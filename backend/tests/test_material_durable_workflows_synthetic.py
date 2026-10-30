"""Isolated synthetic end-to-end material workflows (never lab/optimizer data)."""
from __future__ import annotations

import hashlib
import io
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import (Experiment, MaterialAnalysisRun, ResearchTopic,
                           ScientificObservation, WorkflowNode, WorkflowRun)
from app import worker


def _isolated(tmp_path, monkeypatch, modality: str, filename: str, content: bytes, settings: dict):
    root = tmp_path / "isolated-worktree"
    source_path = root / "data" / "material-analysis" / "originals" / filename
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(content)
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic-only.db'}",
                           connect_args={"check_same_thread": False, "timeout": 20})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "ROOT", root)
    monkeypatch.setattr(worker, "DATA_ROOT", root / "data")
    db = sessions()
    topic = ResearchTopic(name=f"synthetic-{modality}", description="isolated test only")
    db.add(topic); db.flush()
    experiment = Experiment(code=f"SYN-{modality}", name="Synthetic fixture", target="software validation",
                           status="planned", topic_id=topic.id, demo=False)
    db.add(experiment); db.flush()
    run = MaterialAnalysisRun(topic_id=topic.id, experiment_id=experiment.id, modality=modality,
        tool_id=f"{modality}.pending", filename=filename, sha256=hashlib.sha256(content).hexdigest(),
        original_path=str(source_path), result_json={"demo_data": True, "provenance": {"parameters": settings}},
        analysis_status="pending")
    db.add(run); db.flush()
    flow = WorkflowRun(topic_id=topic.id, experiment_id=experiment.id, goal=f"synthetic {modality} worker validation",
                       status="QUEUED", graph_json={}, created_at=datetime.utcnow())
    db.add(flow); db.flush()
    node = WorkflowNode(workflow_id=flow.id, node_key="analyze", tool_id=("afm.plane_level_roughness.v1" if modality == "afm" else "microscopy.otsu_components.v1"),
        dependency_keys=[], input_json={"analysis_run_id": run.id, "settings": settings}, created_at=datetime.utcnow())
    db.add(node); db.commit()
    ids = (topic.id, experiment.id, run.id, flow.id, node.id)
    db.close()
    return engine, sessions, ids, source_path


def _synthetic_sem_image() -> tuple[bytes, np.ndarray]:
    image = np.full((64, 80), 12, dtype=np.uint8)
    truth = np.zeros_like(image, dtype=bool)
    truth[8:24, 10:30] = True
    truth[34:55, 46:71] = True
    image[truth] = 240
    buffer = io.BytesIO(); Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue(), truth


def _synthetic_afm_grid() -> tuple[bytes, tuple[float, float, float]]:
    y, x = np.indices((32, 37), dtype=float)
    # Known tilted plane plus a single calibrated height impulse.
    surface = 0.4 * x - 0.2 * y + 7.0
    surface[16, 18] += 2.5
    content = "\n".join(",".join(f"{v:.12g}" for v in row) for row in surface).encode()
    # Independent least-squares calculation of reference Sa/Sq/Sz.
    design = np.column_stack((x.ravel(), y.ravel(), np.ones(surface.size)))
    plane, *_ = np.linalg.lstsq(design, surface.ravel(), rcond=None)
    leveled = surface - (plane[0] * x + plane[1] * y + plane[2])
    centered = leveled - leveled.mean()
    expected = (float(np.abs(centered).mean()), float(np.sqrt(np.mean(centered ** 2))),
                float(leveled.max() - leveled.min()))
    return content, expected


@pytest.mark.parametrize("modality", ["sem", "tem"])
def test_sem_tem_synthetic_durable_worker_persists_mask_and_keeps_synthetic_lineage(tmp_path, monkeypatch, modality):
    content, truth = _synthetic_sem_image()
    engine, sessions, (_topic_id, _experiment_id, run_id, flow_id, node_id), source_path = _isolated(
        tmp_path, monkeypatch, modality, f"known-{modality}.png", content, {"pixel_size_nm": 2.0, "foreground": "bright"})
    try:
        assert worker.run_once(f"synthetic-{modality}-worker") is True
        db = sessions()
        run, node, flow = db.get(MaterialAnalysisRun, run_id), db.get(WorkflowNode, node_id), db.get(WorkflowRun, flow_id)
        assert flow.status == "COMPLETED" and node.status == "COMPLETED"
        assert run.analysis_status == "completed" and run.sha256 == hashlib.sha256(content).hexdigest()
        assert source_path.read_bytes() == content
        assert run.result_json["analysis_provenance"]["source_type"] == "SYNTHETIC_DEMO"
        assert run.result_json["demo_data"] is True
        assert run.artifact_path and __import__("pathlib").Path(run.artifact_path).is_file()
        with Image.open(run.artifact_path) as mask_image:
            observed = np.asarray(mask_image) > 0
        intersection = np.logical_and(truth, observed).sum()
        union = np.logical_or(truth, observed).sum()
        assert intersection / union == pytest.approx(1.0)
        observations = db.query(ScientificObservation).filter_by(analysis_run_id=run.id).all()
        assert observations
        assert all(item.source_type == "SYNTHETIC_DEMO" and item.review_status == "COMPUTED" for item in observations)
        assert run.result_json["analysis_provenance"]["original_sha256"] == run.sha256
        assert "not a trained SEM/TEM model" in run.result_json["interpretation_limit"]
        db.close()
    finally:
        engine.dispose()


