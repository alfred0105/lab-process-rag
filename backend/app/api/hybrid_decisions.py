"""Local Phase 6 shared-transformer decision API (shadow-only)."""
from __future__ import annotations

import json
import ipaddress
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.database import get_db

from app.services.phase6_hybrid import (
    ARTIFACT_VERSION, CONTEXT_ADAPTER_VERSION, MODEL_ID, MODEL_REVISION,
    Phase6Unavailable, ScientificContextError, _artifact_path, _default_model_path,
    artifact_is_compatible, get_runtime,
)
from app.services.decision_head import ACTIONS
from app.db.models import EvidenceChunk, Experiment, Paper, ResearchTopic

router = APIRouter(prefix="/decisions/hybrid", tags=["phase6-hybrid"])


def enforce_research_access(request: Request, *, deployment_mode: str | None = None) -> str:
    """Fail closed for non-loopback local calls and unauthenticated multi-user deployments.

    This checks the ASGI socket peer, not the Host header. Local mode must also
    bind the server to loopback and must not be put behind a public reverse proxy.
    """
    mode = (deployment_mode or os.environ.get("LAB_PROCESS_RAG_DEPLOYMENT_MODE", "LOCAL_SINGLE_USER")).upper()
    if mode == "AUTHENTICATED_MULTI_USER":
        raise HTTPException(status_code=503, detail={"code": "AUTHENTICATION_REQUIRED",
            "message": "Research inference is disabled in multi-user mode until authenticated user and topic authorization are configured."})
    if mode != "LOCAL_SINGLE_USER":
        raise HTTPException(status_code=503, detail={"code": "UNSUPPORTED_DEPLOYMENT_MODE",
            "message": "Research inference is disabled for an unknown deployment mode."})
    peer = request.client.host if request.client else None
    try:
        is_loopback = bool(peer) and ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=403, detail={"code": "LOCAL_ONLY_RESEARCH_API",
            "message": "Research inference accepts direct loopback connections only in LOCAL_SINGLE_USER mode."})
    return "LOCAL_SINGLE_USER_LOOPBACK_PEER"


def resolve_topic_evidence(db: Session, topic_id: int, evidence_ids: list[int]) -> list[dict[str, Any]]:
    """Resolve citations from stored paper chunks scoped to one research topic."""
    if not evidence_ids:
        return []
    rows = (db.query(EvidenceChunk, Paper)
            .join(Paper, EvidenceChunk.paper_id == Paper.id)
            .filter(EvidenceChunk.id.in_(evidence_ids), Paper.topic_id == topic_id)
            .all())
    if {chunk.id for chunk, _paper in rows} != set(evidence_ids):
        raise HTTPException(422, detail={"code": "EVIDENCE_REFERENCE_INVALID",
            "message": "One or more citations are missing or outside the selected research topic."})
    return [{"_server_verified": True, "evidence_status": "RETRIEVED_UNREVIEWED",
        "citation": f"paper:{paper.id}/chunk:{chunk.id}/page:{chunk.page}", "chunk_id": str(chunk.id),
        "provenance": f"{paper.title}; page {chunk.page}; topic {paper.topic_id}", "text": chunk.text}
        for chunk, paper in rows]


class HybridInferIn(BaseModel):
    mode: str = Field(pattern="^(research|sandbox)$")
    scientific_state: dict[str, Any] | None = None
    topic_id: int | None = Field(default=None, gt=0)
    experiment_id: int | None = Field(default=None, gt=0)
    user_request: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[int] = Field(default_factory=list, max_length=32)
    explanation_requested: bool = False
    max_new_tokens: int = Field(default=96, ge=1, le=256)


@router.get("/models")
def models():
    checkpoint_ready = _default_model_path().exists()
    artifact_status = "MISSING"
    try:
        import torch
        if _artifact_path().is_file():
            artifact = torch.load(_artifact_path(), map_location="cpu", weights_only=True)
            expected = {"artifact_version": ARTIFACT_VERSION, "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION, "tokenizer_revision": MODEL_REVISION,
                "context_adapter_version": CONTEXT_ADAPTER_VERSION,
                "action_mapping_version": "decision-actions-v1", "action_mapping": list(ACTIONS)}
            artifact_status = "COMPATIBLE" if artifact_is_compatible(artifact, expected) else "INCOMPATIBLE"
    except ImportError:
        artifact_status = "OPTIONAL_RUNTIME_NOT_INSTALLED" if _artifact_path().is_file() else "MISSING"
    except Exception:
        artifact_status = "INVALID"
    return {"status": "LOCAL_CHECKPOINT_READY" if _default_model_path().exists() else "CHECKPOINT_MISSING",
            "model_id": MODEL_ID, "revision": MODEL_REVISION,
            "checkpoint_path": str(_default_model_path()), "checkpoint_downloaded": checkpoint_ready,
            "decision_head_artifact": str(_artifact_path()), "decision_head_trained": artifact_status == "COMPATIBLE",
            "decision_head_artifact_status": artifact_status, "context_adapter_version": CONTEXT_ADAPTER_VERSION,
            "license": "Apache-2.0", "workflow_triggered": False}


