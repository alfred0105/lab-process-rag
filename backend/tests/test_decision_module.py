from types import SimpleNamespace

import pytest

from app.api.routes import _validated_decision_options
from app.schemas.core import DecisionOption
from app.services.llm import AISettings, LLMUnavailable, OllamaProvider


def make_option(basis, *, evidence_ids=None, experiment_refs=None):
    return DecisionOption(
        title="Next check", change="Run a controlled repeat", basis=basis,
        rationale="This isolates one uncertainty", evidence_ids=evidence_ids or [],
        experiment_refs=experiment_refs or [], measure_next="Record the same outcome metric",
        risk="Does not establish a cause by itself", confidence="low",
    )


def test_demo_records_only_allow_data_gap_options():
    demo = SimpleNamespace(id=4, demo=True)
    accepted, rejected = _validated_decision_options(
        [make_option("LAB_PATTERN", experiment_refs=[4]), make_option("DATA_GAP")],
        set(), {4}, [demo],
    )
    assert rejected
    assert [item.basis for item in accepted] == ["DATA_GAP"]


def test_real_record_and_paper_options_require_supplied_source_ids():
    real = SimpleNamespace(id=8, demo=False, status="success")
    accepted, rejected = _validated_decision_options(
        [make_option("LAB_PATTERN", experiment_refs=[8]), make_option("PAPER_EVIDENCE", evidence_ids=[7]),
         make_option("PAPER_EVIDENCE", evidence_ids=[99])],
        {7}, {8}, [real],
    )
    assert rejected
    assert [item.basis for item in accepted] == ["LAB_PATTERN", "PAPER_EVIDENCE"]


def test_literature_reference_records_cannot_become_lab_pattern_evidence():
    literature = SimpleNamespace(id=12, demo=False, status="reference")
    accepted, rejected = _validated_decision_options(
        [make_option("LAB_PATTERN", experiment_refs=[12]), make_option("DATA_GAP")],
        set(), {12}, [literature],
    )
    assert rejected
    assert [item.basis for item in accepted] == ["DATA_GAP"]


def test_ollama_choice_uses_only_declared_candidate_tokens(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"logprobs": [{"top_logprobs": [{"token": "A", "logprob": -0.2}, {"token": "B", "logprob": -1.1}]}]}

    monkeypatch.setattr("app.services.llm.httpx.post", lambda *args, **kwargs: Response())
    provider = OllamaProvider(AISettings(provider="ollama", ollama_model="test-model"))
    result = provider.decide_choice({"observations": ["limited test state"]}, "Choose a safe next check", [
        {"id": "measure", "label": "Measure again"}, {"id": "change", "label": "Change condition"},
    ])
    assert result["selected_option_id"] == "measure"
    assert set(result["probabilities"]) == {"measure", "change"}
    assert sum(result["probabilities"].values()) == pytest.approx(1)
    assert result["calibration_status"] == "uncalibrated_raw_token_scores"


def test_ollama_choice_abstains_when_any_candidate_score_is_missing(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"logprobs": [{"top_logprobs": [{"token": "A", "logprob": -0.2}]}]}

    monkeypatch.setattr("app.services.llm.httpx.post", lambda *args, **kwargs: Response())
    provider = OllamaProvider(AISettings(provider="ollama", ollama_model="test-model"))
    with pytest.raises(LLMUnavailable, match="omitted"):
        provider.decide_choice("state", "Choose an option", [
            {"id": "a", "label": "A"}, {"id": "b", "label": "B"},
        ])
