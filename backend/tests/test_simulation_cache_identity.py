from app.services.simulation import cache


def test_cache_identity_scopes_topic_experiment_step_and_tool_versions(monkeypatch):
    monkeypatch.setattr(cache, "_database_provenance", lambda: {"database": "phreeqc.dat", "sha256": "a" * 64})
    common = dict(tool_id="phreeqc.aqueous_equilibrium.v1", tool_version="1", topic_id=1,
                  experiment_id=2, process_step_id=3, parameters={"pH": 7.0, "temperature_c": 25.0})
    original, payload = cache.phreeqc_cache_identity(**common)
    assert payload["model"]["sha256"] == "a" * 64
    assert cache.phreeqc_cache_identity(**common)[0] == original
    assert cache.phreeqc_cache_identity(**{**common, "topic_id": 9})[0] != original
    assert cache.phreeqc_cache_identity(**{**common, "experiment_id": 8})[0] != original
    assert cache.phreeqc_cache_identity(**{**common, "process_step_id": 4})[0] != original
    assert cache.phreeqc_cache_identity(**{**common, "tool_version": "2"})[0] != original
    monkeypatch.setattr(cache, "_database_provenance", lambda: {"database": "phreeqc.dat", "sha256": "b" * 64})
    assert cache.phreeqc_cache_identity(**common)[0] != original
