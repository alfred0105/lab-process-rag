"""Local Phase 6 shared-transformer decision API (shadow-only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.database import get_db

from app.services.phase6_hybrid import (
    MODEL_ID, MODEL_REVISION, Phase6Unavailable, ScientificContextError,
    _artifact_path, _default_model_path, get_runtime,
)

router = APIRouter(prefix="/decisions/hybrid", tags=["phase6-hybrid"])


class HybridInferIn(BaseModel):
    scientific_state: dict[str, Any] | None = None
    topic_id: int | None = Field(default=None, gt=0)
    experiment_id: int | None = Field(default=None, gt=0)
    user_request: str = Field(min_length=1, max_length=4000)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    explanation_requested: bool = False
    max_new_tokens: int = Field(default=96, ge=1, le=256)


@router.get("/models")
def models():
    return {"status": "LOCAL_CHECKPOINT_READY" if _default_model_path().exists() else "CHECKPOINT_MISSING",
            "model_id": MODEL_ID, "revision": MODEL_REVISION,
            "checkpoint_path": str(_default_model_path()), "checkpoint_downloaded": _default_model_path().exists(),
            "decision_head_artifact": str(_artifact_path()), "decision_head_trained": _artifact_path().is_file(),
            "license": "Apache-2.0", "workflow_triggered": False}


@router.get("/runtime")
def runtime_status():
    try:
        import torch
    except ImportError:
        return {"status": "OPTIONAL_PHASE6_RUNTIME_NOT_INSTALLED", "checkpoint_downloaded": _default_model_path().exists(),
                "decision_head_trained": _artifact_path().is_file(), "workflow_triggered": False}
    return {"checkpoint_downloaded": _default_model_path().exists(),
            "decision_head_trained": _artifact_path().is_file(),
            "mps_available": bool(torch.backends.mps.is_available()),
            "cuda_available": bool(torch.cuda.is_available()),
            "artifact_path": str(_artifact_path()), "workflow_triggered": False}


@router.post("/infer")
def infer(payload: HybridInferIn, db: Session = Depends(get_db)):
    try:
        state = payload.scientific_state
        if payload.experiment_id is not None:
            if payload.topic_id is None:
                raise HTTPException(422, detail="topic_id is required with experiment_id")
            from app.api.decisions import _stage3_experiment_state
            state = _stage3_experiment_state(db, payload.topic_id, payload.experiment_id)
        if state is None:
            raise HTTPException(422, detail="Provide a ScientificState V2 or a recorded non-demo experiment.")
        return get_runtime().infer(state, payload.user_request,
                                   evidence=payload.evidence,
                                   explanation_requested=payload.explanation_requested,
                                   max_new_tokens=payload.max_new_tokens)
    except ScientificContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Phase6Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Install backend/requirements-phase6.txt to enable the optional local Transformer runtime.") from exc


@router.post("/explain")
def explain(payload: HybridInferIn, db: Session = Depends(get_db)):
    return infer(payload.model_copy(update={"explanation_requested": True}), db)


@router.get("/benchmarks")
def benchmarks():
    reports = Path(__file__).resolve().parents[2] / "reports"
    names = ("phase6_decision_benchmark.json", "phase6_early_exit_benchmark.json",
             "phase6_generation_benchmark.json", "phase6_memory_latency.json")
    result = {}
    for name in names:
        path = reports / name
        if path.is_file():
            try:
                result[name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result[name] = {"status": "INVALID_REPORT"}
        else:
            result[name] = {"status": "NOT_RUN"}
    return {"reports": result, "workflow_triggered": False}
