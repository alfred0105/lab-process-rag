"""Compare the five requested Phase 6 head/router combinations on the frozen
synthetic research contract. Results are diagnostic only and never authorize
production early exit.

This reuses the hash-verified hidden-state cache from phase6_ee_research.py.
One candidate is selected on policy_selection and only that single frozen
policy is evaluated on risk_certification. The frozen split is descriptive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import phase6_ee_research as ee
sys.path.insert(0, str(ROOT))
from app.services.phase5_stage3 import generate_scenarios
from app.services.phase6_hybrid import MODEL_REVISION
from app.services.decision_head import ACTIONS

LAYERS = ee.LAYERS
TARGET_RISK = ee.TARGET_RISK
MIN_EXITS = ee.MIN_EXITS


def _prediction_metrics(y, pred):
    return {"count": int(len(y)), "accuracy": float(accuracy_score(y, pred)),
            "macro_f1": float(f1_score(y, pred, labels=np.arange(len(ACTIONS)), average="macro", zero_division=0))}


def _fit_probability_head(name, x, y, fit, query):
    scaler = StandardScaler().fit(x[fit])
    kwargs = {"max_iter": 900, "C": .08, "random_state": ee.SEED}
    if name in {"class_balanced_linear", "class_balanced_fusion"}:
        kwargs["class_weight"] = "balanced"
    model = LogisticRegression(**kwargs).fit(scaler.transform(x[fit]), y[fit])
    return {key: model.predict_proba(scaler.transform(x[idx])) for key, idx in query.items()}


def _fit_distilled(x, y, fit, router_fit, query):
    # Same teacher protocol as the main audit: the full-depth teacher is fit on
    # fit only; soft targets are generated only for the disjoint router-fit set.
    import torch
    torch.manual_seed(ee.SEED + 991)
    teacher_scaler = StandardScaler().fit(x[fit])
    teacher = LogisticRegression(max_iter=900, C=.08, random_state=ee.SEED).fit(
        teacher_scaler.transform(x[fit]), y[fit])
    teacher_x = teacher_scaler.transform(x[router_fit]).astype(np.float32)
    teacher_prob = teacher.predict_proba(teacher_x).astype(np.float32)
    scaler = StandardScaler().fit(x[fit])
    student = torch.nn.Linear(x.shape[1], len(ACTIONS))
    opt = torch.optim.AdamW(student.parameters(), lr=.004, weight_decay=.01)
    hard_x = torch.tensor(scaler.transform(x[fit]).astype(np.float32))
    hard_y = torch.tensor(y[fit], dtype=torch.long)
    soft_x = torch.tensor(scaler.transform(x[router_fit]).astype(np.float32))
    soft_y = torch.tensor(teacher_prob)
    rng = np.random.default_rng(ee.SEED + 991)
    for _ in range(20):
        order = rng.permutation(len(hard_y))
        for start in range(0, len(order), 128):
            ids = torch.tensor(order[start:start + 128], dtype=torch.long)
            sid = torch.tensor(rng.integers(0, len(soft_y), size=len(ids)), dtype=torch.long)
            opt.zero_grad(set_to_none=True)
            hard_loss = torch.nn.functional.cross_entropy(student(hard_x[ids]), hard_y[ids])
            logp = torch.nn.functional.log_softmax(student(soft_x[sid]) / .8, dim=1)
            kl = torch.nn.functional.kl_div(logp, soft_y[sid], reduction="batchmean") * .8**2
            loss = .7 * hard_loss + .3 * kl
            loss.backward(); opt.step()
    student.eval()
    output = {}
    with torch.inference_mode():
        for split, idx in query.items():
            logits = student(torch.tensor(scaler.transform(x[idx]).astype(np.float32)))
            output[split] = torch.softmax(logits, dim=1).numpy()
    return output


def _fit_eefp(layer_probs, y, router_fit):
    features, targets = [], []
    for pos, layer in enumerate(LAYERS[:-1]):
        x = ee._features_for_router({l: p["router_fit"] for l, p in layer_probs.items()}, LAYERS, pos)
        early_correct = layer_probs[layer]["router_fit"].argmax(1) == y[router_fit]
        final_correct = layer_probs[28]["router_fit"].argmax(1) == y[router_fit]
        features.append(x); targets.append((~early_correct & final_correct).astype(int))
    xx, yy = np.vstack(features), np.concatenate(targets)
    return LogisticRegression(max_iter=400, class_weight="balanced", random_state=ee.SEED).fit(xx, yy) if len(np.unique(yy)) > 1 else None


def _score(prob, kind):
    if kind == "eefp":
        return None
    if kind == "entropy":
        return -(prob * np.log(np.clip(prob, 1e-12, 1))).sum(1), False
    if kind == "margin":
        s = np.sort(prob, axis=1)
        return s[:, -1] - s[:, -2], True
    return prob.max(1), True


def _ood_masks(hidden, fit, query):
    masks = {}
    thresholds = {}
    for layer in LAYERS:
        mean = hidden[layer][fit].mean(0)
        scale = hidden[layer][fit].std(0)
        scale[scale < 1e-5] = 1.
        def score(indices):
            z = np.clip((hidden[layer][indices] - mean) / scale, -8, 8)
            return np.sqrt(np.mean(z * z, axis=1))
        cutoff = float(np.quantile(score(query["calibration"]), .95, method="higher"))
        thresholds[layer] = cutoff
        masks[layer] = {name: score(indices) > cutoff for name, indices in query.items()}
    return masks, thresholds


def _route(layer_probs, split, thresholds, router, y, idx, eefp=None, agreement=False, ood=None):
    n = len(idx); pred = np.empty(n, dtype=int); exits = np.full(n, 28, dtype=int)
    split_probs = {layer: layer_probs[layer][split] for layer in LAYERS}
    for i in range(n):
        for pos, layer in enumerate(LAYERS[:-1]):
            if ood is not None and bool(ood[layer][split][i]):
                continue
            threshold = thresholds.get(layer)
            if threshold is None:
                continue
            p = split_probs[layer][i:i + 1]
            if router == "eefp":
                feats = ee._features_for_router(split_probs, LAYERS, pos)[i:i + 1]
                accept = eefp is not None and float(eefp.predict_proba(feats)[0, 1]) <= threshold
            else:
                values, high_good = _score(p, router)
                accept = bool(values[0] >= threshold if high_good else values[0] <= threshold)
            if agreement:
                seq = [int(split_probs[l][i].argmax()) for l in LAYERS[max(0, pos - 1):pos + 1]]
                accept = accept and len(seq) == 2 and seq[0] == seq[1]
            if accept:
                pred[i] = int(p.argmax(1)[0]); exits[i] = layer; break
        else:
            pred[i] = int(split_probs[28][i].argmax())
    return pred, exits


def _calibrate(layer_probs, y, cal, router, eefp=None, agreement=False, ood=None):
    thresholds = {}
    cal_probs = {layer: layer_probs[layer]["calibration"] for layer in LAYERS}
    for pos, layer in enumerate(LAYERS[:-1]):
        p = cal_probs[layer]
        if router == "eefp":
            feats = ee._features_for_router(cal_probs, LAYERS, pos)
            values = eefp.predict_proba(feats)[:, 1] if eefp is not None else np.ones(len(cal))
            high_good = False
        else:
            values, high_good = _score(p, router)
        agree = np.ones(len(cal), dtype=bool)
        if agreement:
            agree = np.asarray([cal_probs[LAYERS[pos - 1]][i].argmax() == p[i].argmax() for i in range(len(cal))]) if pos else np.zeros(len(cal), dtype=bool)
        valid = []
        for t in np.unique(values):
            mask = values >= t if high_good else values <= t
            mask &= agree
            if ood is not None:
                mask &= ~ood[layer]["calibration"]
            count = int(mask.sum()); errors = int(np.sum(p.argmax(1)[mask] != y[cal][mask]))
            if count >= MIN_EXITS and ee._wilson_upper(errors, count) <= TARGET_RISK:
                valid.append((count, float(t)))
        thresholds[layer] = max(valid)[1] if valid else None
    return thresholds


def main():
    report_path = ROOT / "reports" / "phase6_ee_final_benchmark.json"
    main_report = json.loads(report_path.read_text(encoding="utf-8"))
    cache_key = main_report["cache"]["key"]
    cache_path = Path.home() / ".cache/lab-process-rag" / f"phase6-ee-research-{cache_key}.npz"
    if not cache_path.exists():
        raise FileNotFoundError("Expected hash-matched hidden cache; run phase6_ee_research.py first")
    with np.load(cache_path, allow_pickle=False) as archive:
        contract = json.loads(str(archive["contract"].item()))
        hidden = {layer: archive[f"layer_{layer}"].copy() for layer in LAYERS}
    if contract["model_revision"] != MODEL_REVISION or contract["dataset_hash"] != main_report.get("dataset_hash"):
        raise ValueError("Hidden cache model revision or dataset hash does not match the primary research report")
    rows = generate_scenarios(seed=73191, samples=3840)
    y = np.asarray([ACTIONS.index(row["action"]) for row in rows])
    splits = ee._splits(rows)
    fit, router_fit, cal, selection, certify, test = (splits[k] for k in
        ("fit", "router_fit", "calibration", "policy_selection", "risk_certification", "frozen_evaluation"))
    structured = np.nan_to_num(np.vstack([r["features_v2"] for r in rows]).astype(np.float32), nan=0., posinf=0., neginf=0.)
    query = {"router_fit": router_fit, "calibration": cal, "selection": selection, "certification": certify, "test": test}
    ood, ood_thresholds = _ood_masks(hidden, fit, query)
    variants = {
        "linear_hidden": lambda l: _fit_probability_head("linear", hidden[l], y, fit, query),
        "class_balanced_hidden": lambda l: _fit_probability_head("class_balanced_linear", hidden[l], y, fit, query),
        "fusion": lambda l: _fit_probability_head("fusion", np.concatenate([hidden[l], structured], axis=1), y, fit, query),
        "class_balanced_fusion": lambda l: _fit_probability_head("class_balanced_fusion", np.concatenate([hidden[l], structured], axis=1), y, fit, query),
    }
    outputs = {name: {l: fit_fn(l) for l in LAYERS} for name, fit_fn in variants.items()}
    # Distilled-head combination uses the same hard/soft, disjoint teacher protocol.
    outputs["distilled_hidden"] = {l: _fit_distilled(hidden[l], y, fit, router_fit, query) for l in LAYERS[:-1]}
    outputs["distilled_hidden"][28] = outputs["linear_hidden"][28]
    combos = [
        ("BASELINE", "linear_hidden", "max_softmax", False),
        ("COMBO-A", "linear_hidden", "pabee", False),
        ("COMBO-B", "class_balanced_hidden", "max_softmax", False),
        ("COMBO-C", "fusion", "eefp", False),
        ("COMBO-D", "class_balanced_fusion", "eefp", True),
        ("COMBO-E", "distilled_hidden", "max_softmax", False),
    ]
    evaluated = []
    for combo_id, head, router, agreement in combos:
        layer_probs = outputs[head]
        eefp = _fit_eefp(layer_probs, y, router_fit) if router == "eefp" else None
        if router == "pabee":
            thresholds = {l: .0 for l in LAYERS[:-1]}
            # PABEE still requires the same confidence/risk calibration.
            conf_thresholds = _calibrate(layer_probs, y, cal, "max_softmax", ood=ood)
            thresholds.update(conf_thresholds)
        else:
            thresholds = _calibrate(layer_probs, y, cal, router, eefp=eefp, agreement=agreement, ood=ood)
        pred, exits = _route(layer_probs, "selection", thresholds, "max_softmax" if router == "pabee" else router,
                             y, selection, eefp=eefp, agreement=(router == "pabee" or agreement), ood=ood)
        early = exits < 28; n = int(early.sum()); errors = int(np.sum((pred != y[selection]) & early))
        evaluated.append({"id": combo_id, "head": head, "router": router, "layer_agreement": bool(agreement or router == "pabee"),
            "thresholds": {str(k): v for k, v in thresholds.items()}, "policy_selection": {
                "count": len(selection), "early_exit_count": n, "errors": errors, "observed_risk": errors / max(n, 1),
                "wilson_upper_95": ee._wilson_upper(errors, n), "passed": n >= MIN_EXITS and ee._wilson_upper(errors, n) <= TARGET_RISK},
            "full_depth_frozen_metrics": _prediction_metrics(y[test], layer_probs[28]["test"].argmax(1))})
        evaluated[-1]["_thresholds"] = thresholds
        evaluated[-1]["_eefp"] = eefp
        evaluated[-1]["_probs"] = layer_probs
    eligible = [item for item in evaluated if item["policy_selection"]["passed"]]
    chosen = max(eligible, key=lambda x: (x["policy_selection"]["early_exit_count"], -x["policy_selection"]["errors"])) if eligible else None
    certification = None
    if chosen:
        pred, exits = _route(chosen["_probs"], "certification", chosen["_thresholds"],
            "max_softmax" if chosen["router"] == "pabee" else chosen["router"], y, certify,
            eefp=chosen["_eefp"], agreement=chosen["layer_agreement"], ood=ood)
        mask = exits < 28; n = int(mask.sum()); errors = int(np.sum((pred != y[certify]) & mask))
        certification = {"candidate": chosen["id"], "count": len(certify), "early_exit_count": n, "errors": errors,
            "observed_risk": errors / max(n, 1), "wilson_upper_95": ee._wilson_upper(errors, n),
            "exact_binomial_upper_95": ee._cp_upper(errors, n), "target_risk": TARGET_RISK,
            "minimum_early_exits": MIN_EXITS, "passed": n >= MIN_EXITS and ee._wilson_upper(errors, n) <= TARGET_RISK and ee._cp_upper(errors, n) <= TARGET_RISK}
        pred, exits = _route(chosen["_probs"], "test", chosen["_thresholds"],
            "max_softmax" if chosen["router"] == "pabee" else chosen["router"], y, test,
            eefp=chosen["_eefp"], agreement=chosen["layer_agreement"], ood=ood)
        chosen_test = {"count": len(test), "early_exit_count": int(np.sum(exits < 28)),
            "mean_layers_offline_estimate": float(exits.mean()), "routed_metrics": _prediction_metrics(y[test], pred),
            "used_for_selection_or_certification": False}
    else:
        chosen_test = None
    for item in evaluated:
        item.pop("_thresholds"); item.pop("_eefp"); item.pop("_probs")
    report = {"status": "SYNTHETIC_COMBINATION_DIAGNOSTIC_ONLY", "model_revision": MODEL_REVISION,
        "dataset_hash": contract["dataset_hash"], "split_counts": {k: len(v) for k, v in splits.items()},
        "split_independence_checked": True, "risk_target": TARGET_RISK, "minimum_exits": MIN_EXITS,
        "candidate_combinations": evaluated, "selection_protocol": "Thresholds fit on calibration; all six candidates compared on policy_selection; one policy certified once on independent risk_certification; frozen test descriptive only.",
        "ood_gate": {"enabled": True, "calibration_quantile": .95, "thresholds": {str(k): float(v) for k, v in ood_thresholds.items()}},
        "selected_on_policy_selection": None if chosen is None else chosen["id"], "independent_risk_certification": certification,
        "frozen_evaluation_of_selected_policy": chosen_test,
        "status_boundary": "Synthetic labels only. This report cannot authorize research-mode Early Exit, real lab decisions, or model promotion.",
        "limitations": ["No empirical laboratory labels", "Synthetic rules with override", "No real adaptive decoder execution in this combination script", "Structured-feature causal shortcut risk remains synthetic-contract specific"]}
    out = ROOT / "reports" / "phase6_ee_combinations.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False,
        default=lambda value: value.item() if isinstance(value, np.generic) else str(value)) + "\n", encoding="utf-8")
    selection_path = ROOT / "reports" / "phase6_ee_model_selection.json"
    selection_report = json.loads(selection_path.read_text(encoding="utf-8"))
    selection_report["combination_comparison"] = {
        "report": out.name, "status": report["status"],
        "selected_on_policy_selection": report["selected_on_policy_selection"],
        "independent_synthetic_risk_certification": certification,
        "production_promotion": "NOT_ELIGIBLE_SYNTHETIC_LABELS_ONLY",
    }
    selection_report["selected_candidate"] = None if chosen is None else {
        "combo": chosen["id"], "head": chosen["head"], "router": chosen["router"],
        "basis": "policy-selection only; separate synthetic certification; not production eligible"}
    selection_report["phase6_status"] = "IN_PROGRESS"
    selection_report["phase7_status"] = "NOT_STARTED"
    selection_report["promotion_status"] = "SHADOW_ONLY"
    selection_path.write_text(json.dumps(selection_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    main_report["integrated_combinations"] = {"report": out.name, "selected_on_policy_selection": report["selected_on_policy_selection"],
        "synthetic_certificate": certification, "production_early_exit_enabled": False}
    report_path.write_text(json.dumps(main_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "selected": report["selected_on_policy_selection"], "certification": certification, "report": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
