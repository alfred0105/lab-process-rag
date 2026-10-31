"""Auditable two-objective GP, Pareto, hypervolume and MC-HVI utilities.

Independent objective GPs are an explicit modeling assumption. Synthetic
benchmark helpers in this module never create ScientificObservation rows.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import sys

import numpy as np

from .gpbo import GaussianProcess, OptimizationInputError, acquisition, branin, _posterior_cross_covariance

MODEL_VERSION = "gpbo-moo-stage3-1"
OBJECTIVES = 2


def _finite_matrix(values, name, *, columns=None):
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 and columns is not None:
        return np.empty((0, columns), dtype=float)
    if arr.ndim != 2 or (columns is not None and arr.shape[1] != columns) or not np.isfinite(arr).all():
        raise OptimizationInputError(f"{name} must be a finite 2D matrix")
    return arr


def orient(values, directions):
    """Map mixed objectives to minimization coordinates."""
    arr = np.asarray(values, dtype=float)
    if arr.shape[-1] != OBJECTIVES or len(directions) != OBJECTIVES or not np.isfinite(arr).all():
        raise OptimizationInputError("Exactly two finite objectives and directions are required")
    if any(direction not in {"minimize", "maximize"} for direction in directions):
        raise OptimizationInputError("Objective direction must be minimize or maximize")
    signs = np.array([1.0 if item == "minimize" else -1.0 for item in directions])
    result = arr * signs
    if not np.isfinite(result).all():
        raise OptimizationInputError("Objective direction conversion overflowed")
    return result


def pareto_front(values, directions=("minimize", "minimize"), *, ids=None, feasible=None):
    """Return indices of unique non-dominated feasible points; exact dominance."""
    points = _finite_matrix(values, "objective values", columns=2)
    ids = list(range(len(points))) if ids is None else list(ids)
    if len(ids) != len(points):
        raise OptimizationInputError("Point IDs must match objective row count")
    mask = np.ones(len(points), dtype=bool) if feasible is None else np.asarray(feasible, dtype=bool)
    if mask.shape != (len(points),):
        raise OptimizationInputError("Feasibility mask must match objective rows")
    oriented = orient(points, directions)
    ranks = [-1] * len(points)
    remaining = {i for i in range(len(points)) if mask[i]}
    keep = []
    rank_value = 0
    while remaining:
        layer = []
        for i in remaining:
            if not any(j != i and np.all(oriented[j] <= oriented[i]) and np.any(oriented[j] < oriented[i]) for j in remaining):
                layer.append(i)
        if not layer:  # Defensive guard for numerical/pathological input.
            break
        for i in layer:
            ranks[i] = rank_value
        if rank_value == 0:
            keep = sorted(layer)
        remaining.difference_update(layer)
        rank_value += 1
    # Equal objective vectors represent one front location; retain all IDs in
    # metadata while returning a deterministic single representative index.
    unique = []
    seen = set()
    for index in keep:
        key = tuple(oriented[index].tolist())
        if key not in seen:
            seen.add(key)
            unique.append(index)
    return {"indices": unique, "ids": [ids[i] for i in unique], "rank": ranks,
            "oriented_values": oriented.tolist(), "duplicate_front_ids": {
                str(ids[unique_index]): [ids[i] for i in keep if np.array_equal(oriented[i], oriented[unique_index])]
                for unique_index in unique}}


def hypervolume_2d(values, reference_point, directions=("minimize", "minimize"), *, scale=None):
    """Exact union area of dominated rectangles in two-dimensional minimization space."""
    points = _finite_matrix(values, "objective values", columns=2)
    ref = np.asarray(reference_point, dtype=float)
    if ref.shape != (2,) or not np.isfinite(ref).all():
        raise OptimizationInputError("Reference point must contain two finite values")
    oriented = orient(points, directions)
    oriented_ref = orient(ref.reshape(1, 2), directions)[0]
    scales = np.ones(2) if scale is None else np.asarray(scale, dtype=float)
    if scales.shape != (2,) or not np.isfinite(scales).all() or (scales <= 0).any():
        raise OptimizationInputError("Objective scales must be two positive finite values")
    oriented = oriented / scales
    oriented_ref = oriented_ref / scales
    if len(oriented) == 0:
        return 0.0
    front = pareto_front(points, directions)["indices"]
    oriented = oriented[front]
    if np.any(oriented >= oriented_ref):
        raise OptimizationInputError("Reference point must be strictly worse than every included Pareto point")
    pts = sorted(oriented, key=lambda p: (p[0], p[1]))
    area = 0.0
    best_y = oriented_ref[1]
    for x, y in pts:
        if y < best_y:
            area += max(oriented_ref[0] - x, 0.0) * (best_y - y)
            best_y = y
            if not math.isfinite(area):
                raise OptimizationInputError("Hypervolume overflowed; rescale objectives and reference point")
    return float(area)


def _validate_reference(front, reference, directions, scales):
    # Empty baseline is permitted only when a finite reference is supplied.
    ref = np.asarray(reference, dtype=float)
    if ref.shape != (2,) or not np.isfinite(ref).all():
        raise OptimizationInputError("Reference point must contain two finite values")
    if len(front):
        hypervolume_2d(front, reference, directions, scale=scales)
    return ref


def mc_hvi(models, candidates, front, reference_point, directions, *, scales=None, samples=256, seed=7):
    """Expected HV improvement using the full candidate posterior covariance per GP."""
    x = _finite_matrix(candidates, "candidates")
    if len(models) != 2 or any(x.shape[1] != len(model.x_mean) for model in models):
        raise OptimizationInputError("Two compatible objective GPs are required")
    if not isinstance(samples, int) or samples < 32 or samples > 4096:
        raise OptimizationInputError("Monte Carlo samples must be an integer in [32, 4096]")
    front_arr = _finite_matrix(front, "Pareto baseline", columns=2) if len(front) else np.empty((0, 2))
    scales_arr = np.ones(2) if scales is None else np.asarray(scales, dtype=float)
    _validate_reference(front_arr, reference_point, directions, scales_arr)
    # Keep memory bounded: candidate pool is capped separately at API boundary.
    rng = np.random.default_rng(seed)
    draws = []
    for objective_index, model in enumerate(models):
        mean, covariance = model.posterior(x)
        covariance = (covariance + covariance.T) * 0.5
        jitter = max(float(np.max(np.diag(covariance))) if len(x) else 0.0, 1.0) * 1e-12
        for _ in range(8):
            try:
                chol = np.linalg.cholesky(covariance + np.eye(len(x)) * jitter)
                break
            except np.linalg.LinAlgError:
                jitter *= 10
        else:
            raise OptimizationInputError("Candidate joint posterior is numerically unstable")
        draws.append(np.asarray(mean)[None, :] + rng.standard_normal((samples, len(x))) @ chol.T)
    samples_array = np.stack(draws, axis=-1)
    oriented_samples = orient(samples_array, directions) / scales_arr
    oriented_ref = orient(np.asarray(reference_point).reshape(1, 2), directions)[0] / scales_arr
    base_hv = hypervolume_2d(front_arr, reference_point, directions, scale=scales_arr) if len(front_arr) else 0.0
    scores = np.zeros(len(x))
    for index in range(len(x)):
        for draw in samples_array[:, index, :]:
            if np.any(orient(draw.reshape(1, 2), directions)[0] / scales_arr >= oriented_ref):
                continue
            hv = hypervolume_2d(np.vstack([front_arr, draw]), reference_point, directions, scale=scales_arr) if len(front_arr) else hypervolume_2d(draw.reshape(1, 2), reference_point, directions, scale=scales_arr)
            scores[index] += max(hv - base_hv, 0.0)
    return scores / samples


def greedy_batch(models, candidates, front, reference_point, directions, *, scales=None, samples=256, seed=7, q=1, min_distance=1e-6, feature_scales=None):
    """Greedy joint MC-HVI; common GP posterior draws preserve within-objective correlation."""
    if not isinstance(q, int) or q < 1 or q > 4:
        raise OptimizationInputError("Batch size must be in [1, 4]")
    x = _finite_matrix(candidates, "candidates")
    if len(x) < q:
        raise OptimizationInputError("NO_FEASIBLE_BATCH: fewer feasible candidates than requested")
    ref = np.asarray(reference_point, dtype=float)
    distance_scales = np.ones(x.shape[1]) if feature_scales is None else np.asarray(feature_scales, dtype=float)
    if distance_scales.shape != (x.shape[1],) or not np.isfinite(distance_scales).all() or np.any(distance_scales <= 0):
        raise OptimizationInputError("Feature scales for candidate diversity must be positive finite values")
    scales_arr = np.ones(2) if scales is None else np.asarray(scales, dtype=float)
    front_arr = _finite_matrix(front, "Pareto baseline", columns=2) if len(front) else np.empty((0, 2))
    _validate_reference(front_arr, ref, directions, scales_arr)
    # Reuse reproducible correlated joint samples for every greedy addition.
    rng = np.random.default_rng(seed)
    draws = []
    for model in models:
        mean, covariance = model.posterior(x)
        covariance = (covariance + covariance.T) * .5
        jitter = max(float(np.max(np.diag(covariance))), 1.0) * 1e-12
        for _ in range(8):
            try:
                chol = np.linalg.cholesky(covariance + np.eye(len(x)) * jitter); break
            except np.linalg.LinAlgError: jitter *= 10
        else: raise OptimizationInputError("Joint posterior sampling is numerically unstable")
        draws.append(np.asarray(mean)[None, :] + rng.standard_normal((samples, len(x))) @ chol.T)
    raw_objective_draws = np.stack(draws, axis=-1)
    objective_draws = orient(raw_objective_draws, directions) / scales_arr
    ref_o = orient(ref.reshape(1, 2), directions)[0] / scales_arr
    base_o = orient(front_arr, directions) / scales_arr
    base_hv = hypervolume_2d(front_arr, ref, directions, scale=scales_arr) if len(front_arr) else 0.0
    selected, marginal, marginal_se = [], [], []
    for _ in range(q):
        best_idx, best_gain, best_se = None, -1.0, 0.0
        for idx in range(len(x)):
            if idx in selected or any(np.linalg.norm((x[idx] - x[j]) / distance_scales) <= min_distance for j in selected):
                continue
            gains = []
            for sample in range(samples):
                current = [raw_objective_draws[sample, j] for j in selected
                           if np.all(objective_draws[sample, j] < ref_o)]
                before = np.vstack([front_arr, np.asarray(current)]) if current else front_arr
                if np.any(objective_draws[sample, idx] >= ref_o):
                    gains.append(0.0); continue
                after = np.vstack([before, raw_objective_draws[sample, idx]])
                before_hv = hypervolume_2d(before, ref, directions, scale=scales_arr) if len(before) else 0.0
                after_hv = hypervolume_2d(after, ref, directions, scale=scales_arr)
                gains.append(max(after_hv - before_hv, 0.0))
            gain = float(np.mean(gains))
            if gain > best_gain:
                best_idx, best_gain = idx, gain
                best_se = float(np.std(gains, ddof=1) / math.sqrt(len(gains))) if len(gains) > 1 else 0.0
        if best_idx is None:
            raise OptimizationInputError("NO_FEASIBLE_BATCH: no sufficiently distinct feasible candidate remains")
        selected.append(best_idx); marginal.append(best_gain); marginal_se.append(best_se)
    # Estimate the reported batch gain on independent validation draws to
    # reduce winner's-curse bias from reusing acquisition samples for selection.
    chosen_x = x[selected]
    eval_rng = np.random.default_rng(seed + 1_000_003)
    evaluation_draws = []
    for model in models:
        mean, covariance = model.posterior(chosen_x)
        covariance = (covariance + covariance.T) * .5
        jitter = max(float(np.max(np.diag(covariance))), 1.0) * 1e-12
        for _ in range(8):
            try:
                chol = np.linalg.cholesky(covariance + np.eye(q) * jitter); break
            except np.linalg.LinAlgError: jitter *= 10
        else: raise OptimizationInputError("Batch validation posterior is numerically unstable")
        evaluation_draws.append(np.asarray(mean)[None, :] + eval_rng.standard_normal((samples, q)) @ chol.T)
    evaluation_values = np.stack(evaluation_draws, axis=-1)
    eval_gains = [[] for _ in range(q)]
    for sample in range(samples):
        current = front_arr.copy()
        current_hv = base_hv
        for k in range(q):
            point = evaluation_values[sample, k]
            if np.any(orient(point.reshape(1, 2), directions)[0] / scales_arr >= ref_o):
                gain = 0.0
            else:
                updated = np.vstack([current, point])
                updated_hv = hypervolume_2d(updated, ref, directions, scale=scales_arr)
                gain = max(updated_hv - current_hv, 0.0)
                current, current_hv = updated, updated_hv
            eval_gains[k].append(gain)
    marginal = [float(np.mean(gains)) for gains in eval_gains]
    marginal_se = [float(np.std(gains, ddof=1) / math.sqrt(len(gains))) if len(gains) > 1 else 0.0 for gains in eval_gains]
    total_draw_gains = np.sum(np.asarray(eval_gains, dtype=float), axis=0)
    return {"indices": selected, "marginal_ehvi": marginal, "marginal_ehvi_mc_standard_error": marginal_se,
            "total_expected_batch_hvi": float(np.mean(total_draw_gains)),
            "total_expected_batch_hvi_mc_standard_error": float(np.std(total_draw_gains, ddof=1) / math.sqrt(len(total_draw_gains))) if len(total_draw_gains) > 1 else 0.0,
            "batch_method": "greedy_mc_hvi", "posterior_joint_sampling": True, "baseline_hypervolume": base_hv}


def zdt1(x):
    """Two-objective ZDT1 benchmark (minimize both), deterministic software fixture only."""
    arr = _finite_matrix(x, "ZDT1 inputs")
    if arr.shape[1] < 2 or np.any(arr < 0) or np.any(arr > 1):
        raise OptimizationInputError("ZDT1 expects at least two variables in [0, 1]")
    f1 = arr[:, 0]
    g = 1 + 9 * arr[:, 1:].mean(axis=1)
    f2 = g * (1 - np.sqrt(f1 / g))
    return np.column_stack([f1, f2])


def branin_currin(x):
    """Normalized Branin–Currin pair; software benchmark, not lab data."""
    arr = _finite_matrix(x, "Branin-Currin inputs")
    if arr.shape[1] != 2 or np.any(arr < 0) or np.any(arr > 1):
        raise OptimizationInputError("Branin-Currin expects two variables in [0, 1]")
    mapped = np.column_stack([-5 + 15 * arr[:, 0], 15 * arr[:, 1]])
    b = np.asarray(branin(mapped), dtype=float)
    # Branin is minimized while negative Currin corresponds to maximizing the
    # standard Currin response; fixed scales keep objectives dimensionless.
    x1 = np.maximum(arr[:, 0], 1e-6); x2 = np.maximum(arr[:, 1], 1e-6)
    currin = (1 - np.exp(-1 / (2 * x2))) * (2300*x1**3 + 1900*x1**2 + 2092*x1 + 60) / (100*x1**3 + 500*x1**2 + 4*x1 + 20)
    return np.column_stack([b / 310.0, -currin / 14.0])


def _reference_hv(function, *, samples=220):
    grid = np.linspace(0.002, 0.998, samples)
    if function == "zdt1":
        x = np.column_stack([grid, np.zeros_like(grid)])
        ref = np.array([1.1, 10.1])
        directions = ("minimize", "minimize")
        return zdt1(x), ref, directions
    # A dense deterministic grid gives a reproducible approximate reference
    # front for Branin–Currin; it is explicitly labeled an estimate.
    mesh = np.array(np.meshgrid(grid[::4], grid[::4])).reshape(2, -1).T
    values = branin_currin(mesh)
    front = pareto_front(values)["indices"]
    ref = np.array([2.1, 0.2])
    return values[front], ref, ("minimize", "minimize")


def run_moo_benchmarks(*, seed=7, seeds=5, budget=10, mc_samples=32, candidate_pool_size=48):
    """Equal-evaluation-budget comparison for 2 synthetic MOO benchmarks.

    Reports software behavior only. Every policy receives an identical initial
    design and total objective-pair evaluation count for each seed.
    """
    import resource
    import time
    if seeds != 5 or budget < 8 or budget > 16:
        raise OptimizationInputError("Stage 3 benchmark uses exactly five seeds and evaluation budget [8, 16]")
    if not 32 <= mc_samples <= 256 or not 24 <= candidate_pool_size <= 96:
        raise OptimizationInputError("Benchmark MC samples or candidate pool exceed the safe range")
    started = time.perf_counter()
    policies = ("random_feasible_search", "scalarized_gp", "single_mc_ehvi", "greedy_batch_mc_hvi")
    output = {}
    for function_name, function in (("ZDT1", zdt1), ("Branin-Currin", branin_currin)):
        _reference, ref, directions = _reference_hv("zdt1" if function_name == "ZDT1" else "branin_currin")
        reference_hv = hypervolume_2d(_reference, ref, directions)
        runs = {policy: [] for policy in policies}
        for run_index in range(seeds):
            run_seed = seed + run_index
            rng0 = np.random.default_rng(run_seed)
            initial_x = rng0.random((6, 2))
            for policy in policies:
                policy_started = time.perf_counter()
                x = initial_x.copy(); y = function(x)
                rng = np.random.default_rng(run_seed + 1009)
                while len(x) < budget:
                    count = budget - len(x)
                    if policy == "random_feasible_search":
                        proposal = rng.random((count, 2))
                    else:
                        models = [GaussianProcess.fit(x, y[:, j], kernel="matern", noise=1e-6) for j in range(2)]
                        pool = rng.random((candidate_pool_size, 2))
                        if policy == "scalarized_gp":
                            scales = np.std(y, axis=0); scales[scales < 1e-12] = 1
                            scalar = np.mean((y - np.mean(y, axis=0)) / scales, axis=1)
                            scalar_model = GaussianProcess.fit(x, scalar)
                            mean, std = scalar_model.predict(pool, prediction_type="latent")
                            scores = acquisition(mean, std, float(np.min(scalar)), "ei", maximize=False)
                            proposal = pool[[int(np.argmax(scores))]]
                        elif policy == "single_mc_ehvi":
                            current_front = pareto_front(y)["indices"]
                            score = mc_hvi(models, pool, y[current_front], ref, directions,
                                           samples=mc_samples, seed=run_seed + len(x))
                            proposal = pool[[int(np.argmax(score))]]
                        else:
                            current_front = pareto_front(y)["indices"]
                            batch_count = min(2, count)
                            chosen = greedy_batch(models, pool, y[current_front], ref, directions,
                                samples=mc_samples, seed=run_seed + len(x), q=batch_count, min_distance=0.025)
                            proposal = pool[chosen["indices"]]
                    x = np.vstack([x, proposal]); y = np.vstack([y, function(proposal)])
                final_front = pareto_front(y)["indices"]
                hv = hypervolume_2d(y[final_front], ref, directions)
                unique = len({tuple(np.round(p, 8)) for p in x[6:]})
                distances = [np.linalg.norm(x[i] - x[j]) for i in range(6, len(x)) for j in range(i+1, len(x))]
                runs[policy].append({"seed": run_seed, "hypervolume": hv, "pareto_front_size": len(final_front),
                    "dominated_candidate_ratio": 1 - len(final_front)/len(y), "feasible_recommendation_rate": 1.0,
                    "duplicate_candidate_rate": 1 - unique/max(len(x)-6, 1),
                    "batch_diversity_mean_distance": float(np.mean(distances)) if distances else 0.0,
                    "evaluation_budget": len(y), "runtime_seconds": time.perf_counter()-policy_started})
        summary = {}
        for name, values in runs.items():
            hvs = np.asarray([row["hypervolume"] for row in values])
            summary[name] = {"runs": values, "median_hypervolume": float(np.median(hvs)),
                "mean_hypervolume": float(np.mean(hvs)), "mean_hypervolume_regret_to_reference": float(np.mean(np.maximum(reference_hv-hvs, 0))),
                "median_pareto_front_size": float(np.median([row["pareto_front_size"] for row in values])),
                "feasible_recommendation_rate": 1.0,
                "duplicate_candidate_rate": float(np.mean([row["duplicate_candidate_rate"] for row in values])),
                "batch_diversity_mean_distance": float(np.mean([row["batch_diversity_mean_distance"] for row in values])),
                "median_runtime_seconds": float(np.median([row["runtime_seconds"] for row in values]))}
        output[function_name] = {"policies": summary, "reference_point": ref.tolist(), "reference_hypervolume": reference_hv,
            "reference_front_source": "analytical ZDT1 front" if function_name == "ZDT1" else "dense deterministic Branin-Currin grid approximation",
            "seeds": [seed + i for i in range(seeds)], "evaluation_budget_per_policy_per_seed": budget,
            "initial_design_size": 6, "objective_directions": list(directions)}
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = int(rss if sys.platform == "darwin" else rss * 1024)
    return {"benchmark_version": MODEL_VERSION, "mode": "sandbox", "benchmarks": output,
        "environment": {"os": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
        "seed": seed, "seeds": seeds, "evaluation_budget": budget, "mc_samples": mc_samples,
        "candidate_pool_size": candidate_pool_size, "runtime_seconds": time.perf_counter()-started,
        "peak_rss_bytes_process_high_water": rss_bytes,
        "notice": "Synthetic algorithm comparison for software validation only. No experimental evidence, scientific validity, causal claim, or recommendation success probability is established. Equal total objective-pair evaluation budgets are used within each seed."}


def benchmark_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