@router.get("/runtime")
def runtime_status():
    deployment_mode = os.environ.get("LAB_PROCESS_RAG_DEPLOYMENT_MODE", "LOCAL_SINGLE_USER").upper()
    access_control = (
        "LOCAL_SINGLE_USER_LOOPBACK_PEER"
        if deployment_mode == "LOCAL_SINGLE_USER"
        else "AUTHENTICATION_REQUIRED"
    )
    try:
        import torch
    except ImportError:
        return {"status": "OPTIONAL_PHASE6_RUNTIME_NOT_INSTALLED", "checkpoint_downloaded": _default_model_path().exists(),
                "decision_head_trained": False, "research_access_control": access_control,
                "deployment_mode": deployment_mode,
                "workflow_triggered": False}
    model_status = models()
    return {"checkpoint_downloaded": _default_model_path().exists(),
            "decision_head_trained": model_status["decision_head_trained"],
            "decision_head_artifact_status": model_status["decision_head_artifact_status"],
            "mps_available": bool(torch.backends.mps.is_available()),
            "cuda_available": bool(torch.cuda.is_available()),
            "artifact_path": str(_artifact_path()), "research_access_control": access_control,
            "deployment_mode": deployment_mode,
            "workflow_triggered": False}


@router.post("/infer")
def infer(payload: HybridInferIn, request: Request, db: Session = Depends(get_db)):
    try:
        if payload.mode == "research":
            access_mode = enforce_research_access(request)
            if payload.scientific_state is not None:
                raise HTTPException(422, detail={"code": "CLIENT_STATE_NOT_TRUSTED", "message": "Research mode builds ScientificState from server records; client state is not accepted."})
            if payload.topic_id is None or payload.experiment_id is None:
                raise HTTPException(422, detail={"code": "RESEARCH_RECORD_REQUIRED", "message": "Research mode requires a topic and recorded experiment."})
            topic = db.get(ResearchTopic, payload.topic_id)
            experiment = db.get(Experiment, payload.experiment_id)
            if not topic or not experiment or experiment.topic_id != topic.id or experiment.demo:
                raise HTTPException(422, detail={"code": "UNVERIFIED_RESEARCH_PROVENANCE", "message": "Research inference requires a non-demo experiment belonging to the selected topic."})
            from app.api.decisions import _stage3_experiment_state
            state = _stage3_experiment_state(db, topic.id, experiment.id)
            provenance = state.get("provenance", {}) if isinstance(state, dict) else {}
            if not isinstance(provenance, dict) or provenance.get("validity") != "VALID" or provenance.get("data_quality_gate") != "PASS":
                raise HTTPException(422, detail={"code": "RESEARCH_STATE_NOT_VERIFIED",
                    "message": "The stored experiment does not meet the source and data-quality gate for Research inference."})
        else:
            if payload.experiment_id is not None or payload.topic_id is not None:
                raise HTTPException(422, detail={"code": "SANDBOX_RESEARCH_REFERENCE_CONFLICT", "message": "Sandbox mode accepts only an explicitly unverified state and cannot reference research records."})
            if payload.scientific_state is None:
                raise HTTPException(422, detail="Sandbox mode requires a ScientificState V2.")
            state = dict(payload.scientific_state)
            # Never let client-supplied provenance be promoted in the sandbox.
            state["provenance"] = {"validity": "UNKNOWN", "data_quality_gate": "UNKNOWN"}
            state.pop("source_provenance", None)

        # Look up every citation from the database and scope it to the chosen
        # research topic. Inline text and self-reported SUPPORTED flags are not accepted.
        verified_evidence = []
        if payload.evidence_ids:
            if payload.mode != "research":
                raise HTTPException(422, detail={"code": "SANDBOX_EVIDENCE_NOT_VERIFIED", "message": "Sandbox evidence references cannot be used as research citations."})
            verified_evidence = resolve_topic_evidence(db, payload.topic_id, payload.evidence_ids)
        result = get_runtime().infer(state, payload.user_request,
                                   evidence=verified_evidence,
                                   explanation_requested=payload.explanation_requested,
                                   max_new_tokens=payload.max_new_tokens, mode=payload.mode)
        if payload.mode == "research":
            result["research_access_control"] = access_mode
        return result
    except ScientificContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Phase6Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Install backend/requirements-phase6.txt to enable the optional local Transformer runtime.") from exc


@router.post("/explain")
def explain(payload: HybridInferIn, request: Request, db: Session = Depends(get_db)):
    return infer(payload.model_copy(update={"explanation_requested": True}), request, db)


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
