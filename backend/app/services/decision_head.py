"""Small trainable action classifier for Phase 5; never executes workflow actions."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.services.tool_registry import RuleBasedDecisionPolicy

FEATURE_SCHEMA_VERSION = "scientific-decision-features-v1"
MODEL_VERSION = "learned-decision-mlp-v1"
DATASET_VERSION = "decision-dataset-v1"
ACTIONS = ("REQUEST_INFORMATION", "ANALYZE", "SIMULATE", "OPTIMIZE", "REQUEST_REVIEW", "ABSTAIN")
FEATURES = (
    "accepted_observation_count", "measurement_completeness", "available_analysis_count",
    "pending_analysis_count", "analysis_tool_available", "available_simulation_count",
    "simulation_tool_available", "gp_model_ready", "gp_mean_uncertainty",
    "optimization_ready", "optimization_tool_available", "pending_review_count", "available_tool_count",
    "missing_required_information_count", "provenance_valid", "validation_status",
    "workflow_state", "state_field_missing_count",
)


class DecisionInputError(ValueError):
    pass


class FeatureExtractor:
    """Versioned deterministic ScientificState-to-model feature contract."""
    schema_version=FEATURE_SCHEMA_VERSION
    feature_names=FEATURES

    @staticmethod
    def extract(state: dict[str, Any]) -> np.ndarray:
        if not isinstance(state, dict):
            raise DecisionInputError("ScientificState must be a JSON object")
        values: list[float] = []
        absent = 0
        for name in FEATURES[:-1]:
            value = state.get(name)
            if value is None:
                absent += 1
                value = 0
            if isinstance(value, bool):
                numeric = float(value)
            elif isinstance(value, (int, float)):
                numeric = float(value)
            else:
                raise DecisionInputError(f"Feature '{name}' must be numeric or boolean")
            if not np.isfinite(numeric):
                raise DecisionInputError(f"Feature '{name}' must be finite")
            if name in {"measurement_completeness", "provenance_valid"} and not 0 <= numeric <= 1:
                raise DecisionInputError(f"Feature '{name}' must be between 0 and 1")
            values.append(numeric)
        values.append(float(absent))
        return np.asarray(values, dtype=float)


def encode_state(state: dict[str, Any]) -> np.ndarray:
    return FeatureExtractor.extract(state)


def state_from_experiment(experiment, observations, analysis_runs, simulation_runs, optimization_runs, tool_recommendations=None) -> dict[str, Any]:
    accepted = [row for row in observations if row.review_status == "ACCEPTED"]
    pending = [row for row in observations if row.review_status in {"PENDING", "NEEDS_REVIEW"}]
    total = len(observations)
    valid = sum(row.normalization_error is None and row.normalized_value is not None for row in accepted)
    analysis_ready = sum(str(row.analysis_status).casefold() == "completed" for row in analysis_runs)
    analysis_pending = sum(str(row.analysis_status).casefold() not in {"completed", "failed", "rejected"} for row in analysis_runs)
    simulation_ready = sum(str(row.status).casefold() in {"completed", "succeeded"} for row in simulation_runs)
    models = [row for row in optimization_runs if row.status == "COMPLETED"]
    newest = models[-1] if models else None
    uncertainty = 0.0
    if newest:
        uncertainty = float(newest.metrics_json.get("holdout", {}).get("mean_normalized_std", 0.0) or 0.0)
    required = 0
    if experiment.method_version:
        actual = {variable.name for step in experiment.steps for variable in step.variables}
        required = sum(1 for field in experiment.method_version.condition_definitions or [] if field.get("required") and field.get("name") not in actual)
    provenance_valid = all(bool(row.source_id) and not row.normalization_error for row in accepted)
    recommendations=tool_recommendations or []
    ready_tools=[item for item in recommendations if item.get("readiness")=="READY"]
    analysis_tool_available=any(item.get("category")=="analysis" and item.get("connected")
        and item.get("readiness") in {"READY","REQUIRES_REVIEW"} for item in recommendations) or bool(analysis_pending)
    simulation_tool_available=any(item.get("category")=="simulation" and item.get("connected")
        and item.get("readiness") in {"READY","REQUIRES_REVIEW"} for item in recommendations)
    return {
        "topic_id": experiment.topic_id, "experiment_id": experiment.id,
        "method_version_id": experiment.method_version_id,
        "accepted_observation_count": len(accepted),
        "measurement_completeness": valid / max(1, total),
        "available_analysis_count": analysis_ready,
        "pending_analysis_count": analysis_pending,
        "analysis_tool_available": analysis_tool_available,
        "available_simulation_count": simulation_ready,
        "simulation_tool_available": simulation_tool_available,
        "gp_model_ready": bool(models), "gp_mean_uncertainty": uncertainty,
        "optimization_ready": bool(models) and len(accepted) >= 3,
        "optimization_tool_available": bool(models) and len(accepted) >= 3,
        "pending_review_count": len(pending), "available_tool_count": len(ready_tools),
        "missing_required_information_count": required,
        "provenance_valid": bool(provenance_valid),
        "validation_status": 1.0 if valid == total and total > 0 else 0.0,
        # Never expose final experiment success/failure to the action predictor:
        # retrospective outcomes can post-date the decision being labeled.
        "workflow_state": 0.0,
        "tool_availability": {"analysis": analysis_tool_available,
            "simulation": simulation_tool_available,
            "optimization": bool(models)},
        "pending_review": len(pending) > 0,
        "missing_required_information": required > 0,
        "provenance_status": "VALID" if provenance_valid else "INCOMPLETE",
    }


def synthetic_cases(seed: int = 7, per_action: int = 24) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    cases = []
    for action_index, action in enumerate(ACTIONS):
        for sample_index in range(per_action):
            state = {
                "accepted_observation_count": max(0, int(rng.normal([0, 4, 5, 8, 3, 2][action_index], 1.5))),
                "measurement_completeness": float(np.clip(rng.normal([.05,.55,.7,.9,.75,.2][action_index], .13), 0, 1)),
                "available_analysis_count": max(0, int(rng.normal([0,0,2,2,1,0][action_index], .8))),
                "pending_analysis_count": int(action_index==1 and sample_index%4!=0),
                "analysis_tool_available": action_index==1 and sample_index%4!=0,
                "available_simulation_count": max(0, int(rng.normal([0,0,0,1,0,0][action_index], .5))),
                "simulation_tool_available": action_index==2 and sample_index%4!=0,
                "gp_model_ready": action_index == 3 and sample_index % 3 != 0,
                "gp_mean_uncertainty": float(abs(rng.normal([1,.8,.5,.2,.4,1][action_index], .25))),
                "optimization_ready": action_index == 3 and sample_index % 3 != 0,
                "optimization_tool_available": action_index == 3 and sample_index % 3 != 0,
                "pending_review_count": max(0, int(rng.normal([0,0,0,0,2,0][action_index], .7))),
                "available_tool_count": max(0, int(rng.normal([0,1,2,3,1,0][action_index], .7))),
                "missing_required_information_count": max(0, int(rng.normal([2,1,0,0,0,1][action_index], .7))),
                "provenance_valid": action_index != 5 or sample_index % 2 == 0,
                "validation_status": float(np.clip(rng.normal([0,.5,.8,.95,.7,.1][action_index],.12),0,1)),
                "workflow_state": float(rng.choice([-1,0,1])),
            }
            cases.append({"case_group_id": f"sandbox-{seed}-{action_index}-{sample_index}", "state": state, "action": action})
    rng.shuffle(cases)
    return cases


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(np.clip(shifted, -60, 60))
    return exp / np.sum(exp, axis=1, keepdims=True)


@dataclass
class LearnedDecisionHead:
    mean: np.ndarray
    scale: np.ndarray
    hidden_weight: np.ndarray
    hidden_bias: np.ndarray
    output_weight: np.ndarray
    output_bias: np.ndarray
    temperature: float = 1.0
    calibrated: bool = False

    @classmethod
    def fit(cls, x: np.ndarray, labels: list[str], *, seed: int = 7, epochs: int = 550, learning_rate: float = .035) -> tuple["LearnedDecisionHead", list[float]]:
        if len(x) != len(labels) or len(labels) < 12:
            raise DecisionInputError("At least 12 paired decision cases are required")
        if set(labels) - set(ACTIONS):
            raise DecisionInputError("Unknown action label")
        y = np.asarray([ACTIONS.index(label) for label in labels], dtype=int)
        mean = x.mean(axis=0); scale = x.std(axis=0); scale[scale < 1e-8] = 1.0
        z = np.clip((x - mean) / scale, -8, 8)
        rng = np.random.default_rng(seed)
        hidden = 12
        w1 = rng.normal(0, .12, (z.shape[1], hidden)); b1 = np.zeros(hidden)
        w2 = rng.normal(0, .08, (hidden, len(ACTIONS))); b2 = np.zeros(len(ACTIONS))
        losses = []
        for _ in range(epochs):
            h = np.tanh(z @ w1 + b1)
            probs = _softmax(h @ w2 + b2)
            losses.append(float(-np.log(np.maximum(probs[np.arange(len(y)), y], 1e-12)).mean()))
            grad = probs; grad[np.arange(len(y)), y] -= 1; grad /= len(y)
            gw2 = h.T @ grad + 1e-4*w2; gb2 = grad.sum(axis=0)
            gh = (grad @ w2.T) * (1 - h*h)
            gw1 = z.T @ gh + 1e-4*w1; gb1 = gh.sum(axis=0)
            w1 -= learning_rate*gw1; b1 -= learning_rate*gb1
            w2 -= learning_rate*gw2; b2 -= learning_rate*gb2
        return cls(mean, scale, w1, b1, w2, b2), losses

    def logits(self, x: np.ndarray) -> np.ndarray:
        z = np.clip((x-self.mean)/self.scale, -8, 8)
        return np.tanh(z @ self.hidden_weight+self.hidden_bias) @ self.output_weight+self.output_bias

    def predict_proba(self, x: np.ndarray, *, calibrated: bool = True) -> np.ndarray:
        logits=self.logits(x)/(self.temperature if calibrated else 1.0)
        return _softmax(logits)

    def calibrate(self, x: np.ndarray, labels: list[str]) -> bool:
        if len(labels) < 24 or len(set(labels)) < 3:
            self.temperature=1.0
            self.calibrated=False
            return False
        y=np.asarray([ACTIONS.index(label) for label in labels],dtype=int)
        logits=self.logits(x)
        candidates=np.geomspace(.35,3.0,80)
        losses=[-np.log(np.maximum(_softmax(logits/temp)[np.arange(len(y)),y],1e-12)).mean() for temp in candidates]
        self.temperature=float(candidates[int(np.argmin(losses))])
        self.calibrated=True
        return True

    def to_dict(self) -> dict:
        return {"feature_schema_version":FEATURE_SCHEMA_VERSION,"model_version":MODEL_VERSION,"actions":list(ACTIONS),
                "mean":self.mean.tolist(),"scale":self.scale.tolist(),"hidden_weight":self.hidden_weight.tolist(),
                "hidden_bias":self.hidden_bias.tolist(),"output_weight":self.output_weight.tolist(),"output_bias":self.output_bias.tolist(),
                "temperature":self.temperature,"calibrated":self.calibrated,"architecture":{"type":"tanh_mlp_softmax","input_size":len(FEATURES),"hidden_size":self.hidden_weight.shape[1],"output_size":len(ACTIONS)}}

    @classmethod
    def from_dict(cls, payload: dict) -> "LearnedDecisionHead":
        if payload.get("model_version") != MODEL_VERSION or payload.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or payload.get("actions") != list(ACTIONS):
            raise DecisionInputError("Unsupported learned decision model or feature schema version")
        result=cls(*(np.asarray(payload[key],dtype=float) for key in ("mean","scale","hidden_weight","hidden_bias","output_weight","output_bias")),temperature=float(payload.get("temperature",1)),calibrated=bool(payload.get("calibrated",False)))
        if len(result.mean)!=len(FEATURES) or result.scale.shape!=result.mean.shape or result.hidden_weight.shape[0]!=len(FEATURES) or result.output_weight.shape[1]!=len(ACTIONS):
            raise DecisionInputError("Stored decision model tensor shapes are invalid")
        return result

    def is_ood(self, x: np.ndarray) -> tuple[str, list[str]]:
        z=np.abs((x-self.mean)/self.scale)
        reasons=[]
        if x[-1] > 4:
            return "UNSUPPORTED_STATE", ["TOO_MANY_REQUIRED_STATE_FEATURES_MISSING"]
        if np.any(z>5): reasons.append("FEATURE_FAR_OUTSIDE_TRAINING_DISTRIBUTION")
        if not np.isfinite(x).all(): reasons.append("INVALID_FEATURE")
        return ("POTENTIAL_OOD",reasons) if reasons else ("IN_DISTRIBUTION",[])


def split_by_group(labels: list[str], groups: list[str], *, seed: int=7, fraction: float=.25) -> tuple[np.ndarray,np.ndarray]:
    if len(labels)!=len(groups) or len(set(groups))<2:
        raise DecisionInputError("At least two independent decision groups are required")
    rng=np.random.default_rng(seed); train=[]; valid=[]
    for action in sorted(set(labels)):
        indices=np.asarray([i for i,label in enumerate(labels) if label==action])
        rng.shuffle(indices)
        if len(indices)<2: raise DecisionInputError("Each action class needs two independent cases for grouped evaluation")
        count=max(1,min(len(indices)-1,int(round(len(indices)*fraction))))
        valid.extend(indices[:count].tolist()); train.extend(indices[count:].tolist())
    train_groups={groups[i] for i in train}; valid_groups={groups[i] for i in valid}
    if train_groups & valid_groups: raise DecisionInputError("Decision group leakage detected")
    return np.asarray(train,dtype=int),np.asarray(valid,dtype=int)


def calibration_metrics(y_true: list[str], probabilities: np.ndarray) -> dict:
    if not y_true: return {"sample_count":0,"status":"INSUFFICIENT_DATA"}
    yi=np.asarray([ACTIONS.index(value) for value in y_true]); n=len(yi)
    onehot=np.eye(len(ACTIONS))[yi]
    confidence=probabilities.max(axis=1); prediction=probabilities.argmax(axis=1)
    bins=[]
    ece=0.0
    for low in np.linspace(0,1,11)[:-1]:
        mask=(confidence>=low)&(confidence<(low+.1) if low<.9 else confidence<=1)
        if mask.any():
            acc=float(np.mean(prediction[mask]==yi[mask])); conf=float(confidence[mask].mean()); ece+=float(mask.mean())*abs(acc-conf)
            bins.append({"lower":float(low),"upper":float(low+.1),"count":int(mask.sum()),"accuracy":acc,"mean_confidence":conf})
    order=np.argsort(-confidence); correct=(prediction==yi)[order]; risk_coverage=[]
    for coverage in (.25,.5,.75,1.0):
        k=max(1,int(np.ceil(n*coverage)))
        risk_coverage.append({"coverage":coverage,"risk":float(1-correct[:k].mean()),"count":k})
    return {"sample_count":n,"accuracy":float(np.mean(prediction==yi)),"macro_f1":float(np.mean([
        (2*np.sum((prediction==i)&(yi==i)))/(max(1,np.sum(prediction==i)+np.sum(yi==i))) for i in range(len(ACTIONS))])),
        "negative_log_likelihood":float(-np.log(np.maximum(probabilities[np.arange(n),yi],1e-12)).mean()),
        "brier_score":float(np.square(probabilities-onehot).sum(axis=1).mean()),"expected_calibration_error_10_bins":float(ece),
        "confusion_matrix":{"labels":list(ACTIONS),"counts":[[int(np.sum((yi==a)&(prediction==b))) for b in range(len(ACTIONS))] for a in range(len(ACTIONS))]},
        "reliability_bins":bins,"risk_coverage":risk_coverage}


def majority_metrics(y_true: list[str]) -> dict:
    if not y_true:return {"sample_count":0}
    majority=max(ACTIONS,key=lambda action:sum(label==action for label in y_true))
    pred=[majority]*len(y_true)
    return {"sample_count":len(y_true),"predicted_action":majority,"accuracy":sum(a==b for a,b in zip(y_true,pred))/len(y_true),
            "macro_f1":float(np.mean([2*sum(a==c and b==c for a,b in zip(y_true,pred))/max(1,sum(a==c for a in pred)+sum(b==c for b in y_true)) for c in ACTIONS]))}


def rule_metrics(states: list[dict], y_true: list[str]) -> dict:
    rules=RuleBasedDecisionPolicy(); predictions=[]
    for state in states:
        recommendations=[]
        if state.get("optimization_ready"):
            goal="optimize experiment conditions"
        elif state.get("pending_review_count",0):
            recommendations.append({"tool_id":"xrd.local_peaks.v1","category":"analysis","readiness":"REQUIRES_REVIEW"})
            goal="xrd peaks"
        elif state.get("simulation_tool_available"):
            recommendations.append({"tool_id":"phreeqc.aqueous_equilibrium.v1","category":"simulation","readiness":"READY"})
            goal="aqueous equilibrium"
        elif state.get("analysis_tool_available"):
            recommendations.append({"tool_id":"xrd.local_peaks.v1","category":"analysis","readiness":"READY"})
            goal="xrd peaks"
        elif state.get("missing_required_information_count",0):
            recommendations.append({"tool_id":"xrd.local_peaks.v1","category":"analysis","readiness":"MISSING_INPUT"})
            goal="xrd peaks"
        else:
            goal="unknown research goal"
        action=rules.choose(state,recommendations,goal).get("action","ABSTAIN")
        mapped={"RUN_ANALYSIS":"ANALYZE","RUN_SIMULATION":"SIMULATE","RUN_OPTIMIZATION":"OPTIMIZE","REQUEST_DATA":"REQUEST_INFORMATION","REVIEW_RESULT":"REQUEST_REVIEW","ABSTAIN":"ABSTAIN"}.get(action,"ABSTAIN")
        predictions.append(mapped)
    return {"sample_count":len(y_true),"accuracy":float(np.mean(np.asarray(predictions)==np.asarray(y_true))),"predictions":predictions,
            "macro_f1":float(np.mean([2*sum(a==c and b==c for a,b in zip(y_true,predictions))/max(1,sum(a==c for a in predictions)+sum(b==c for b in y_true)) for c in ACTIONS]))}


def dataset_digest(rows: list[dict]) -> str:
    raw=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def infer_safe(model: LearnedDecisionHead, state: dict) -> dict:
    x=encode_state(state).reshape(1,-1)
    started=time.perf_counter(); probs=model.predict_proba(x)[0]; latency=(time.perf_counter()-started)*1000
    ood,reasons=model.is_ood(x[0]); best=int(np.argmax(probs)); predicted=ACTIONS[best]; confidence=float(probs[best])
    if ood!="IN_DISTRIBUTION": action="ABSTAIN"; abstention="State is outside the learned training range or is missing required features."
    elif int(state.get("missing_required_information_count",0) or 0)>0: action="REQUEST_INFORMATION"; abstention=None
    elif int(state.get("pending_review_count",0) or 0)>0: action="REQUEST_REVIEW"; abstention=None
    elif confidence < .45: action="ABSTAIN"; abstention="Model confidence is below the review threshold."
    else: action=predicted; abstention=None
    return {"action":action,"raw_predicted_action":predicted,"action_probabilities":{name:float(probs[i]) for i,name in enumerate(ACTIONS)},
            "confidence":confidence,"confidence_semantics":"temperature_scaled_score" if model.calibrated else "uncalibrated_softmax_score",
            "ood_status":ood,"ood_reasons":reasons,"abstention_reason":abstention,"inference_latency_ms":latency,
            "mode":"SHADOW_ONLY","workflow_triggered":False,"model_version":MODEL_VERSION}
