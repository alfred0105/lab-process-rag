from app.services.campaign_decision_runtime import adapt_campaign_state, run_learned_decision


def _state(mode="SANDBOX"):
    return {"campaign_id": 9, "topic_id": 3, "experiment_id": None, "mode": mode,
        "goal": "optimize the benchmark objective", "target_property": "branin",
        "accepted_observation_count": 6, "pending_review_count": 0,
        "optimization_ready": True, "provenance_valid": 1.0,
        "workflow_state": 1, "validation_status": 1,
        "quality_result": {"issue_count": 0}, "method_version_id": None}


class FakeRuntime:
    def __init__(self, output=None, error=None):
        self.output, self.error = output, error

    def decide(self, state, *, mode):
        assert state["schema_version"] == "scientific-state-v2"
        assert mode in {"sandbox", "research"}
        if self.error:
            raise self.error
        return self.output

    def get_available_actions(self):
        return ["ANALYZE", "OPTIMIZE"]

    def get_decision_metadata(self):
        return {"model_version": "test-model-v1", "artifact_available": True}


def test_campaign_state_adapter_preserves_unknowns_instead_of_inventing_measurements():
    state = adapt_campaign_state(_state())
    assert state["schema_version"] == "scientific-state-v2"
    assert state["measurements"]["quality_status"] == "UNKNOWN"
    assert state["process_conditions"]["items"] == []
    assert state["provenance"]["validity"] == "UNKNOWN"


def test_jev_shadow_records_model_prediction_but_does_not_route_it():
    runtime = FakeRuntime({"raw_predicted_action": "ANALYZE", "final_safe_action": "ANALYZE",
        "confidence": 0.8, "ood_status": "IN_DISTRIBUTION_BY_CALIBRATION_THRESHOLD",
        "backbone_version": "fixture", "decision_head_version": "fixture-head"})
    result = run_learned_decision(_state(), mode="JEV_SHADOW", campaign_mode="SANDBOX", runtime=runtime)
    assert result["decision_source"] == "JEV_SHADOW"
    assert result["raw_predicted_action"] == "ANALYZE"
    assert result["final_safe_action"] is None


def test_jev_ood_falls_back_to_rule_policy_and_never_claims_jev_action():
    runtime = FakeRuntime({"raw_predicted_action": "OPTIMIZE", "final_safe_action": "ABSTAIN",
        "confidence": 0.7, "ood_status": "POTENTIAL_OOD", "backbone_version": "fixture",
        "decision_head_version": "fixture-head"})
    result = run_learned_decision(_state(), mode="JEV_SANDBOX", campaign_mode="SANDBOX", runtime=runtime)
    assert result["decision_source"] == "RULE_BASED_FALLBACK"
    assert result["raw_predicted_action"] == "OPTIMIZE"
    assert result["final_safe_action"] is None
    assert result["fallback_reason"] == "OOD_OR_UNSUPPORTED_STATE"


def test_runtime_exception_falls_back_explicitly():
    result = run_learned_decision(_state(), mode="JEV_SANDBOX", campaign_mode="SANDBOX",
        runtime=FakeRuntime(error=RuntimeError("fixture failure")))
    assert result["decision_source"] == "RULE_BASED_FALLBACK"
    assert result["runtime_status"] == "FALLBACK"
    assert "fixture failure" in result["fallback_reason"]


def test_jev_sandbox_mode_is_not_accepted_for_research_campaign():
    result = run_learned_decision(_state("RESEARCH"), mode="JEV_SANDBOX", campaign_mode="RESEARCH", runtime=FakeRuntime())
    assert result["decision_source"] == "RULE_BASED_FALLBACK"
    assert result["fallback_reason"] == "RESEARCH_MODE_REQUIRES_RULE_POLICY"
