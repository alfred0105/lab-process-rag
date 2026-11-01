import json

import pytest

from app.services.phase6_hybrid import (
    ScientificContextError, build_scientific_prompt,
)
from app.services.scientific_state_v2 import SCIENTIFIC_STATE_SCHEMA_VERSION


def valid_state():
    return {"schema_version": SCIENTIFIC_STATE_SCHEMA_VERSION,
            "experiment": {"name": "sample", "experiment_id": 88, "outcome": "success"},
            "process_conditions": {"temperature": {"value": 90, "unit": "C"}},
            "measurements": {"accepted_observation_count": 1},
            "analysis": {}, "simulation": {}, "optimization": {},
            "provenance": {"validity": "VALID", "data_quality_gate": "PASS"},
            "pending_reviews": {}, "source_timestamp": "2026-10-31T12:00:00Z",
            "source_provenance": {"observation_ids": [4]}}


def test_prompt_adapter_removes_outcome_and_identity_shortcuts():
    prompt, metadata = build_scientific_prompt(valid_state(), "다음 작업을 알려줘")
    assert "experiment_id" not in prompt
    assert "success" not in prompt
    assert "observation_ids" not in prompt
    assert "90" in prompt
    assert metadata["provenance_valid"] is True
    assert metadata["source_records_retained_for_audit"] == 1


def test_prompt_adapter_only_passes_supported_cited_evidence():
    evidence = [
        {"evidence_status": "SUPPORTED", "citation": "paper:1", "chunk_id": "c1", "text": "Supported text"},
        {"evidence_status": "INFERRED", "citation": "paper:2", "text": "Inference"},
        {"evidence_status": "SUPPORTED", "text": "No citation"},
    ]
    prompt, metadata = build_scientific_prompt(valid_state(), "explain", evidence)
    decoded = json.loads(prompt)
    assert [item["citation"] for item in decoded["Validated Literature Evidence"]] == ["paper:1"]
    assert metadata["validated_evidence_count"] == 1
    assert metadata["evidence_warnings"]


@pytest.mark.parametrize("state,user_input", [
    ({}, "request"),
    ({"schema_version": "future-v3"}, "request"),
    (valid_state(), ""),
    (valid_state(), "x" * 4001),
])
def test_prompt_adapter_fails_closed_on_unsupported_or_invalid_input(state, user_input):
    with pytest.raises(ScientificContextError):
        build_scientific_prompt(state, user_input)


def test_invalid_provenance_blocks_model_context():
    state = valid_state()
    state["provenance"]["validity"] = "INVALID"
    _, metadata = build_scientific_prompt(state, "request")
    assert metadata["provenance_valid"] is False
