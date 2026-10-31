"""Run a reproducible synthetic end-to-end Phase 5 Stage 2 learning cycle."""
from __future__ import annotations

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import ResearchTopic
from app.main import app
from app.services.decision_head import ACTIONS


def run_cycle() -> dict:
    start = time.perf_counter()
    with TemporaryDirectory(prefix="phase5-stage2-") as temp_dir:
        engine = create_engine(f"sqlite:///{temp_dir}/stage2.db", connect_args={"check_same_thread": False})
        sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(bind=engine)

        def test_db():
            db = sessions()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = test_db
        try:
            db = sessions()
            topic = ResearchTopic(name="Phase 5 Stage 2 synthetic benchmark", description="Synthetic software fixture only")
            db.add(topic)
            db.commit()
            topic_id = topic.id
            db.close()

            with TestClient(app) as client:
                def post(path: str, body: dict | None = None):
                    response = client.post(path, json=body) if body is not None else client.post(path)
                    response.raise_for_status()
                    return response.json()

                seed = client.post(f"/api/decisions/learned/sandbox/seed?topic_id={topic_id}&seed=2026")
                seed.raise_for_status()
                dataset_v1 = post("/api/decisions/learned/datasets/build", {"topic_id": topic_id, "mode": "sandbox"})
                model_v1 = post("/api/decisions/learned/retrain", {"dataset_version_id": dataset_v1["dataset_version_id"], "seed": 2026})
                model_v1_clone = post("/api/decisions/learned/retrain", {
                    "dataset_version_id": dataset_v1["dataset_version_id"],
                    "parent_model_id": model_v1["model_id"], "seed": 2026,
                })
                baseline_comparison = post("/api/decisions/learned/models/compare", {
                    "topic_id": topic_id, "champion_model_id": model_v1["model_id"],
                    "challenger_model_id": model_v1_clone["model_id"],
                })
                activate_initial = post("/api/decisions/learned/activate", {
                    "topic_id": topic_id, "model_id": model_v1["model_id"],
                    "reviewer": "Synthetic benchmark operator", "reason": "Initial evaluated shadow model",
                })
                activate_clone = post("/api/decisions/learned/activate", {
                    "topic_id": topic_id, "model_id": model_v1_clone["model_id"],
                    "comparison_id": baseline_comparison["comparison_id"],
                    "reviewer": "Synthetic benchmark operator", "reason": "Same-version reproducibility check",
                })
                rollback = post("/api/decisions/learned/rollback", {
                    "topic_id": topic_id, "mode": "sandbox", "reviewer": "Synthetic benchmark operator",
                    "reason": "Verify reversible shadow selection",
                })

                case = client.get(f"/api/decisions/learned/cases?topic_id={topic_id}&mode=sandbox").json()[0]
                decision = post("/api/decisions/learned/compare", {
                    "topic_id": topic_id, "model_id": model_v1_clone["model_id"], "case_id": case["case_id"],
                })
                snapshot = decision["decision_snapshot"]
                corrected_action = next(action for action in ACTIONS if action != snapshot["suggested_action"])
                feedback = post("/api/decisions/learned/feedback", {
                    "snapshot_id": snapshot["snapshot_id"], "model_id": model_v1_clone["model_id"],
                    "feedback_type": "CORRECT", "final_reviewed_action": corrected_action,
                    "reviewer": "Synthetic benchmark reviewer", "review_reason": "Synthetic lifecycle verification",
                })
                dataset_v2 = post("/api/decisions/learned/datasets/build", {"topic_id": topic_id, "mode": "sandbox"})
                model_v2 = post("/api/decisions/learned/retrain", {
                    "dataset_version_id": dataset_v2["dataset_version_id"],
                    "parent_model_id": model_v1_clone["model_id"], "seed": 2027,
                })
                v2_comparison = post("/api/decisions/learned/models/compare", {
                    "topic_id": topic_id, "champion_model_id": model_v1["model_id"],
                    "challenger_model_id": model_v2["model_id"],
                })
                active_after_v2_review = client.get(f"/api/decisions/learned/active?topic_id={topic_id}&mode=sandbox").json()["model"]["model_id"]

                if dataset_v1["evaluation_hash"] != dataset_v2["evaluation_hash"]:
                    raise AssertionError("The frozen evaluation set changed between dataset versions")
                if feedback["label_eligible"] is not True:
                    raise AssertionError("The explicit synthetic correction was not included as an eligible fixture label")
                if activate_clone["active_model_id"] != model_v1_clone["model_id"] or rollback["active_model_id"] != model_v1["model_id"]:
                    raise AssertionError("Shadow activation/rollback lifecycle did not restore the expected model")
                if active_after_v2_review != model_v1["model_id"]:
                    raise AssertionError("Training/comparison must not promote the V2 challenger automatically")

                return {
                    "status": "PASSED",
                    "dataset_v1": {"version": dataset_v1["dataset_version"], "hash": dataset_v1["dataset_hash"], "case_count": dataset_v1["case_count"]},
                    "dataset_v2": {"version": dataset_v2["dataset_version"], "hash": dataset_v2["dataset_hash"], "case_count": dataset_v2["case_count"]},
                    "model_ids": {"v1_champion": model_v1["model_id"], "v1_reproducibility_clone": model_v1_clone["model_id"], "v2_challenger": model_v2["model_id"]},
                    "feature_schema_version": model_v2["feature_schema_version"],
                    "group_split_summary": {key: model_v2["provenance"][key] for key in ("group_split", "training_case_ids", "calibration_case_ids", "evaluation_case_ids", "evaluation_group_ids")},
                    "evaluation_set_hash": dataset_v1["evaluation_hash"],
                    "evaluation_hash_frozen_across_versions": dataset_v1["evaluation_hash"] == dataset_v2["evaluation_hash"],
                    "champion_metrics": model_v1["metrics"], "challenger_metrics": model_v2["metrics"],
                    "same_version_comparison": {"status": baseline_comparison["status"], "report": baseline_comparison["report"]},
                    "v1_vs_v2_comparison": {"status": v2_comparison["status"], "report": v2_comparison["report"]},
                    "feedback": {key: feedback[key] for key in ("feedback_id", "feedback_type", "final_reviewed_action", "label_eligible", "review_status")},
                    "promotion_rollback": {"initial_model_id": activate_initial["active_model_id"], "activated_model_id": activate_clone["active_model_id"], "rollback_model_id": rollback["active_model_id"], "v2_promoted_automatically": False},
                    "workflow_triggered": False,
                    "runtime_seconds": round(time.perf_counter() - start, 4),
                    "limitations": ["Synthetic software fixture only; not evidence of laboratory decision accuracy.", "No automated retraining, promotion, workflow execution, or instrument control."],
                }
        finally:
            app.dependency_overrides.clear()
            engine.dispose()


if __name__ == "__main__":
    report = run_cycle()
    output = Path(__file__).resolve().parents[1] / "reports" / "phase5_stage2_learning_cycle.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "dataset_v1_hash": report["dataset_v1"]["hash"],
        "dataset_v2_hash": report["dataset_v2"]["hash"], "v2_comparison": report["v1_vs_v2_comparison"]["status"],
        "runtime_seconds": report["runtime_seconds"], "report": str(output)}, ensure_ascii=False, indent=2))
