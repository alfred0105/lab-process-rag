"""Small, auditable Gaussian-process and Bayesian-optimization MVP.

The implementation is intentionally limited to continuous, single-output
problems. Models are stored as JSON parameters rather than executable pickle.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr

MODEL_VERSION = "gpbo-mvp-1"


class OptimizationInputError(ValueError):
    pass


def _matrix(value, name):
    result = np.asarray(value, dtype=float)
    if result.ndim == 1:
        result = result.reshape(-1, 1)
    if result.ndim != 2 or not np.isfinite(result).all():
        raise OptimizationInputError(f"{name} must be a finite 2D numeric array")
    return result


def _kernel(a, b, kind, length_scale):
    delta = (a[:, None, :] - b[None, :, :]) / np.maximum(length_scale, 1e-8)
    distance = np.sqrt(np.maximum(np.sum(delta * delta, axis=2), 0.0))
    if kind == "rbf":
        return np.exp(-0.5 * distance * distance)
    if kind == "matern":
        root5 = math.sqrt(5.0) * distance
        return (1 + root5 + (5.0 / 3.0) * distance * distance) * np.exp(-root5)
    raise OptimizationInputError("kernel must be rbf or matern")


@dataclass
class GaussianProcess:
    x_mean: list[float]
    x_scale: list[float]
    y_mean: float
    y_scale: float
    x_train: list[list[float]]
    alpha: list[float]
    observation_noise_variance: list[float]
    length_scale: list[float]
    signal_variance: float
    noise: float
    kernel: str
    jitter: float
    model_version: str = MODEL_VERSION

    @classmethod
    def fit(cls, x, y, *, kernel="matern", noise=1e-6, measurement_std=None):
        x = _matrix(x, "X")
        y = np.asarray(y, dtype=float).reshape(-1)
        if len(x) != len(y) or len(y) < 2:
            raise OptimizationInputError("At least two paired observations are required")
        if not np.isfinite(y).all() or not math.isfinite(float(noise)) or noise < 0:
            raise OptimizationInputError("y must be finite and noise must be non-negative")
        if kernel not in {"rbf", "matern"}:
            raise OptimizationInputError("kernel must be rbf or matern")
        xm = x.mean(axis=0); xs = x.std(axis=0); xs[xs < 1e-12] = 1.0
        ym = float(y.mean()); ys = float(y.std())
        if ys < 1e-12: ys = 1.0
        xn = (x - xm) / xs; yn = (y - ym) / ys
        n, d = xn.shape
        base_noise = max(float(noise), 1e-8)
        if measurement_std is None:
            observation_variance=np.zeros(n)
        else:
            measurement_std=np.asarray(measurement_std,dtype=float).reshape(-1)
            if len(measurement_std)!=n or not np.isfinite(measurement_std).all() or (measurement_std<0).any():
                raise OptimizationInputError("measurement standard deviations must be finite, non-negative, and match y")
            observation_variance=(measurement_std/ys)**2

        def objective(log_params):
            length = np.exp(log_params[:d]); signal = math.exp(float(log_params[d])); nugget = math.exp(float(log_params[d+1]))
            cov = signal * _kernel(xn, xn, kernel, length) + np.diag(observation_variance+nugget+1e-10)
            try:
                chol = np.linalg.cholesky(cov)
                alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, yn))
                return float(0.5 * yn @ alpha + np.log(np.diag(chol)).sum() + 0.5*n*math.log(2*math.pi))
            except np.linalg.LinAlgError:
                return 1e30

        initial = np.r_[np.zeros(d), 0.0, math.log(base_noise)]
        opt = minimize(objective, initial, method="L-BFGS-B", bounds=[(-5, 5)]*d + [(-5, 5), (-18, 1)])
        params = opt.x if np.isfinite(opt.fun) else initial
        length = np.exp(params[:d]); signal = math.exp(float(params[d])); learned_noise = max(math.exp(float(params[d+1])), base_noise)
        jitter = max(learned_noise, 1e-10)
        for _ in range(8):
            cov = signal * _kernel(xn, xn, kernel, length) + np.diag(observation_variance+jitter)
            try:
                chol = np.linalg.cholesky(cov)
                alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, yn))
                break
            except np.linalg.LinAlgError:
                jitter *= 10
        else:
            raise OptimizationInputError("Covariance matrix remained numerically unstable")
        return cls(xm.tolist(), xs.tolist(), ym, ys, xn.tolist(), alpha.tolist(), observation_variance.tolist(), length.tolist(), signal, learned_noise, kernel, jitter)

    def predict(self, x):
        x = _matrix(x, "X")
        if x.shape[1] != len(self.x_mean):
            raise OptimizationInputError("Candidate feature dimension does not match model")
        xn = (x - np.array(self.x_mean)) / np.array(self.x_scale)
        train = np.asarray(self.x_train); alpha = np.asarray(self.alpha)
        length = np.asarray(self.length_scale)
        k = self.signal_variance*_kernel(xn, train, self.kernel, length)
        k_train = self.signal_variance*_kernel(train, train, self.kernel, length)
        cov = k_train + np.diag(np.asarray(self.observation_noise_variance)+self.jitter)
        chol = np.linalg.cholesky(cov)
        mean = np.array(self.y_mean) + self.y_scale*(k @ alpha)
        v = np.linalg.solve(chol, k.T)
        variance = np.maximum(self.signal_variance - np.sum(v*v, axis=0), 1e-12)
        std = self.y_scale*np.sqrt(variance)
        return mean.tolist(), std.tolist()

    def to_dict(self):
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, value):
        if value.get("model_version") != MODEL_VERSION:
            raise OptimizationInputError("Unsupported saved model version")
        return cls(**value)


def acquisition(mean, std, best, name, *, maximize=True, kappa=2.0, xi=0.01):
    mean = np.asarray(mean, dtype=float); std = np.asarray(std, dtype=float)
    if not np.isfinite(mean).all() or not np.isfinite(std).all() or (std < 0).any():
        raise OptimizationInputError("Prediction mean/std must be finite and std non-negative")
    signed = mean if maximize else -mean
    incumbent = best if maximize else -best
    improvement = signed - incumbent - xi
    safe = np.maximum(std, 1e-12)
    z = improvement / safe
    if name == "ei":
        score = improvement*ndtr(z) + safe*np.exp(-0.5*z*z)/math.sqrt(2*math.pi)
        return np.where(std <= 1e-10, np.maximum(improvement, 0), score)
    if name == "pi":
        return np.where(std <= 1e-10, (improvement > 0).astype(float), ndtr(z))
    if name == "ucb":
        return signed + float(kappa)*std
    raise OptimizationInputError("acquisition must be ei, pi, or ucb")


def dataset_hash(rows):
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def metrics(y_true, mean, std):
    y = np.asarray(y_true, dtype=float); p = np.asarray(mean, dtype=float); s = np.maximum(np.asarray(std, dtype=float), 1e-12)
    rmse = float(np.sqrt(np.mean((y-p)**2))); mae = float(np.mean(np.abs(y-p)))
    nlpd = float(np.mean(0.5*np.log(2*np.pi*s*s) + (y-p)**2/(2*s*s)))
    coverage = float(np.mean(np.abs(y-p) <= 1.96*s))
    return {"rmse": rmse, "mae": mae, "nlpd": nlpd, "coverage_95": coverage}


def branin(x):
    x = np.asarray(x, dtype=float)
    x1, x2 = x[..., 0], x[..., 1]
    a=1; b=5.1/(4*math.pi**2); c=5/math.pi; r=6; s=10; t=1/(8*math.pi)
    return a*(x2-b*x1*x1+c*x1-r)**2 + s*(1-t)*np.cos(x1) + s


def sandbox_benchmark(seed=7, budget=20, seeds=5):
    """Compare Random, Latin-hypercube, GP-EI and GP-UCB on Branin.

    Every policy shares a seed-specific five-point initial design and evaluation
    budget. This deterministic benchmark supports software evaluation only.
    """
    started=time.perf_counter()
    bounds=np.array([[-5.0,10.0],[0.0,15.0]])
    policies=("random_search","latin_hypercube","gp_ei","gp_ucb")
    all_traces={name:[] for name in policies}
    for replicate in range(seeds):
        rng=np.random.default_rng(seed+replicate)
        x0=bounds[:,0]+rng.random((5,2))*(bounds[:,1]-bounds[:,0]); y0=branin(x0)
        # Latin Hypercube: stratify each dimension independently across the
        # additional budget, with randomized permutations and within-bin jitter.
        lhs=np.empty((budget,2))
        for dim in range(2):
            lhs[:,dim]=(rng.permutation(budget)+rng.random(budget))/budget
        lhs=bounds[:,0]+lhs*(bounds[:,1]-bounds[:,0])
        state={name:(x0.copy(),y0.copy(),[]) for name in policies}
        for step in range(budget):
            for name in policies:
                x_obs,y_obs,trace=state[name]
                if name=="random_search":
                    candidate=bounds[:,0]+rng.random(2)*(bounds[:,1]-bounds[:,0])
                elif name=="latin_hypercube":
                    candidate=lhs[step]
                else:
                    model=GaussianProcess.fit(x_obs,y_obs,kernel="matern")
                    candidates=bounds[:,0]+rng.random((1200,2))*(bounds[:,1]-bounds[:,0])
                    mean,std=model.predict(candidates)
                    acq="ei" if name=="gp_ei" else "ucb"
                    score=acquisition(mean,std,float(np.min(y_obs)),acq,maximize=False)
                    candidate=candidates[int(np.argmax(score))]
                x_obs=np.vstack((x_obs,candidate)); y_obs=np.r_[y_obs,float(branin(candidate))]
                trace.append(float(np.min(y_obs)))
                state[name]=(x_obs,y_obs,trace)
        for name in policies: all_traces[name].append(state[name][2])
    optimum=0.397887
    summary={}
    for name,traces in all_traces.items():
        best=np.asarray([trace[-1] for trace in traces],dtype=float)
        regret=np.maximum(0,best-optimum)
        summary[name]={"runs":int(seeds),"mean_best":float(np.mean(best)),"median_best":float(np.median(best)),
            "std_best":float(np.std(best,ddof=1)) if seeds>1 else 0.0,"mean_simple_regret":float(np.mean(regret)),
            "median_simple_regret":float(np.median(regret)),"best_by_seed":best.tolist(),
            "mean_best_trace":np.mean(np.asarray(traces),axis=0).tolist()}
    return {"function":"Branin (synthetic sandbox)","known_global_minimum_approx":optimum,"base_seed":seed,"seeds":seeds,
            "initial_points":5,"additional_evaluations":budget,"policies":summary,
            "wall_clock_seconds":time.perf_counter()-started,
            "notice":"Synthetic benchmark only; these optimizer results do not establish experimental success or performance on research materials."}
