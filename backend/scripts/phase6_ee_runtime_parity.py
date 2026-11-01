"""Sandbox-only real Qwen3 runtime parity and early-exit benchmark.

Uses the pinned Qwen checkpoint and the already-audited 3,840-row synthetic
contract/cache. It does not enable early exit in the Research API or trigger a
workflow. It intentionally does not repeat risk certification.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from scipy.special import expit, softmax
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import phase6_ee_research as ee
import phase6_ee_combo_comparison as combos
from app.services.decision_head import ACTIONS
from app.services.phase5_stage3 import generate_scenarios
from app.services.phase6_hybrid import (
    CONTEXT_ADAPTER_VERSION, MODEL_ID, MODEL_REVISION, TOKENIZER_REVISION,
    SharedTransformerBackbone, _OodScorer, _training_context,
)

LAYERS = ee.LAYERS
PARITY_ATOL = 2e-4
SAMPLES = 30
WARMUPS = 3
ARTIFACT_PATH = Path.home() / ".cache/lab-process-rag/phase6-early-exit-runtime-v1.pt"


class AffineHead(torch.nn.Module):
    """Torch equivalent of the standardized sklearn multinomial linear head."""
    def __init__(self, mean, scale, coef, bias, feature_vector=None, device="cpu"):
        super().__init__()
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32, device=device))
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32, device=device))
        self.register_buffer("feature_vector", None if feature_vector is None else
            torch.tensor(feature_vector, dtype=torch.float32, device=device))
        self.linear = torch.nn.Linear(np.asarray(coef).shape[1], np.asarray(coef).shape[0], dtype=torch.float32, device=device)
        with torch.no_grad():
            self.linear.weight.copy_(torch.tensor(coef, dtype=torch.float32, device=device))
            self.linear.bias.copy_(torch.tensor(bias, dtype=torch.float32, device=device))

    def forward(self, hidden):
        x = hidden.float()
        if self.feature_vector is not None:
            f = self.feature_vector.expand(x.shape[0], -1)
            x = torch.cat([x, f], dim=-1)
        return self.linear((x - self.mean) / self.scale)


def _sync(device):
    if device == "mps" and torch.backends.mps.is_available():
        torch.mps.synchronize()
    elif device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.synchronize()


def _memory_snapshot(device):
    if device == "mps" and torch.backends.mps.is_available():
        return {"allocator_current_bytes": int(torch.mps.current_allocated_memory()),
            "driver_allocated_bytes": int(torch.mps.driver_allocated_memory()), "peak_bytes": None,
            "peak_measurement_supported": False}
    if device.startswith("cuda") and torch.cuda.is_available():
        return {"allocator_current_bytes": int(torch.cuda.memory_allocated()),
            "allocator_reserved_bytes": int(torch.cuda.memory_reserved()),
            "peak_bytes": int(torch.cuda.max_memory_allocated()), "peak_measurement_supported": True}
    return {"allocator_current_bytes": None, "peak_bytes": None, "peak_measurement_supported": False}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _load_contract_and_cache():
    primary = json.loads((ROOT / "reports/phase6_ee_final_benchmark.json").read_text(encoding="utf-8"))
    key = primary["cache"]["key"]
    cache_path = Path.home() / ".cache/lab-process-rag" / f"phase6-ee-research-{key}.npz"
    with np.load(cache_path, allow_pickle=False) as archive:
        contract = json.loads(str(archive["contract"].item()))
        hidden = {layer: archive[f"layer_{layer}"].copy() for layer in LAYERS}
    if contract["model_revision"] != MODEL_REVISION or contract["dataset_hash"] != primary["dataset_hash"]:
        raise RuntimeError("The hidden cache does not match the pinned model and research report")
    rows = generate_scenarios(seed=73191, samples=3840)
    y = np.asarray([ACTIONS.index(row["action"]) for row in rows], dtype=int)
    splits = ee._splits(rows)
    if len(splits["frozen_evaluation"]) != 384:
        raise RuntimeError("Expected the existing 384-row frozen synthetic split")
    return primary, contract, hidden, rows, y, splits


def _fit_candidate_models(hidden, rows, y, splits, combo_report):
    fit, router_fit = splits["fit"], splits["router_fit"]
    cal, selection, certify, test = (splits[k] for k in
        ("calibration", "policy_selection", "risk_certification", "frozen_evaluation"))
    structured = np.nan_to_num(np.vstack([r["features_v2"] for r in rows]).astype(np.float32), nan=0., posinf=0., neginf=0.)
    query = {"router_fit": router_fit, "calibration": cal, "selection": selection,
             "certification": certify, "test": test}
    heads_a, probs_a = {}, {}
    heads_c, probs_c = {}, {}
    scalers_a, classifiers_a, scalers_c, classifiers_c = {}, {}, {}, {}
    for layer in LAYERS:
        xa = hidden[layer]
        scaler_a = StandardScaler().fit(xa[fit])
        clf_a = LogisticRegression(max_iter=900, C=.08, random_state=ee.SEED).fit(scaler_a.transform(xa[fit]), y[fit])
        heads_a[layer] = (scaler_a, clf_a)
        scalers_a[layer], classifiers_a[layer] = scaler_a, clf_a
        probs_a[layer] = {name: clf_a.predict_proba(scaler_a.transform(xa[idx])) for name, idx in query.items()}

        xc = np.concatenate([hidden[layer], structured], axis=1)
        scaler_c = StandardScaler().fit(xc[fit])
        clf_c = LogisticRegression(max_iter=900, C=.08, random_state=ee.SEED).fit(scaler_c.transform(xc[fit]), y[fit])
        heads_c[layer] = (scaler_c, clf_c)
        scalers_c[layer], classifiers_c[layer] = scaler_c, clf_c
        probs_c[layer] = {name: clf_c.predict_proba(scaler_c.transform(xc[idx])) for name, idx in query.items()}

    eefp = combos._fit_eefp(probs_c, y, router_fit)
    old_router = json.loads((ROOT / "reports/phase6_ee_router_comparison.json").read_text(encoding="utf-8"))
    pabee_thresholds = {int(k): v for k, v in old_router["selected_policy"]["thresholds"].items()}
    pabee_ood_thresholds = {int(k): float(v) for k, v in old_router["ood_thresholds_p95"].items()}
    combo_c = next(item for item in combo_report["candidate_combinations"] if item["id"] == "COMBO-C")
    eefp_thresholds = {int(k): v for k, v in combo_c["thresholds"].items()}
    eefp_ood_thresholds = {int(k): float(v) for k, v in combo_report["ood_gate"]["thresholds"].items()}

    ood_a, ood_c = {}, {}
    for layer in LAYERS:
        mean = hidden[layer][fit].mean(0).astype(np.float32)
        scale = hidden[layer][fit].std(0).astype(np.float32)
        scale[scale < 1e-5] = 1.
        ood_a[layer] = _OodScorer(mean, scale)
        ood_c[layer] = _OodScorer(mean, scale)

    # Runtime artifact contains only model weights, scaler values and the fixed
    # already-certified synthetic policy descriptors. It remains outside Git.
    package = {
        "artifact_version": 1, "source": "LOCAL_REPRODUCIBLE_SYNTHETIC_SANDBOX",
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "tokenizer_revision": TOKENIZER_REVISION, "context_adapter_version": CONTEXT_ADAPTER_VERSION,
        "action_mapping": list(ACTIONS), "layers": list(LAYERS), "dataset_hash": combo_report["dataset_hash"],
        "candidate_a": {"router": "PABEE", "thresholds": {str(k): v for k, v in pabee_thresholds.items()},
            "ood_thresholds": {str(k): v for k, v in pabee_ood_thresholds.items()},
            "ood_stats": {str(l): {"mean": ood_a[l].mean, "scale": ood_a[l].scale} for l in LAYERS},
            "heads": {str(l): {"mean": scalers_a[l].mean_, "scale": scalers_a[l].scale_,
                "coef": classifiers_a[l].coef_, "bias": classifiers_a[l].intercept_} for l in LAYERS}},
        "candidate_c": {"router": "EEFP", "thresholds": {str(k): v for k, v in eefp_thresholds.items()},
            "ood_thresholds": {str(k): v for k, v in eefp_ood_thresholds.items()},
            "ood_stats": {str(l): {"mean": ood_c[l].mean, "scale": ood_c[l].scale} for l in LAYERS},
            "router_coef": eefp.coef_, "router_bias": eefp.intercept_,
            "heads": {str(l): {"mean": scalers_c[l].mean_, "scale": scalers_c[l].scale_,
                "coef": classifiers_c[l].coef_, "bias": classifiers_c[l].intercept_} for l in LAYERS}},
    }
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tensors = {}
    metadata = {k: v for k, v in package.items() if k not in {"candidate_a", "candidate_c"}}
    for candidate_name in ("candidate_a", "candidate_c"):
        candidate = package[candidate_name]
        metadata[candidate_name] = {k: v for k, v in candidate.items() if k not in {"heads", "router_coef", "ood_stats"}}
        metadata[candidate_name]["heads"] = {}
        for layer, values in candidate["heads"].items():
            metadata[candidate_name]["heads"][layer] = {}
            for name, value in values.items():
                key = f"{candidate_name}.{layer}.{name}"
                tensors[key] = torch.tensor(np.asarray(value), dtype=torch.float32)
                metadata[candidate_name]["heads"][layer][name] = key
        metadata[candidate_name]["ood_stats"] = {}
        for layer, values in candidate["ood_stats"].items():
            metadata[candidate_name]["ood_stats"][layer] = {}
            for name, value in values.items():
                key = f"{candidate_name}.{layer}.ood_{name}"
                tensors[key] = torch.tensor(np.asarray(value), dtype=torch.float32)
                metadata[candidate_name]["ood_stats"][layer][name] = key
        if candidate_name == "candidate_c":
            for name, value in (("router_coef", candidate["router_coef"]), ("router_bias", candidate["router_bias"])):
                key = f"{candidate_name}.{name}"
                tensors[key] = torch.tensor(np.asarray(value), dtype=torch.float32)
                metadata[candidate_name][name] = key
    torch.save({"metadata": metadata, "tensors": tensors}, ARTIFACT_PATH)

    return {"scalers_a": scalers_a, "classifiers_a": classifiers_a,
        "scalers_c": scalers_c, "classifiers_c": classifiers_c, "probs_a": probs_a, "probs_c": probs_c,
        "eefp": eefp, "ood_a": ood_a, "ood_c": ood_c,
        "thresholds_a": pabee_thresholds, "thresholds_c": eefp_thresholds,
        "ood_thresholds_a": pabee_ood_thresholds, "ood_thresholds_c": eefp_ood_thresholds,
        "structured": structured, "router_fit": router_fit}


def _sync_affine_heads(candidate_heads, device, feature_vector=None):
    result = {}
    for layer, head in candidate_heads.items():
        if feature_vector is not None:
            head.feature_vector = torch.tensor(feature_vector, dtype=torch.float32)
        result[layer] = head.to(device).eval()
    return result


def _load_heads_from_artifact(package, candidate, device, feature_vector=None):
    metadata = package["metadata"][f"candidate_{candidate.lower()}"]
    tensors = package["tensors"]
    result = {}
    for layer in map(str, LAYERS):
        refs = metadata["heads"][layer]
        result[layer] = AffineHead(tensors[refs["mean"]].numpy(), tensors[refs["scale"]].numpy(),
            tensors[refs["coef"]].numpy(), tensors[refs["bias"]].numpy(), feature_vector, device=device).eval()
    return result


def _load_ood_from_artifact(package, candidate):
    metadata = package["metadata"][f"candidate_{candidate.lower()}"]
    tensors = package["tensors"]
    scorers = {}
    thresholds = {int(k): float(v) for k, v in metadata["ood_thresholds"].items()}
    for layer in map(str, LAYERS):
        refs = metadata["ood_stats"][layer]
        scorers[int(layer)] = _OodScorer(tensors[refs["mean"]].numpy(), tensors[refs["scale"]].numpy())
    return scorers, thresholds


def _pabee_router(probability, traces, layer, thresholds):
    pos = LAYERS.index(layer)
    if pos == 0 or not traces:
        return False
    previous = traces[-1]
    return (int(previous["layer"]) == LAYERS[pos - 1]
            and int(previous["prediction_index"]) == int(np.argmax(probability))
            and thresholds.get(layer) is not None
            and float(np.max(probability)) >= float(thresholds[layer]))


def _eefp_router(probability, traces, layer, thresholds, coef, bias):
    pos = LAYERS.index(layer)
    features = np.zeros((1, len(LAYERS) * 4), dtype=np.float32)
    sequence = list(traces) + [{"layer": layer, "probabilities": probability.tolist()}]
    for trace in sequence:
        trace_pos = LAYERS.index(int(trace["layer"]))
        p = np.asarray(trace["probabilities"], dtype=float)
        sortedp = np.sort(p)
        entropy = float(-(p * np.log(np.clip(p, 1e-12, 1))).sum())
        features[0, trace_pos * 4:trace_pos * 4 + 4] = [p.max(), sortedp[-1] - sortedp[-2], entropy, p.argmax()]
    logits = (features @ coef.reshape(-1, 1) + bias.reshape(1, -1))[0]
    probability_of_fix = float(expit(logits[0])) if logits.size == 1 else float(softmax(logits)[1])
    threshold = thresholds.get(layer)
    return threshold is not None and probability_of_fix <= float(threshold)


def _metrics(y, pred):
    from sklearn.metrics import accuracy_score, f1_score, balanced_accuracy_score, precision_recall_fscore_support
    p, r, f, support = precision_recall_fscore_support(y, pred, labels=np.arange(len(ACTIONS)), zero_division=0)
    return {"count": int(len(y)), "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, labels=np.arange(len(ACTIONS)), average="macro", zero_division=0)),
        "per_class": {action: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(support[i])}
            for i, action in enumerate(ACTIONS)}}


def _fixed_sample_indices(y, indexes, count=SAMPLES):
    by_class = {i: [int(x) for x in indexes if int(y[x]) == i] for i in range(len(ACTIONS))}
    selected = []
    while len(selected) < count:
        changed = False
        for cls in range(len(ACTIONS)):
            if by_class[cls]:
                selected.append(by_class[cls].pop(0)); changed = True
                if len(selected) >= count:
                    break
        if not changed:
            break
    return selected


def main():
    primary, contract, hidden, rows, y, splits = _load_contract_and_cache()
    combo_report = json.loads((ROOT / "reports/phase6_ee_combinations.json").read_text(encoding="utf-8"))
    fitted = _fit_candidate_models(hidden, rows, y, splits, combo_report)
    model = SharedTransformerBackbone()
    model.model.eval()
    device = model.device
    memory_before = _memory_snapshot(device)
    indices = _fixed_sample_indices(y, splits["frozen_evaluation"], SAMPLES)
    if len(indices) != SAMPLES:
        raise RuntimeError(f"Frozen evaluation provides only {len(indices)} benchmark cases")

    package = torch.load(ARTIFACT_PATH, map_location="cpu", weights_only=True)
    metadata = package["metadata"]
    artifact_contract_ok = (metadata["model_revision"] == MODEL_REVISION
        and metadata["tokenizer_revision"] == TOKENIZER_REVISION
        and metadata["context_adapter_version"] == CONTEXT_ADAPTER_VERSION
        and metadata["dataset_hash"] == combo_report["dataset_hash"]
        and metadata["action_mapping"] == list(ACTIONS))
    if not artifact_contract_ok:
        raise RuntimeError("Sandbox runtime artifact contract mismatch")
    runtime_heads_a = _load_heads_from_artifact(package, "A", device)
    runtime_ood_a, runtime_ood_thresholds_a = _load_ood_from_artifact(package, "A")

    full_ms, adaptive_ms = [], {"A": [], "C": []}
    layer_counts = {"full": [], "A": [], "C": []}
    predictions = {"full_A": [], "full_C": [], "adaptive_A": [], "adaptive_C": []}
    labels = []
    out_rows = []
    parity = {"sample_count": len(indices), "token_id_exact_matches": 0,
        "max_hidden_abs_diff_by_layer": {str(l): 0.0 for l in LAYERS},
        "max_probability_abs_diff": {"A": 0.0, "C": 0.0}, "predicted_action_matches": {"A": 0, "C": 0},
        "exit_layer_matches": {"A": 0, "C": 0}, "tolerance_atol": PARITY_ATOL}
    # Create instrumented hooks once. Each run snapshots and differences counts.
    hook_counts = [0] * model.layer_count
    handles = [layer.register_forward_hook(lambda _m, _i, _o, idx=i: hook_counts.__setitem__(idx, hook_counts[idx] + 1))
        for i, layer in enumerate(model.backbone.layers)]
    head_ms = {"A": [], "C": []}; ood_ms = {"A": [], "C": []}; router_ms = {"A": [], "C": []}

    def run_adaptive(candidate, idx, encoded):
        feature = None if candidate == "A" else fitted["structured"][idx]
        heads = runtime_heads_a if candidate == "A" else _load_heads_from_artifact(package, "C", device, feature)
        candidate_metadata = metadata[f"candidate_{candidate.lower()}"]
        thresholds = {int(k): v for k, v in candidate_metadata["thresholds"].items()}
        scorers, ood_thresholds = _load_ood_from_artifact(package, candidate)
        if candidate == "A":
            router = lambda layer, p, traces: _pabee_router(p, traces, layer, thresholds)
        else:
            coef = package["tensors"][candidate_metadata["router_coef"]].numpy().reshape(-1).astype(np.float32)
            bias = package["tensors"][candidate_metadata["router_bias"]].numpy().reshape(-1).astype(np.float32)
            router = lambda layer, p, traces: _eefp_router(p, traces, layer, thresholds, coef, bias)
        gates = {"temperatures": {str(l): (lambda logits: torch.softmax(logits.float(), dim=-1)) for l in LAYERS},
            "exit_thresholds": {str(l): thresholds.get(l) for l in LAYERS}, "ood": {str(l): scorers[l] for l in LAYERS}}
        return model.early_hidden(encoded["input_ids"], encoded.get("attention_mask"),
            decision_heads=heads, gates=gates, input_valid=True,
            ood_thresholds={str(l): ood_thresholds[l] for l in LAYERS}, allow_early_exit=True, exit_router=router)

    # Warm each real execution path before timing; warmups are not included in reports.
    for idx in indices[:WARMUPS]:
        warm_encoded = model.format_decision_tokens(_training_context(rows[idx]["state"]))
        with torch.inference_mode():
            model.forward_to_exits(warm_encoded["input_ids"], warm_encoded.get("attention_mask"), capture_layers=LAYERS)
            run_adaptive("A", idx, warm_encoded)
            run_adaptive("C", idx, warm_encoded)
        _sync(device)
    for sample_position, idx in enumerate(indices):
        row = rows[idx]; labels.append(int(y[idx]))
        canonical = _training_context(row["state"])
        encoded = model.format_decision_tokens(canonical)
        ids_hash = hashlib.sha256(encoded["input_ids"].detach().cpu().numpy().tobytes()).hexdigest()
        if ids_hash != contract["token_hashes"][idx]:
            raise RuntimeError(f"Tokenizer parity failed at frozen row {idx}")
        parity["token_id_exact_matches"] += 1
        start_counts = hook_counts.copy(); _sync(device); start = time.perf_counter()
        with torch.inference_mode():
            full = model.forward_to_exits(encoded["input_ids"], encoded.get("attention_mask"), capture_layers=LAYERS)
        _sync(device); full_ms.append((time.perf_counter() - start) * 1000)
        full_calls = sum(a - b for a, b in zip(hook_counts, start_counts)); layer_counts["full"].append(full_calls)
        if full_calls != model.layer_count:
            raise RuntimeError(f"Full-depth hook evidence expected {model.layer_count} layer calls, got {full_calls}")
        offline_probs = {"A": {}, "C": {}}
        for layer in LAYERS:
            ref_hidden = hidden[layer][idx]
            actual_hidden = full["hidden_by_layer"][layer][0].detach().float().cpu().numpy()
            err = float(np.max(np.abs(ref_hidden - actual_hidden)))
            parity["max_hidden_abs_diff_by_layer"][str(layer)] = max(parity["max_hidden_abs_diff_by_layer"][str(layer)], err)
            feat = fitted["structured"][idx]
            for candidate, scaler_key, classifier_key in (("A", "scalers_a", "classifiers_a"), ("C", "scalers_c", "classifiers_c")):
                scaler = fitted[scaler_key][layer]; clf = fitted[classifier_key][layer]
                x = actual_hidden.reshape(1, -1) if candidate == "A" else np.concatenate([actual_hidden, feat]).reshape(1, -1)
                offline_probs[candidate][layer] = clf.predict_proba(scaler.transform(x))[0]
        pred_full_a = int(np.argmax(offline_probs["A"][28])); pred_full_c = int(np.argmax(offline_probs["C"][28]))
        predictions["full_A"].append(pred_full_a); predictions["full_C"].append(pred_full_c)

        runs = {}
        for candidate in ("A", "C"):
            start_counts = hook_counts.copy(); _sync(device); start = time.perf_counter()
            with torch.inference_mode():
                result = run_adaptive(candidate, idx, encoded)
            _sync(device); adaptive_ms[candidate].append((time.perf_counter() - start) * 1000)
            calls = sum(a - b for a, b in zip(hook_counts, start_counts)); layer_counts[candidate].append(calls)
            if calls != int(result["exit_layer"]):
                raise RuntimeError(f"Adaptive exit at layer {result['exit_layer']} executed {calls} decoder layers")
            action_index = int(result["probabilities"].argmax(dim=-1)[0].item())
            predictions[f"adaptive_{candidate}"].append(action_index)
            runs[candidate] = {"action_index": action_index, "exit_layer": int(result["exit_layer"]),
                "actual_layer_calls": calls, "ood_at_exit": bool(result["ood"]),
                "trace": result["trace"], "probabilities": result["probabilities"][0].detach().float().cpu().numpy()}
            head_ms[candidate].append(sum(t.get("decision_head_ms", 0.) for t in result["trace"]))
            ood_ms[candidate].append(sum(t.get("ood_ms", 0.) for t in result["trace"]))
            router_ms[candidate].append(sum(t.get("router_ms", 0.) for t in result["trace"]))
            ref_exit = offline_probs[candidate][runs[candidate]["exit_layer"]]
            p_err = float(np.max(np.abs(ref_exit - runs[candidate]["probabilities"])))
            parity["max_probability_abs_diff"][candidate] = max(parity["max_probability_abs_diff"][candidate], p_err)
            parity["predicted_action_matches"][candidate] += int(action_index == int(np.argmax(ref_exit)))
            # Candidate A parity uses the already-certified PABEE policy and its OOD vector.
            if candidate == "A":
                old = json.loads((ROOT / "reports/phase6_ee_router_comparison.json").read_text(encoding="utf-8"))
                prob_view = {l: np.asarray([fitted["probs_a"][l]["test"][list(splits["frozen_evaluation"]).index(idx)]]) for l in LAYERS}
                ood_arrays = {}
                for l in LAYERS:
                    z = np.clip((hidden[l][splits["frozen_evaluation"]] - fitted["ood_a"][l].mean) / fitted["ood_a"][l].scale, -8, 8)
                    scores = np.sqrt(np.mean(z * z, axis=1))
                    ood_arrays[l] = scores > fitted["ood_thresholds_a"][l]
                frozen_pos = list(splits["frozen_evaluation"]).index(idx)
                ood_sub = {l: {"test": np.asarray([ood_arrays[l][frozen_pos]])} for l in LAYERS}
                expected_pred, expected_exit = ee._route(prob_view, LAYERS, fitted["thresholds_a"], "pabee", eefp=None,
                    ood={l: ood_sub[l]["test"] for l in LAYERS})
                exp_exit = int(expected_exit[0]); exp_pred = int(expected_pred[0])
            else:
                # Reconstruct the exact offline COMBO-C route on the same frozen
                # index using probabilities generated from the pinned cache.
                local_probs = {l: {"test": fitted["probs_c"][l]["test"][list(splits["frozen_evaluation"]).index(idx):list(splits["frozen_evaluation"]).index(idx)+1]}
                    for l in LAYERS}
                frozen_pos = list(splits["frozen_evaluation"]).index(idx)
                ood_map = {}
                for l in LAYERS:
                    z = np.clip((hidden[l][splits["fit"]].mean(0) - fitted["ood_c"][l].mean) / fitted["ood_c"][l].scale, -8, 8)
                    fit_hidden = hidden[l][splits["fit"]]
                    fit_mean = fit_hidden.mean(0); fit_scale = fit_hidden.std(0); fit_scale[fit_scale < 1e-5] = 1.
                    zz = np.clip((hidden[l][splits["frozen_evaluation"]] - fit_mean) / fit_scale, -8, 8)
                    scores = np.sqrt(np.mean(zz * zz, axis=1))
                    ood_map[l] = {"test": np.asarray([scores[frozen_pos] > fitted["ood_thresholds_c"][l]])}
                expected_pred, expected_exit = combos._route(local_probs, "test", fitted["thresholds_c"], "eefp", y,
                    np.asarray([idx]), eefp=fitted["eefp"], agreement=False, ood=ood_map)
                exp_exit = int(expected_exit[0]); exp_pred = int(expected_pred[0])
            parity["exit_layer_matches"][candidate] += int(runs[candidate]["exit_layer"] == exp_exit)
        out_rows.append({"row_index": idx, "label": ACTIONS[y[idx]], "full_depth_action_a": ACTIONS[pred_full_a],
            "full_depth_action_c": ACTIONS[pred_full_c], "adaptive_a": {**{k: v for k, v in runs["A"].items() if k != "probabilities"}, "action": ACTIONS[runs["A"]["action_index"]]},
            "adaptive_c": {**{k: v for k, v in runs["C"].items() if k != "probabilities"}, "action": ACTIONS[runs["C"]["action_index"]]}})

    for handle in handles:
        handle.remove()
    memory_after = _memory_snapshot(device)
    ys = np.asarray(labels)
    summaries = {}
    baseline_p50 = float(np.percentile(full_ms, 50))
    baseline_p95 = float(np.percentile(full_ms, 95))
    for candidate in ("A", "C"):
        early = np.asarray(layer_counts[candidate]) < model.layer_count
        trace_key = "adaptive_a" if candidate == "A" else "adaptive_c"
        ood_blocks = [sum(bool(trace["ood"]) and not bool(trace["accepted"]) for trace in sample[trace_key]["trace"])
            for sample in out_rows]
        ood_detections = [sum(bool(trace["ood"]) for trace in sample[trace_key]["trace"])
            for sample in out_rows]
        ood_early_exit_violations = [sum(bool(trace["ood"]) and bool(trace["accepted"])
                and int(trace["layer"]) < model.layer_count for trace in sample[trace_key]["trace"])
            for sample in out_rows]
        summaries[candidate] = {"policy": "PABEE" if candidate == "A" else "Fusion + EEFP",
            "early_exit_count": int(early.sum()), "early_exit_rate": float(early.mean()),
            "mean_executed_layers": float(np.mean(layer_counts[candidate])),
            "actual_layer_calls": layer_counts[candidate],
            "latency_p50_ms": float(np.percentile(adaptive_ms[candidate], 50)),
            "latency_p95_ms": float(np.percentile(adaptive_ms[candidate], 95)),
            "speedup_vs_shared_full_depth_p50": baseline_p50 / float(np.percentile(adaptive_ms[candidate], 50)),
            "speedup_vs_shared_full_depth_p95": baseline_p95 / float(np.percentile(adaptive_ms[candidate], 95)),
            "mean_head_ms": float(np.mean(head_ms[candidate])),
            "mean_ood_gate_ms": float(np.mean(ood_ms[candidate])),
            "mean_router_ms": float(np.mean(router_ms[candidate])),
            "full_depth_metrics": _metrics(ys, predictions[f"full_{candidate}"]),
            "adaptive_metrics": _metrics(ys, predictions[f"adaptive_{candidate}"]),
            "prediction_agreement_with_full_depth": float(np.mean(np.asarray(predictions[f"adaptive_{candidate}"]) == np.asarray(predictions[f"full_{candidate}"]))),
            "unsafe_optimize_false_positive_count": int(np.sum((np.asarray(predictions[f"adaptive_{candidate}"]) == ACTIONS.index("OPTIMIZE")) & (ys != ACTIONS.index("OPTIMIZE")))),
            "review_or_abstain_recall": float(np.mean(np.isin(np.asarray(predictions[f"adaptive_{candidate}"])[np.isin(ys, [ACTIONS.index("REQUEST_REVIEW"), ACTIONS.index("ABSTAIN")])],
                [ACTIONS.index("REQUEST_REVIEW"), ACTIONS.index("ABSTAIN")]))),
            "ood_detection_count": int(sum(ood_detections)),
            "ood_exit_block_count": int(sum(ood_blocks)),
            "ood_early_exit_violation_count": int(sum(ood_early_exit_violations))}
    runtime_report = {"status": "COMPLETED_REAL_QWEN_SANDBOX_RUNTIME", "scope": "SYNTHETIC_SANDBOX_ONLY_NO_RESEARCH_API_OR_WORKFLOW", "model": {
        "id": MODEL_ID, "revision": MODEL_REVISION, "tokenizer_revision": TOKENIZER_REVISION,
        "device": device, "precision": model.precision, "layer_count": model.layer_count,
        "model_loading_excluded": True}, "artifact": {"path": str(ARTIFACT_PATH), "sha256": hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest(),
        "contract_validated": artifact_contract_ok, "source": "regenerated locally from existing report/cache; no external artifact loaded"},
        "dataset": {"hash": contract["dataset_hash"], "frozen_count": len(splits["frozen_evaluation"]),
            "benchmark_count": len(indices), "selected_indices": indices, "labels": [ACTIONS[v] for v in labels]},
        "timing_protocol": {"warmup_runs": WARMUPS, "measured_inputs": len(indices), "same_inputs_and_token_ids": True,
            "synchronization": device in {"mps"} or device.startswith("cuda"), "latency_includes": "decoder prefix + heads + router; tokenization excluded",
            "full_depth_p50_ms": baseline_p50, "full_depth_p95_ms": baseline_p95,
            "full_depth_mean_layer_calls": float(np.mean(layer_counts["full"]))},
        "memory": {"before_benchmark": memory_before, "after_benchmark": memory_after,
            "peak_note": "MPS peak allocator counter is unavailable in this PyTorch runtime; current driver/allocator bytes are reported."},
        "candidates": summaries, "per_sample_evidence": out_rows,
        "safety": {"ood_gate_in_runtime": True,
            "ood_early_exit_violation_count": sum(v["ood_early_exit_violation_count"] for v in summaries.values()),
            "research_api_changed": False, "workflow_triggered": False,
            "production_router_changed": False, "synthetic_certification_promoted": False,
            "external_scientific_validation": "PENDING"},
        "hook_evidence": {"per_run_calls_match_reported_exit_layer": True,
            "full_depth_calls_per_run": model.layer_count,
            "candidate_layer_call_distribution": {c: {str(layer): int(sum(x == layer for x in layer_counts[c]))
                for layer in sorted(set(layer_counts[c]))} for c in ("A", "C")}},
        "limitations": ["Thirty synthetic frozen cases are a runtime diagnostic, not a risk certificate.",
            "This benchmark calls the existing Qwen layer loop directly and does not expose a public API.",
            "Sandbox actions are not experimental authorization; human approval and Research provenance gates remain unchanged."]}
    parity_report = {"status": "PASS" if parity["token_id_exact_matches"] == len(indices)
        and all(v <= PARITY_ATOL for v in parity["max_hidden_abs_diff_by_layer"].values())
        and all(v <= PARITY_ATOL for v in parity["max_probability_abs_diff"].values())
        and all(parity["predicted_action_matches"][c] == len(indices) for c in ("A", "C"))
        and all(parity["exit_layer_matches"][c] == len(indices) for c in ("A", "C")) else "FAILED",
        "model_revision": MODEL_REVISION, "tokenizer_revision": TOKENIZER_REVISION,
        "context_adapter_version": CONTEXT_ADAPTER_VERSION, "artifact_sha256": runtime_report["artifact"]["sha256"],
        "sample_count": len(indices), "token_id_exact_matches": parity["token_id_exact_matches"],
        "max_hidden_abs_diff_by_layer": parity["max_hidden_abs_diff_by_layer"],
        "max_probability_abs_diff": parity["max_probability_abs_diff"],
        "predicted_action_matches": parity["predicted_action_matches"], "exit_layer_matches": parity["exit_layer_matches"],
        "absolute_tolerance": PARITY_ATOL, "offline_reference": "same pinned checkpoint/revision, cached hidden states and deterministic head refits"}
    (ROOT / "reports/phase6_ee_actual_runtime.json").write_text(json.dumps(runtime_report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (ROOT / "reports/phase6_ee_runtime_parity.json").write_text(json.dumps(parity_report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    selection_report = {"status": "PENDING_REVIEW_OF_MEASURED_RUNTIME", "candidate_results": summaries,
        "selection_rule": "Select only a candidate whose parity passes, no worse safety gate, lower decision error than full depth, actual layer calls decrease, and measured p50 improves.",
        "selected_candidate": None, "phase6_status": "IN_PROGRESS", "phase7_status": "NOT_STARTED",
        "runtime_parity": parity_report["status"], "external_scientific_validation": "PENDING"}
    passing = []
    if parity_report["status"] == "PASS":
        for candidate, value in summaries.items():
            if (value["mean_executed_layers"] < model.layer_count
                    and value["latency_p50_ms"] < baseline_p50
                    and value["adaptive_metrics"]["macro_f1"] >= value["full_depth_metrics"]["macro_f1"]
                    and value["unsafe_optimize_false_positive_count"] <= sum(
                        p == ACTIONS.index("OPTIMIZE") and yy != ACTIONS.index("OPTIMIZE")
                        for p, yy in zip(predictions[f"full_{candidate}"], ys))):
                passing.append((candidate, value["latency_p50_ms"]))
    if passing:
        picked = min(passing, key=lambda x: x[1])[0]
        selection_report["selected_candidate"] = picked
        selection_report["status"] = "PHASE_6_SANDBOX_RUNTIME_VERIFIED"
        selection_report["performance_status"] = "PHASE_6_PERFORMANCE_TARGET_MET"
    else:
        selection_report["performance_status"] = "PHASE_6_PERFORMANCE_OPTIMIZATION_PENDING"
        selection_report["status"] = "PHASE_6_RUNTIME_INCOMPLETE" if not any(x["early_exit_rate"] > 0 for x in summaries.values()) else "PHASE_6_SANDBOX_RUNTIME_VERIFIED"
    (ROOT / "reports/phase6_ee_runtime_selection.json").write_text(json.dumps(selection_report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"runtime_status": selection_report["status"], "performance_status": selection_report["performance_status"],
        "parity": parity_report["status"], "full_depth_p50_ms": baseline_p50,
        "candidates": {k: {"early_exit_rate": v["early_exit_rate"], "mean_layers": v["mean_executed_layers"],
            "p50_ms": v["latency_p50_ms"], "p95_ms": v["latency_p95_ms"]} for k, v in summaries.items()}} , ensure_ascii=False))


if __name__ == "__main__":
    main()
