"""Run isolated Phase 6 integrity checks with the real local checkpoint.

The temporary SQLite data is synthetic software-test fixture data, never lab
evidence. The script validates the actual API → DB provenance/evidence gates →
Qwen decision → conditional LM generation path without touching the project DB.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import EvidenceChunk, Experiment, Paper, ResearchTopic, ScientificObservation
from app.services.phase6_hybrid import (CONTEXT_ADAPTER_VERSION, MODEL_ID, MODEL_REVISION,
    Phase6HybridRuntime, _artifact_path, _default_model_path)
import app.api.hybrid_decisions as hybrid_api


def main():
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="lab-process-phase6-integrity-") as temporary:
        engine = create_engine(f"sqlite:///{Path(temporary) / 'isolated-test.sqlite'}")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        topic = ResearchTopic(name="isolated-phase6-integrity-fixture")
        db.add(topic)
        db.flush()
        experiment = Experiment(code="P6-FIXTURE-001", name="software integration fixture", target="software-test",
            status="COMPLETE", demo=False, topic_id=topic.id)
        db.add(experiment)
        db.flush()
        observation = ScientificObservation(topic_id=topic.id, experiment_id=experiment.id,
            parameter_id="fixture_temperature", original_value="25", original_unit="degC",
            normalized_value=25.0, normalized_unit="degC", value_type="numeric", source_type="LAB_RECORD",
            source_id=f"experiment:{experiment.id}:fixture", review_status="ACCEPTED")
        paper = Paper(title="Synthetic software-test source; not a scientific reference", filename="fixture.pdf", topic_id=topic.id)
        db.add_all([observation, paper])
        db.flush()
        chunk = EvidenceChunk(paper_id=paper.id, page=1, section="Test fixture",
            text="This artificial passage exists only to verify citation wiring. It makes no scientific claim.", chunk_index=0)
        db.add(chunk)
        db.commit()

        runtime = Phase6HybridRuntime(_default_model_path(), _artifact_path(), device="mps" if torch.backends.mps.is_available() else "cpu")
        hybrid_api.get_runtime = lambda: runtime
        result = hybrid_api.infer(hybrid_api.HybridInferIn(mode="research", topic_id=topic.id,
            experiment_id=experiment.id, evidence_ids=[chunk.id], user_request="Explain the model's decision from this test source.",
            explanation_requested=True, max_new_tokens=160), db)
        assert result["input_mode"] == "RESEARCH"
        assert result["workflow_triggered"] is False
        assert result["generated_token_count"] > 0, "conditional explanation path must call the actual language model"
        assert result["kv_cache_bytes"] > 0
        assert result["cache_reuse_status"].startswith("GENERATED_") or result["cache_reuse_status"].startswith("GENERATION_REJECTED_")
        report = {
            "status": "PASS_SOFTWARE_INTEGRATION_ONLY",
            "scope": "SYNTHETIC_FIXTURE_NOT_LAB_OR_SCIENTIFIC_VALIDATION",
            "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
            "context_adapter_version": CONTEXT_ADAPTER_VERSION,
            "actual_checkpoint_loaded": True,
            "api_path": "Research API → DB-built ScientificState → topic-scoped DB EvidenceChunk → decision head → locked explanation prompt → actual LM generation",
            "source_state": result["provenance"],
            "raw_action": result["raw_predicted_action"],
            "final_safe_action": result["final_safe_action"],
            "generation_tokens": result["generated_token_count"],
            "generation_status": result["cache_reuse_status"],
            "generation_validation_status": result["generation_validation_status"],
            "generated_output_accepted": result["generated_output_accepted"],
            "explanation_evidence_count": result["explanation_evidence_count"],
            "citation_validation": "accepted only when structured output echoes the locked action and exact DB-resolved citation; otherwise safe fallback",
            "cache_bytes": result["kv_cache_bytes"],
            "workflow_triggered": result["workflow_triggered"],
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "access_control_limitation": result["research_access_control"],
            "limitations": ["All database rows and PDF excerpt in this isolated test are fabricated test fixtures.",
                "No scientific content validity or real laboratory decision accuracy is established.",
                "The application currently has topic scoping but no authenticated user identity/authorization layer."],
        }
        db.close()
        engine.dispose()
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "phase6_generation_validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