def test_afm_synthetic_durable_worker_matches_independent_plane_fit(tmp_path, monkeypatch):
    content, expected = _synthetic_afm_grid()
    engine, sessions, (_topic_id, _experiment_id, run_id, flow_id, node_id), source_path = _isolated(
        tmp_path, monkeypatch, "afm", "known-height-grid.csv", content, {"afm_height_unit": "um"})
    try:
        assert worker.run_once("synthetic-afm-worker") is True
        db = sessions()
        run, node, flow = db.get(MaterialAnalysisRun, run_id), db.get(WorkflowNode, node_id), db.get(WorkflowRun, flow_id)
        assert flow.status == "COMPLETED" and node.status == "COMPLETED"
        assert run.analysis_status == "completed" and run.result_json["height_unit"] == "um"
        assert run.result_json["Sa"] == pytest.approx(expected[0], abs=1e-9)
        assert run.result_json["Sq"] == pytest.approx(expected[1], abs=1e-9)
        assert run.result_json["Sz"] == pytest.approx(expected[2], abs=1e-9)
        assert run.result_json["analysis_provenance"]["source_type"] == "SYNTHETIC_DEMO"
        assert run.sha256 == hashlib.sha256(source_path.read_bytes()).hexdigest()
        observations = db.query(ScientificObservation).filter_by(analysis_run_id=run.id).all()
        assert all(item.source_type == "SYNTHETIC_DEMO" for item in observations)
        assert any(item.parameter_id.endswith("_sa") for item in observations)
        db.close()
    finally:
        engine.dispose()


@pytest.mark.parametrize("modality,settings", [
    ("xrd", {}), ("afm", {}), ("sem", {}), ("tem", {"pixel_size_nm": 0.0}),
])
def test_durable_analysis_api_rejects_missing_or_invalid_calibration(tmp_path, monkeypatch, modality, settings):
    from fastapi.testclient import TestClient
    from app.db.database import get_db
    from app.main import app

    content = b"10 1\n11 3\n12 1\n13 0\n14 1\n" if modality == "xrd" else b"unused"
    engine, sessions, (topic_id, experiment_id, run_id, _flow_id, _node_id), _ = _isolated(
        tmp_path, monkeypatch, modality, "pending.dat" if modality in {"xrd", "afm"} else "pending.png", content, settings)
    # Keep this test focused on enqueue-time calibration gates, with the source
    # classified as a real upload so the calibration check is reached.
    db = sessions(); run = db.get(MaterialAnalysisRun, run_id); run.result_json = {"provenance": {"parameters": settings}}; db.commit(); db.close()
    def get_test_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = get_test_db
    try:
        with TestClient(app) as client:
            # Existing helper node is local DB state only; request a second plan with no declared settings.
            response = client.post("/api/workflows", json={"topic_id": topic_id, "experiment_id": experiment_id,
                "goal": f"analyze {modality}", "nodes": [{"key": "analysis",
                    "tool_id": "xrd.local_peaks.v1" if modality == "xrd" else "afm.plane_level_roughness.v1" if modality == "afm" else "microscopy.otsu_components.v1",
                    "inputs": {"analysis_run_id": run_id, "settings": settings}}]})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_synthetic_workflow_test_mode_requires_explicit_flag_and_temp_database(tmp_path, monkeypatch):
    from app.api.workflows import _isolated_synthetic_test_mode
    isolated_db = tmp_path / "isolated.sqlite"
    monkeypatch.setenv("LAB_PROCESS_DB_PATH", str(isolated_db))
    monkeypatch.delenv("LAB_PROCESS_TESTING", raising=False)
    assert not _isolated_synthetic_test_mode()
    monkeypatch.setenv("LAB_PROCESS_TESTING", "1")
    assert _isolated_synthetic_test_mode()
    monkeypatch.setenv("LAB_PROCESS_DB_PATH", str(Path(__file__).resolve().parents[1] / "data" / "operating.sqlite"))
    assert not _isolated_synthetic_test_mode()
