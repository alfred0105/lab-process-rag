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

MODEL_VERSION = "gpbo-stage2-2"


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

    def posterior(self, x):
        """Return latent posterior mean and covariance in original target units."""
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
        prior = self.signal_variance * _kernel(xn, xn, self.kernel, length)
        covariance = self.y_scale**2 * (prior - v.T @ v)
        covariance = (covariance + covariance.T) * 0.5
        diagonal = np.maximum(np.diag(covariance), 1e-12)
        np.fill_diagonal(covariance, diagonal)
        if not np.isfinite(mean).all() or not np.isfinite(covariance).all():
            raise OptimizationInputError("GP posterior contains non-finite values")
        return mean, covariance

    def predict_components(self, x):
        mean, covariance = self.posterior(x)
        epistemic = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        # The optimized homoscedastic nugget represents residual observation
        # noise for a future measurement. Known training-row uncertainties are
        # already included heteroscedastically in the conditioning covariance.
        aleatoric = np.full_like(epistemic, self.y_scale * math.sqrt(max(self.noise, 0.0)))
        total = np.sqrt(epistemic**2 + aleatoric**2)
        return mean.tolist(), epistemic.tolist(), aleatoric.tolist(), total.tolist()

    def predict(self, x, *, prediction_type="observation"):
        mean, epistemic, _aleatoric, total = self.predict_components(x)
        if prediction_type == "latent":
            return mean, epistemic
        if prediction_type == "observation":
            return mean, total
        raise OptimizationInputError("prediction_type must be latent or observation")

    def to_dict(self):
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, value):
        version=value.get("model_version")
        if version not in {MODEL_VERSION,"gpbo-mvp-1"}:
            raise OptimizationInputError("Unsupported saved model version")
        # Stage 1 JSON remains readable. Its old predictive std is interpreted
        # as latent posterior uncertainty and the learned nugget supplies the
        # future-observation aleatoric component under the Stage 2 model.
        payload=dict(value)
        payload.setdefault("observation_noise_variance",[0.0]*len(payload.get("x_train",[])))
        return cls(**payload)


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


def noisy_expected_improvement(model, candidates, *, samples=256, seed=7, maximize=True):
    """Monte Carlo noisy EI over the joint latent posterior at observed X and candidates.

    The sampled incumbent is the best latent objective over the noisy baseline
    observations, rather than the best noisy measured value. Candidate values
    are sampled conditionally on each shared baseline draw, preserving their
    posterior dependence. This is a one-candidate qNEI-style acquisition.
    """
    if not isinstance(samples, int) or samples < 32 or samples > 8192:
        raise OptimizationInputError("noisy EI samples must be an integer in [32, 8192]")
    candidates = _matrix(candidates, "Candidates")
    if candidates.shape[1] != len(model.x_mean):
        raise OptimizationInputError("Candidate feature dimension does not match model")
    baseline = np.asarray(model.x_train) * np.asarray(model.x_scale) + np.asarray(model.x_mean)
    baseline_mean, baseline_cov = model.posterior(baseline)
    candidate_mean, candidate_cov = model.posterior(candidates)
    baseline_candidate_cov = _posterior_cross_covariance(model, baseline, candidates)
    baseline_cov = (baseline_cov + baseline_cov.T) * 0.5
    scale = max(float(np.max(np.diag(baseline_cov))), 1.0)
    jitter = scale * 1e-12
    for _ in range(8):
        try:
            chol = np.linalg.cholesky(baseline_cov + np.eye(len(baseline))*jitter)
            break
        except np.linalg.LinAlgError:
            jitter *= 10
    else:
        raise OptimizationInputError("Noisy EI baseline posterior is numerically unstable")
    rng = np.random.default_rng(seed)
    baseline_draws = np.asarray(baseline_mean)[None, :] + rng.standard_normal((samples, len(baseline))) @ chol.T
    weights = np.linalg.solve(chol.T, np.linalg.solve(chol, baseline_candidate_cov))
    conditional_mean = np.asarray(candidate_mean)[None, :] + (baseline_draws - np.asarray(baseline_mean)[None, :]) @ weights
    conditional_variance = np.maximum(np.diag(candidate_cov) - np.sum(baseline_candidate_cov * weights, axis=0), 0.0)
    candidate_draws = conditional_mean + rng.standard_normal(conditional_mean.shape) * np.sqrt(conditional_variance)[None, :]
    signed_baseline = baseline_draws if maximize else -baseline_draws
    signed_candidates = candidate_draws if maximize else -candidate_draws
    incumbent = np.max(signed_baseline, axis=1, keepdims=True)
    return np.mean(np.maximum(signed_candidates - incumbent, 0.0), axis=0)


