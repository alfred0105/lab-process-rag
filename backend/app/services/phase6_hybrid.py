"""One-checkpoint Phase 6 hybrid inference for the local Qwen3 decoder.

The language model is lazily loaded from a local checkpoint. Decision-only
requests never call `generate`; intermediate exits stop the decoder loop. The
learned action head is a small projection over the same decoder hidden states.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.services.decision_head import ACTIONS
from app.services.phase5_stage4 import _risk_threshold, _temperature_from_calibration
from app.services.scientific_state_v2 import ACTION_NAMES, FEATURE_SCHEMA_VERSION_V2, SCIENTIFIC_STATE_SCHEMA_VERSION

MODEL_ID = "Qwen/Qwen3-0.6B"
MODEL_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"
TOKENIZER_REVISION = MODEL_REVISION
CONTEXT_ADAPTER_VERSION = "scientific-state-text-v1"
DECISION_HEAD_VERSION = "shared-transformer-linear-decision-head-v1"
EXIT_LAYER_NUMBERS = (7, 14, 21, 28)
ROUTE_DECISION_ONLY = "DECISION_ONLY"
ROUTE_CONTINUE = "CONTINUE_BACKBONE"
ROUTE_GENERATE = "GENERATE_EXPLANATION"
ROUTE_REVIEW = "REQUEST_REVIEW"
ROUTE_ABSTAIN = "ABSTAIN"


class Phase6Unavailable(RuntimeError):
    pass


class ScientificContextError(ValueError):
    pass


def _default_model_path() -> Path:
    cache_root = Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache" / "huggingface" / "hub"))
    return cache_root / "models--Qwen--Qwen3-0.6B" / "snapshots" / MODEL_REVISION


def _artifact_path() -> Path:
    return Path(os.environ.get(
        "LAB_PROCESS_RAG_PHASE6_ARTIFACT_PATH",
        Path.home() / ".cache" / "lab-process-rag" / "phase6-decision-heads.pt",
    )).expanduser()


def _strip_model_shortcuts(value: Any) -> Any:
    """Drop identity, label and retrospective outcome fields from model text."""
    banned = {
        "action", "selected_action", "label", "target", "outcome", "success", "failure",
        "experiment_id", "topic_id", "case_id", "snapshot_id", "decision_id", "group_id",
        "source_provenance", "experiment_run_id", "method_version_id",
    }
    if isinstance(value, dict):
        return {str(k): _strip_model_shortcuts(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
                if str(k).casefold() not in banned and not str(k).casefold().endswith("_id")}
    if isinstance(value, list):
        return [_strip_model_shortcuts(v) for v in value]
    return value


def _safe_evidence(evidence: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in evidence or []:
        status = str(item.get("evidence_status", "UNKNOWN")).upper()
        citation = str(item.get("citation") or item.get("source_document_id") or "").strip()
        text = str(item.get("text", "")).strip()
        if status != "SUPPORTED" or not citation or not text:
            warnings.append("검색 근거 중 출처·상태가 검증되지 않은 항목은 설명 근거로 사용하지 않았습니다.")
            continue
        accepted.append({
            "citation": citation[:300],
            "chunk_id": str(item.get("chunk_id", ""))[:200],
            "retrieval_score": float(item["retrieval_score"]) if isinstance(item.get("retrieval_score"), (int, float)) else None,
            "provenance": str(item.get("provenance", ""))[:200],
            "evidence_status": status,
            "text": text[:4000],
        })
    return accepted, sorted(set(warnings))


def build_scientific_prompt(state: dict[str, Any], user_request: str, evidence: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    if not isinstance(state, dict) or state.get("schema_version") != SCIENTIFIC_STATE_SCHEMA_VERSION:
        raise ScientificContextError(f"Expected schema_version={SCIENTIFIC_STATE_SCHEMA_VERSION}")
    if not isinstance(user_request, str) or not user_request.strip() or len(user_request) > 4000:
        raise ScientificContextError("user_request must contain 1–4000 characters")
    cleaned = _strip_model_shortcuts(state)
    evidence_rows, warnings = _safe_evidence(evidence)
    prompt = {
        "Experiment": cleaned.get("experiment", {}),
        "Method": cleaned.get("process_conditions", {}),
        "Measurements": cleaned.get("measurements", {}),
        "Analysis Status": cleaned.get("analysis", {}),
        "Simulation Readiness": cleaned.get("simulation", {}),
        "Optimization Readiness": cleaned.get("optimization", {}),
        "Provenance and Data Quality": cleaned.get("provenance", {}),
        "Pending Approval": cleaned.get("pending_reviews", {}),
        "User Request": user_request.strip(),
        "Validated Literature Evidence": evidence_rows,
    }
    provenance = cleaned.get("provenance", {})
    valid = isinstance(provenance, dict) and provenance.get("validity") not in {"INVALID", "INCOMPLETE", "UNKNOWN"}
    quality = provenance.get("data_quality_gate") if isinstance(provenance, dict) else None
    if quality == "BLOCK":
        valid = False
    summary = {
        "adapter_version": CONTEXT_ADAPTER_VERSION,
        "input_schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
        "provenance_valid": bool(valid),
        "data_quality_gate": quality or "UNKNOWN",
        "validated_evidence_count": len(evidence_rows),
        "evidence_warnings": warnings,
        "source_timestamp": str(state.get("source_timestamp", ""))[:100],
        "source_records_retained_for_audit": len((state.get("source_provenance") or {}).get("observation_ids", [])) if isinstance(state.get("source_provenance"), dict) else 0,
    }
    return json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":")), summary


def _system_prompt() -> str:
    return (
        "You are a laboratory research assistant. The structured action has already been decided by a separate classifier and safety policy; "
        "never change that action or execute tools. Explain only the supplied state and explicitly supported evidence. "
        "Distinguish recorded observations, supported literature, and uncertainty. Do not invent measurements, citations, causal conclusions, "
        "success probabilities, or material identities. Cite each literature claim with its supplied citation identifier. "
        "If evidence is missing, say what information is missing. Output Korean when the user asks in Korean."
    )


class SharedTransformerBackbone:
    """A single Qwen3 model instance with direct layer-wise hidden-state access."""

    def __init__(self, model_path: str | Path | None = None, *, device: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.model_path = Path(model_path).expanduser() if model_path else _default_model_path()
        if not self.model_path.exists():
            raise Phase6Unavailable(f"Local checkpoint not found: {self.model_path}; download it as a separate setup step.")
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        dtype = torch.float16 if self.device == "mps" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path, dtype=dtype, low_cpu_mem_usage=True, local_files_only=True,
        ).eval().to(self.device)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.backbone = self.model.model
        self.hidden_size = int(self.model.config.hidden_size)
        self.layer_count = int(self.model.config.num_hidden_layers)
        self.exit_layers = tuple(min(x, self.layer_count) for x in EXIT_LAYER_NUMBERS)
        if self.exit_layers[-1] != self.layer_count:
            self.exit_layers = tuple(sorted(set((*self.exit_layers, self.layer_count))))
        self.precision = str(next(self.model.parameters()).dtype)
        self.shared_weights = self.model.lm_head.weight.data_ptr() == self.backbone.embed_tokens.weight.data_ptr()
        self.total_parameters = sum(p.numel() for p in self.model.parameters())

    def format_tokens(self, prompt: str, *, user_request: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": f"Research state JSON:\n{prompt}\n\nRequest:\n{user_request}"},
        ]
        encoded = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt",
            enable_thinking=False,
        )
        encoded = {k: v.to(self.device) for k, v in encoded.items() if hasattr(v, "to")}
        if encoded["input_ids"].shape[1] > 2048:
            raise ScientificContextError("Formatted context exceeds the 2048-token Phase 6 limit; shorten the request/evidence.")
        return encoded

    def forward_to_exits(self, input_ids, attention_mask=None, *, use_cache=False):
        """Run exactly the requested prefix depth and return decision-token states.

        The full-depth generation path can retain a complete per-layer KV cache.
        Intermediate-exit caches are never passed to LM generation; callers must
        use the documented full-prefill fallback.
        """
        from transformers.masking_utils import create_causal_mask
        from transformers.cache_utils import DynamicCache

        torch = self.torch
        core = self.backbone
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids)
        input_embeds = core.embed_tokens(input_ids)
        past = DynamicCache(config=self.model.config) if use_cache else None
        cache_position = torch.arange(input_ids.shape[1], device=input_ids.device)
        position_ids = cache_position.unsqueeze(0)
        mask = create_causal_mask(
            config=core.config, input_embeds=input_embeds, attention_mask=attention_mask,
            cache_position=cache_position, past_key_values=past, position_ids=position_ids,
        )
        position_embeddings = core.rotary_emb(input_embeds, position_ids)
        hidden = input_embeds
        snapshots: dict[int, Any] = {}
        for layer_index, layer in enumerate(core.layers, start=1):
            hidden = layer(
                hidden, attention_mask=mask, position_ids=position_ids, past_key_values=past,
                use_cache=use_cache, cache_position=cache_position, position_embeddings=position_embeddings,
            )
            if layer_index in self.exit_layers:
                snapshots[layer_index] = core.norm(hidden[:, -1, :])
        return {"hidden_by_layer": snapshots, "past_key_values": past if use_cache else None,
                "executed_layers": self.layer_count, "token_count": int(input_ids.shape[1])}

    def early_hidden(self, input_ids, attention_mask, *, decision_heads, gates, input_valid: bool, ood_thresholds,
                     allow_early_exit: bool = True):
        """Execute until a calibrated, supported early head accepts or final depth."""
        from transformers.masking_utils import create_causal_mask

        torch = self.torch
        core = self.backbone
        embeds = core.embed_tokens(input_ids)
        cache_position = torch.arange(input_ids.shape[1], device=input_ids.device)
        position_ids = cache_position.unsqueeze(0)
        mask = create_causal_mask(config=core.config, input_embeds=embeds, attention_mask=attention_mask,
                                  cache_position=cache_position, past_key_values=None, position_ids=position_ids)
        position_embeddings = core.rotary_emb(embeds, position_ids)
        hidden = embeds
        traces = []
        for layer_index, layer in enumerate(core.layers, start=1):
            hidden = layer(hidden, attention_mask=mask, position_ids=position_ids, past_key_values=None,
                           use_cache=False, cache_position=cache_position, position_embeddings=position_embeddings)
            if layer_index not in self.exit_layers:
                continue
            state = core.norm(hidden[:, -1, :])
            logits = decision_heads[str(layer_index)](state.float())
            probs = gates["temperatures"][str(layer_index)](logits)
            confidence = float(probs.max().item())
            ood_score = gates["ood"][str(layer_index)].score(state)
            ood = ood_score > ood_thresholds[str(layer_index)]
            threshold = gates["exit_thresholds"].get(str(layer_index))
            can_exit = allow_early_exit and layer_index < self.layer_count and input_valid and not ood and threshold is not None and confidence >= threshold
            traces.append({"layer": layer_index, "confidence": confidence, "ood_score": ood_score,
                           "ood": bool(ood), "exit_threshold": threshold, "accepted": bool(can_exit)})
            if can_exit:
                return {"hidden": state, "logits": logits, "probabilities": probs, "exit_layer": layer_index,
                        "executed_layers": layer_index, "trace": traces, "ood_score": ood_score, "ood": bool(ood)}
        final_layer = self.layer_count
        final_state = core.norm(hidden[:, -1, :])
        final_logits = decision_heads[str(final_layer)](final_state.float())
        final_probs = gates["temperatures"][str(final_layer)](final_logits)
        final_score = gates["ood"][str(final_layer)].score(final_state)
        final_ood = final_score > ood_thresholds[str(final_layer)]
        traces.append({"layer": final_layer, "confidence": float(final_probs.max().item()), "ood_score": final_score,
                       "ood": bool(final_ood), "exit_threshold": None, "accepted": True})
        return {"hidden": final_state, "logits": final_logits, "probabilities": final_probs, "exit_layer": final_layer,
                "executed_layers": final_layer, "trace": traces, "ood_score": final_score, "ood": bool(final_ood)}

    def generate_from_full_cache(self, encoded: dict[str, Any], *, max_new_tokens: int = 96) -> tuple[str, int, float, int]:
        """Greedy autoregressive generation using a complete same-instance KV cache."""
        torch = self.torch
        started = time.perf_counter()
        input_ids = encoded["input_ids"]
        attention_mask = encoded.get("attention_mask", torch.ones_like(input_ids))
        with torch.inference_mode():
            full = self.model(input_ids=input_ids, attention_mask=attention_mask, use_cache=True, return_dict=True)
            cache = full.past_key_values
            next_logits = full.logits[:, -1, :]
            generated = []
            stop_id = self.tokenizer.eos_token_id
            mask = attention_mask
            for _ in range(max_new_tokens):
                token = torch.argmax(next_logits, dim=-1, keepdim=True)
                generated.append(token)
                if stop_id is not None and int(token[0, 0]) == stop_id:
                    break
                mask = torch.cat([mask, mask.new_ones((mask.shape[0], 1))], dim=-1)
                output = self.model(input_ids=token, attention_mask=mask, past_key_values=cache, use_cache=True, return_dict=True)
                cache = output.past_key_values
                next_logits = output.logits[:, -1, :]
        if not generated:
            return "", 0, (time.perf_counter() - started) * 1000, 0
        tokens = torch.cat(generated, dim=1)
        text = self.tokenizer.decode(tokens[0], skip_special_tokens=True)
        count = int(tokens.shape[1])
        elapsed = (time.perf_counter() - started) * 1000
        cache_bytes = sum(layer.keys.numel() * layer.keys.element_size() + layer.values.numel() * layer.values.element_size()
                          for layer in cache.layers if layer.keys is not None and layer.values is not None)
        return text, count, elapsed, int(cache_bytes)

    def metadata(self) -> dict[str, Any]:
        return {
            "model_id": MODEL_ID, "model_revision": MODEL_REVISION, "tokenizer_revision": TOKENIZER_REVISION,
            "model_path": str(self.model_path), "parameter_count": self.total_parameters,
            "hidden_dimension": self.hidden_size, "layer_count": self.layer_count,
            "context_length_limit": 2048, "configured_model_context_length": int(self.model.config.max_position_embeddings),
            "precision": self.precision, "device": self.device, "shared_lm_embedding_weights": bool(self.shared_weights),
            "exit_layers": list(self.exit_layers), "lm_head_parameter_count": sum(p.numel() for p in self.model.lm_head.parameters()),
        }


class _OodScorer:
    def __init__(self, mean, scale):
        self.mean = np.asarray(mean, dtype=np.float32)
        self.scale = np.asarray(scale, dtype=np.float32)

    def score(self, tensor) -> float:
        value = tensor.detach().float().cpu().numpy().reshape(-1)
        z = np.clip((value - self.mean) / self.scale, -8, 8)
        return float(np.sqrt(np.mean(z * z)))


def _softmax_temperature(logits, temperature: float):
    import torch
    return torch.softmax(logits.float() / max(.05, float(temperature)), dim=-1)


def _training_context(state: dict[str, Any]) -> str:
    # Synthetic state context uses the same typed adapter and explicitly omits labels/identifiers.
    return json.dumps(_strip_model_shortcuts(state), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def train_sandbox_heads(*, model: SharedTransformerBackbone, rows: list[dict[str, Any]], fit_indexes,
                        calibration_indexes, eval_indexes, artifact: Path | None = None, epochs: int = 40,
                        batch_size: int = 12, seed: int = 20261101) -> dict[str, Any]:
    """Train real torch heads over frozen pretrained hidden states; labels must be sandbox fixtures."""
    import torch
    from torch import nn

    if len(rows) < 120 or len(fit_indexes) == 0 or len(calibration_indexes) == 0 or len(eval_indexes) == 0:
        raise ValueError("Sandbox head training requires >=120 rows and non-empty fit/calibration/evaluation splits")
    if any(row.get("label_source") != "SYNTHETIC_SANDBOX" for row in rows):
        raise ValueError("This training routine accepts only explicitly synthetic sandbox rows")
    labels = [str(row["action"]) for row in rows]
    if set(labels) - set(ACTIONS):
        raise ValueError("Unknown action label in sandbox fixture")
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    before_backbone = hashlib.sha256(b"".join(p.detach().cpu().numpy().tobytes() for p in model.model.parameters())).hexdigest()
    hidden_cache: dict[int, dict[str, Any]] = {}
    model.model.eval()
    for index, row in enumerate(rows):
        state = row.get("state")
        prompt = _training_context(state)
        encoded = model.format_tokens(prompt, user_request="Select the appropriate next action for this recorded laboratory state.")
        with torch.inference_mode():
            outputs = model.forward_to_exits(encoded["input_ids"], encoded.get("attention_mask"), use_cache=False)
        hidden_cache[index] = {layer: outputs["hidden_by_layer"][layer][0].detach().float().cpu().numpy() for layer in model.exit_layers}
        if (index + 1) % 20 == 0:
            print(f"Phase 6 hidden-state extraction: {index + 1}/{len(rows)}", flush=True)

    exit_heads = nn.ModuleDict({str(layer): nn.Linear(model.hidden_size, len(ACTIONS), dtype=torch.float32) for layer in model.exit_layers})
    for head in exit_heads.values():
        nn.init.xavier_uniform_(head.weight)
        nn.init.zeros_(head.bias)
    optimizer = torch.optim.AdamW(exit_heads.parameters(), lr=2e-3, weight_decay=1e-3)
    loss_fn = nn.CrossEntropyLoss()
    targets = torch.tensor([ACTIONS.index(labels[i]) for i in fit_indexes], dtype=torch.long)
    fit_features = {layer: torch.tensor(np.stack([hidden_cache[i][layer] for i in fit_indexes]), dtype=torch.float32) for layer in model.exit_layers}
    losses_by_layer: dict[str, dict[str, float]] = {}
    for layer in model.exit_layers:
        losses_by_layer[str(layer)] = {}
    for layer in model.exit_layers:
        head = exit_heads[str(layer)]
        initial = float(loss_fn(head(fit_features[layer]), targets).item())
        losses_by_layer[str(layer)]["first"] = initial
    for _ in range(epochs):
        permutation = rng.permutation(len(fit_indexes))
        for start in range(0, len(permutation), batch_size):
            indices = permutation[start:start + batch_size]
            optimizer.zero_grad(set_to_none=True)
            loss = sum(loss_fn(exit_heads[str(layer)](fit_features[layer][indices]), targets[indices]) for layer in model.exit_layers)
            loss.backward()
            optimizer.step()
    for layer in model.exit_layers:
        losses_by_layer[str(layer)]["last"] = float(loss_fn(exit_heads[str(layer)](fit_features[layer]), targets).item())

    temperatures: dict[str, float] = {}
    exit_thresholds: dict[str, float | None] = {}
    ood: dict[str, _OodScorer] = {}
    ood_thresholds: dict[str, float] = {}
    calibration_summary = {}
    for layer in model.exit_layers:
        head = exit_heads[str(layer)]
        cal_x = torch.tensor(np.stack([hidden_cache[i][layer] for i in calibration_indexes]), dtype=torch.float32)
        cal_y = [labels[i] for i in calibration_indexes]
        with torch.no_grad():
            cal_logits = head(cal_x).numpy()
        uncal = np.exp(cal_logits - cal_logits.max(axis=1, keepdims=True))
        uncal /= uncal.sum(axis=1, keepdims=True)
        temperature = _temperature_from_calibration(uncal, cal_y)
        calibrated_logits = cal_logits / temperature
        probs = np.exp(calibrated_logits - calibrated_logits.max(axis=1, keepdims=True))
        probs /= probs.sum(axis=1, keepdims=True)
        gate = _risk_threshold(probs, cal_y, target=.20, min_covered=24)
        temperatures[str(layer)] = float(temperature)
        exit_thresholds[str(layer)] = gate.get("threshold") if layer < model.layer_count else None
        fit_h = np.stack([hidden_cache[i][layer] for i in fit_indexes])
        cal_h = np.stack([hidden_cache[i][layer] for i in calibration_indexes])
        mean = fit_h.mean(axis=0)
        scale = fit_h.std(axis=0)
        scale[scale < 1e-5] = 1.0
        scorer = _OodScorer(mean, scale)
        cal_scores = np.asarray([scorer.score(torch.tensor(v)) for v in cal_h], dtype=float)
        ood[str(layer)] = scorer
        ood_thresholds[str(layer)] = float(np.quantile(cal_scores, .95, method="higher"))
        calibration_summary[str(layer)] = {"temperature": float(temperature), "exit_gate": gate,
            "ood_threshold": ood_thresholds[str(layer)], "calibration_count": len(calibration_indexes)}

    test_metrics = {}
    for layer in model.exit_layers:
        head = exit_heads[str(layer)]
        test_x = torch.tensor(np.stack([hidden_cache[i][layer] for i in eval_indexes]), dtype=torch.float32)
        logits = head(test_x).detach().numpy() / temperatures[str(layer)]
        probs = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs /= probs.sum(axis=1, keepdims=True)
        y = np.asarray([ACTIONS.index(labels[i]) for i in eval_indexes])
        pred = probs.argmax(axis=1)
        threshold = exit_thresholds[str(layer)]
        conf = probs.max(axis=1)
        accepted = conf >= threshold if threshold is not None else np.zeros(len(conf), dtype=bool)
        test_metrics[str(layer)] = {
            "evaluation_count": len(eval_indexes),
            "accuracy": float(np.mean(pred == y)),
            "macro_f1": float(np.mean([_f1_for_class(y, pred, c) for c in range(len(ACTIONS))])),
            "selective_coverage": float(np.mean(accepted)),
            "selective_risk": float(np.mean(pred[accepted] != y[accepted])) if accepted.any() else None,
            "threshold": threshold,
            "high_confidence_wrong_count": int(np.sum((pred != y) & (conf >= .9))),
        }
    after_backbone = hashlib.sha256(b"".join(p.detach().cpu().numpy().tobytes() for p in model.model.parameters())).hexdigest()
    if before_backbone != after_backbone:
        raise RuntimeError("Frozen backbone parameters changed during sandbox head training")
    artifact = artifact or _artifact_path()
    artifact.parent.mkdir(parents=True, exist_ok=True)
    package = {
        "artifact_version": 1,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "tokenizer_revision": TOKENIZER_REVISION,
        "context_adapter_version": CONTEXT_ADAPTER_VERSION,
        "decision_head_version": DECISION_HEAD_VERSION,
        "action_mapping": list(ACTIONS),
        "feature_schema_version": FEATURE_SCHEMA_VERSION_V2,
        "source_label": "SYNTHETIC_SANDBOX",
        "training_group_count": len({rows[i]["group_id"] for i in fit_indexes}),
        "calibration_group_count": len({rows[i]["group_id"] for i in calibration_indexes}),
        "head_layers": list(model.exit_layers),
        "hidden_size": model.hidden_size,
        "temperatures": temperatures,
        "exit_thresholds": exit_thresholds,
        "ood_thresholds": ood_thresholds,
        "ood_means": {str(layer): ood[str(layer)].mean.tolist() for layer in model.exit_layers},
        "ood_scales": {str(layer): ood[str(layer)].scale.tolist() for layer in model.exit_layers},
        "calibration_summary": calibration_summary,
        "final_confidence_threshold": calibration_summary[str(model.layer_count)]["exit_gate"].get("threshold"),
        "losses_by_layer": losses_by_layer,
        "evaluation_metrics": test_metrics,
        "backbone_frozen_digest": before_backbone,
        "head_state_dict": exit_heads.state_dict(),
        "parameter_count": int(sum(p.numel() for p in exit_heads.parameters())),
        "training_config": {"epochs": epochs, "batch_size": batch_size, "seed": seed},
    }
    torch.save(package, artifact)
    return {key: value for key, value in package.items() if key != "head_state_dict"} | {"artifact_path": str(artifact)}


def _f1_for_class(y, pred, class_index):
    tp = int(np.sum((y == class_index) & (pred == class_index)))
    fp = int(np.sum((y != class_index) & (pred == class_index)))
    fn = int(np.sum((y == class_index) & (pred != class_index)))
    return 2 * tp / max(1, 2 * tp + fp + fn)


class Phase6HybridRuntime:
    def __init__(self, model_path: str | Path | None = None, artifact_path: str | Path | None = None, *, device: str | None = None):
        self.backbone = SharedTransformerBackbone(model_path, device=device)
        self.artifact_path = Path(artifact_path).expanduser() if artifact_path else _artifact_path()
        self.heads = None
        self.metadata = None
        self.ood_scorers = None
        if self.artifact_path.is_file():
            self.load_heads()

    def load_heads(self):
        import torch
        from torch import nn
        if not self.artifact_path.is_file():
            raise Phase6Unavailable("No trained decision-head artifact; run the sandbox training or reviewed-data training workflow first.")
        state = torch.load(self.artifact_path, map_location="cpu", weights_only=True)
        if state.get("model_id") != MODEL_ID or state.get("model_revision") != MODEL_REVISION:
            raise Phase6Unavailable("Decision-head artifact is incompatible with the loaded backbone revision.")
        heads = nn.ModuleDict({str(layer): nn.Linear(self.backbone.hidden_size, len(ACTIONS), dtype=torch.float32)
                               for layer in state["head_layers"]})
        heads.load_state_dict(state["head_state_dict"])
        heads.eval().to(self.backbone.device)
        self.heads = heads
        self.metadata = {key: value for key, value in state.items() if key not in {"head_state_dict", "ood_means", "ood_scales"}}
        self.temperatures = state["temperatures"]
        self.exit_thresholds = state["exit_thresholds"]
        self.ood_thresholds = state["ood_thresholds"]
        self.ood_scorers = {layer: _OodScorer(state["ood_means"][layer], state["ood_scales"][layer]) for layer in state["ood_means"]}
        return {"artifact_path": str(self.artifact_path), "model_id": state["model_id"], "source_label": state["source_label"],
                "decision_head_version": state["decision_head_version"], "trained_layers": state["head_layers"]}

    def _gates(self):
        return {"temperatures": {layer: _Temperature(self.temperatures[layer]) for layer in self.temperatures},
                "exit_thresholds": self.exit_thresholds, "ood": self.ood_scorers}

    def infer(self, state: dict[str, Any], user_request: str, *, evidence=None, explanation_requested: bool = False,
              max_new_tokens: int = 96, force_full_depth: bool = False) -> dict[str, Any]:
        prompt, context_meta = build_scientific_prompt(state, user_request, evidence)
        pending_review = bool((state.get("pending_reviews") or {}).get("measurement_review_count", 0)
                              or (state.get("pending_reviews") or {}).get("analysis_review_count", 0)
                              or (state.get("pending_reviews") or {}).get("optimization_review_count", 0))
        if not context_meta["provenance_valid"]:
            return self._early_reject(context_meta, reason="데이터 출처 또는 품질 검증이 통과하지 않아 판단을 보류합니다.", action="ABSTAIN")
        if self.heads is None:
            self.load_heads()
        encoded = self.backbone.format_tokens(prompt, user_request=user_request)
        started = time.perf_counter()
        self.backbone.model.eval()
        with self.backbone.torch.inference_mode():
            result = self.backbone.early_hidden(
                encoded["input_ids"], encoded.get("attention_mask"), decision_heads=self.heads,
                gates=self._gates(), input_valid=context_meta["provenance_valid"], ood_thresholds=self.ood_thresholds,
                allow_early_exit=not force_full_depth,
            )
        probs = result["probabilities"][0].detach().float().cpu().numpy()
        raw_action = ACTIONS[int(np.argmax(probs))]
        conf = float(np.max(probs))
        safe_action = raw_action
        override = None
        if pending_review:
            safe_action = "REQUEST_REVIEW"; override = "PENDING_RESEARCHER_REVIEW"
        elif result["ood"]:
            safe_action = "ABSTAIN"; override = "POTENTIAL_OOD"
        elif self.metadata.get("final_confidence_threshold") is None or conf < float(self.metadata["final_confidence_threshold"]):
            safe_action = "ABSTAIN"; override = "LOW_CONFIDENCE"
        probs_map = {name: float(probs[ACTIONS.index(name)]) for name in ACTIONS}
        decision_latency = (time.perf_counter() - started) * 1000
        generated_text = None; generated_tokens = 0; generation_latency = 0.0; kv_bytes = 0
        generation_status = "NOT_REQUESTED"
        if explanation_requested:
            if context_meta["validated_evidence_count"] == 0:
                # Fail closed: an unconstrained LM explanation without a citation could invent a scientific claim.
                generated_text = "검증된 인용 근거가 없어 설명 생성을 보류했습니다. 필요한 논문 또는 검토된 분석 결과를 연결해 주세요."
                generation_status = "GENERATION_SKIPPED_NO_VALIDATED_EVIDENCE"
            else:
                # Early-exit cache is incomplete; do a new full-depth prefill and use its complete cache.
                generated_text, generated_tokens, generation_latency, kv_bytes = self.backbone.generate_from_full_cache(
                    encoded, max_new_tokens=max_new_tokens,
                )
                generation_status = "GENERATED_WITH_FULL_PREFILL_FALLBACK_AND_AUTOREGRESSIVE_KV_REUSE"
        status = ROUTE_GENERATE if explanation_requested else ROUTE_ABSTAIN if safe_action == "ABSTAIN" else ROUTE_REVIEW if safe_action == "REQUEST_REVIEW" else ROUTE_DECISION_ONLY
        return {
            "raw_predicted_action": raw_action,
            "final_safe_action": safe_action,
            "action_probabilities": probs_map,
            "confidence": conf,
            "calibration_status": "CALIBRATED_ON_SYNTHETIC_SANDBOX" if self.metadata.get("source_label") == "SYNTHETIC_SANDBOX" else "CALIBRATED",
            "ood_status": "POTENTIAL_OOD" if result["ood"] else "IN_DISTRIBUTION_BY_CALIBRATION_THRESHOLD",
            "safety_override": override,
            "routing_status": status,
            "exit_layer": result["exit_layer"],
            "executed_layers": result["executed_layers"],
            "layer_trace": result["trace"],
            "generation_required": bool(explanation_requested),
            "generated_text": generated_text,
            "generated_token_count": generated_tokens,
            "generation_latency_ms": generation_latency,
            "decision_latency_ms": decision_latency,
            "cache_reuse_status": generation_status,
            "kv_cache_bytes": kv_bytes,
            "backbone_version": MODEL_ID + "@" + MODEL_REVISION,
            "decision_head_version": DECISION_HEAD_VERSION,
            "snapshot_id": state.get("source_provenance", {}).get("snapshot_id") if isinstance(state.get("source_provenance"), dict) else None,
            "provenance": {"schema_version": context_meta["input_schema_version"], "evidence_count": context_meta["validated_evidence_count"],
                           "source_record_count": context_meta["source_records_retained_for_audit"]},
            "context_metadata": context_meta,
            "workflow_triggered": False,
            "backbone": self.backbone.metadata(),
            "head_parameter_count": int(self.metadata.get("parameter_count", 0)),
        }

    @staticmethod
    def _early_reject(context_meta, *, reason, action):
        return {"raw_predicted_action": action, "final_safe_action": action,
                "action_probabilities": {a: 1.0 if a == action else 0.0 for a in ACTIONS},
                "confidence": 1.0, "calibration_status": "NOT_RUN_INPUT_REJECTED", "ood_status": "NOT_RUN",
                "safety_override": reason, "routing_status": ROUTE_ABSTAIN,
                "exit_layer": 0, "executed_layers": 0, "layer_trace": [], "generation_required": False,
                "generated_text": None, "generated_token_count": 0, "generation_latency_ms": 0.0,
                "decision_latency_ms": 0.0, "cache_reuse_status": "NOT_RUN", "kv_cache_bytes": 0,
                "backbone_version": MODEL_ID + "@" + MODEL_REVISION,
                "decision_head_version": DECISION_HEAD_VERSION, "snapshot_id": None,
                "provenance": {"schema_version": context_meta["input_schema_version"], "evidence_count": context_meta["validated_evidence_count"],
                               "source_record_count": context_meta["source_records_retained_for_audit"]},
                "context_metadata": context_meta, "workflow_triggered": False, "reason": reason}


class _Temperature:
    def __init__(self, value):
        self.value = float(value)

    def __call__(self, logits):
        return _softmax_temperature(logits, self.value)


_RUNTIME: Phase6HybridRuntime | None = None


def get_runtime(*, reload: bool = False) -> Phase6HybridRuntime:
    global _RUNTIME
    if _RUNTIME is None or reload:
        model_path = os.environ.get("LAB_PROCESS_RAG_PHASE6_MODEL_PATH")
        artifact_path = os.environ.get("LAB_PROCESS_RAG_PHASE6_ARTIFACT_PATH")
        _RUNTIME = Phase6HybridRuntime(model_path=model_path, artifact_path=artifact_path,
                                       device=os.environ.get("LAB_PROCESS_RAG_PHASE6_DEVICE"))
    return _RUNTIME