def _posterior_cross_covariance(model, left, right):
    left = _matrix(left, "Left points"); right = _matrix(right, "Right points")
    xm = np.asarray(model.x_mean); xs = np.asarray(model.x_scale); train = np.asarray(model.x_train)
    left_n = (left-xm)/xs; right_n=(right-xm)/xs
    train_cov = model.signal_variance*_kernel(train,train,model.kernel,np.asarray(model.length_scale))
    train_cov += np.diag(np.asarray(model.observation_noise_variance)+model.jitter)
    try:
        chol=np.linalg.cholesky(train_cov)
        k_train_left=model.signal_variance*_kernel(train,left_n,model.kernel,np.asarray(model.length_scale))
        k_train_right=model.signal_variance*_kernel(train,right_n,model.kernel,np.asarray(model.length_scale))
        v_left=np.linalg.solve(chol,k_train_left)
        v_right=np.linalg.solve(chol,k_train_right)
    except np.linalg.LinAlgError as exc:
        raise OptimizationInputError("GP covariance is numerically unstable") from exc
    prior=model.signal_variance*_kernel(left_n,right_n,model.kernel,np.asarray(model.length_scale))
    return model.y_scale**2*(prior-v_left.T@v_right)


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


def stage2_sandbox_benchmark(kind="all", seed=7, budget=12, seeds=5, noise_level=0.08):
    """Noise-aware and constrained synthetic evaluations; never writes lab records."""
    if kind not in {"noisy","constrained","all"}:
        raise OptimizationInputError("benchmark kind must be noisy, constrained, or all")
    if not 5 <= seeds <= 20 or not 3 <= budget <= 40 or not math.isfinite(noise_level) or not 0 <= noise_level <= 1:
        raise OptimizationInputError("invalid Stage 2 benchmark budget, seed count, or noise level")
    started=time.perf_counter(); result={"base_seed":seed,"seeds":seeds,"additional_evaluations":budget,
        "notice":"Synthetic software benchmark only. It does not establish experimental performance or material science validity."}
    if kind in {"noisy","all"}:
        def objective(x): return (x-0.63)**2 + 0.035*np.sin(12*x)
        domain=np.linspace(0.0,1.0,241); true_values=objective(domain); known=float(np.min(objective(np.linspace(0,1,20001))))
        policies={name:[] for name in ("random_search","gp_ei","gp_noisy_ei")}
        final_locations={name:[] for name in policies}
        for run in range(seeds):
            design_rng=np.random.default_rng(seed+run)
            x0=np.sort(design_rng.choice(domain,4,replace=False)); y0=objective(x0)+design_rng.normal(0,noise_level,4)
            # Give every policy an independent, reproducible stream so one
            # policy's internal sampling cannot change another's noise draws.
            policy_rng={name:np.random.default_rng(seed+run*1009+offset*7919)
                        for offset,name in enumerate(policies, start=1)}
            # Include the shared initial design in both true and observed best
            # values; otherwise a small added-evaluation budget is biased.
            initial_true=objective(x0).astype(float).tolist()
            states={name:(x0.copy(),y0.copy(),initial_true.copy(),[]) for name in policies}
            for _ in range(budget):
                for name,(x_obs,y_obs,true_seen,locs) in states.items():
                    rng=policy_rng[name]
                    if name=="random_search": candidate=float(rng.choice(domain))
                    else:
                        model=GaussianProcess.fit(x_obs[:,None],y_obs,kernel="matern",measurement_std=np.full(len(y_obs),noise_level))
                        if name=="gp_ei":
                            mean,std=model.predict(domain[:,None],prediction_type="latent")
                            scores=acquisition(mean,std,float(np.min(y_obs)),"ei",maximize=False)
                        else:
                            scores=noisy_expected_improvement(model,domain[:,None],samples=128,seed=seed+run*1000+len(locs),maximize=False)
                        candidate=float(domain[int(np.argmax(scores))])
                    true_value=float(objective(candidate)); observed=true_value+float(rng.normal(0,noise_level))
                    x_obs=np.r_[x_obs,candidate]; y_obs=np.r_[y_obs,observed]; true_seen.append(true_value); locs.append(candidate)
                    states[name]=(x_obs,y_obs,true_seen,locs)
            for name,(x_obs,y_obs,true_seen,locs) in states.items():
                policies[name].append({"best_true":float(np.min(true_seen)),"best_observed":float(np.min(y_obs)),"last_x":float(locs[-1])})
                final_locations[name].append(float(locs[-1]))
        summary={}
        for name,runs in policies.items():
            best_true=np.asarray([row["best_true"] for row in runs]); best_observed=np.asarray([row["best_observed"] for row in runs])
            summary[name]={"runs":seeds,"median_best_true_objective":float(np.median(best_true)),"mean_best_true_objective":float(np.mean(best_true)),
                "median_best_observed_objective":float(np.median(best_observed)),"mean_simple_regret":float(np.mean(np.maximum(0,best_true-known))),
                "recommendation_location_std":float(np.std(final_locations[name],ddof=1)) if seeds>1 else 0.0,
                "best_true_by_seed":best_true.tolist(),"best_observed_by_seed":best_observed.tolist()}
        result["noisy"]={"function":"Noisy one-dimensional synthetic objective","noise_std":noise_level,"known_minimum_approx":known,
            "initial_points":4,"policies":summary}
    if kind in {"constrained","all"}:
        bounds=np.array([[-5.,10.],[0.,15.]])
        constraint=lambda points: points[:,0]+points[:,1] <= 9.0
        grid_x,grid_y=np.meshgrid(np.linspace(*bounds[0],501),np.linspace(*bounds[1],501),indexing="ij")
        grid=np.column_stack((grid_x.ravel(),grid_y.ravel()))
        feasible_grid=grid[constraint(grid)]; known=float(np.min(branin(feasible_grid)))
        policies={name:[] for name in ("random_feasible","unconstrained_gp_ei","constraint_aware_gp_ei")}
        for run in range(seeds):
            rng=np.random.default_rng(seed+run); initial=[]
            while len(initial)<5:
                batch=bounds[:,0]+rng.random((64,2))*(bounds[:,1]-bounds[:,0])
                initial.extend(batch[constraint(batch)].tolist())
            x0=np.asarray(initial[:5]); y0=branin(x0)
            # The initial design is feasible by construction and counts toward
            # the best feasible objective for every policy equally.
            states={name:(x0.copy(),y0.copy(),y0.astype(float).tolist(),[]) for name in policies}
            policy_rng={name:np.random.default_rng(seed+run*1009+offset*7919)
                        for offset,name in enumerate(policies, start=1)}
            for _ in range(budget):
                for name,(x_obs,y_obs,feasible_values,violations) in states.items():
                    policy_random=policy_rng[name]
                    proposals=bounds[:,0]+policy_random.random((1600,2))*(bounds[:,1]-bounds[:,0])
                    if name=="random_feasible":
                        valid=proposals[constraint(proposals)]; candidate=valid[int(policy_random.integers(len(valid)))]
                    else:
                        model=GaussianProcess.fit(x_obs,y_obs,kernel="matern")
                        mean,std=model.predict(proposals,prediction_type="latent")
                        score=acquisition(mean,std,float(np.min(y_obs)),"ei",maximize=False)
                        if name=="constraint_aware_gp_ei":
                            mask=constraint(proposals)
                            if not mask.any(): continue
                            candidate=proposals[np.flatnonzero(mask)[int(np.argmax(score[mask]))]]
                        else:
                            candidate=proposals[int(np.argmax(score))]
                    value=float(branin(candidate)); valid=bool(constraint(np.asarray(candidate)[None,:])[0])
                    violations.append(not valid)
                    if valid: feasible_values.append(value)
                    # Benchmark deliberately evaluates the mathematical function
                    # even at violating suggestions to expose unsafe proposals.
                    x_obs=np.vstack([x_obs,candidate]); y_obs=np.r_[y_obs,value]
                    states[name]=(x_obs,y_obs,feasible_values,violations)
            for name,(_x,_y,values,violations) in states.items():
                policies[name].append({"best_feasible":float(np.min(values)) if values else None,"violations":sum(violations),"feasible":len(violations)-sum(violations)})
        summary={}
        for name,runs in policies.items():
            best=np.asarray([row["best_feasible"] if row["best_feasible"] is not None else math.inf for row in runs])
            violation=sum(row["violations"] for row in runs); total=seeds*budget
            finite=best[np.isfinite(best)]
            summary[name]={"runs":seeds,"feasible_recommendation_rate":float((total-violation)/total),"constraint_violation_count":int(violation),
                "median_best_feasible_objective":float(np.median(finite)) if len(finite) else None,
                "mean_simple_regret":float(np.mean(np.maximum(0,finite-known))) if len(finite) else None,
                "best_feasible_by_seed":[None if not np.isfinite(value) else float(value) for value in best]}
        result["constrained"]={"function":"Constrained Branin (synthetic; x1+x2<=9)","known_feasible_minimum_approx":known,
            "initial_points":5,"constraint":"x1 + x2 <= 9","policies":summary,
            "notice":"Unconstrained policy proposals are evaluated only inside this mathematical benchmark to count violations; they are never executable experiment recommendations."}
    result["wall_clock_seconds"]=time.perf_counter()-started
    return result
