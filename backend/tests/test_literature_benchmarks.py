from fastapi.testclient import TestClient

from app.main import app


def test_benchmark_catalog_keeps_process_families_separate():
    with TestClient(app) as client:
        response = client.get("/api/research/benchmarks")
        assert response.status_code == 200
        datasets = response.json()
        assert len(datasets) == 7
        assert sum(item["run_count"] for item in datasets) == 125
        by_id = {item["dataset_id"]: item for item in datasets}
        assert by_id["water_hyacinth_htl_uncatalyzed_ccd_2023"]["run_count"] == 13
        assert by_id["water_hyacinth_htl_ccd_2023"]["run_count"] == 20
        assert by_id["water_hyacinth_htl_uncatalyzed_ccd_2023"]["dataset_id"] != by_id["water_hyacinth_htl_ccd_2023"]["dataset_id"]


def test_benchmark_run_data_and_observed_summary():
    with TestClient(app) as client:
        records = client.get("/api/research/benchmarks/pmma_mex_taguchi_l25_2023").json()
        assert len(records) == 25
        assert records[0]["factors"]["infill_density_percent"] == 80
        assert records[0]["outcomes"]["tensile_strength_MPa"]["n"] == 5

        summary_response = client.get("/api/research/benchmarks/pmma_mex_taguchi_l25_2023/summary?outcome_key=tensile_strength_MPa&objective=maximize")
        assert summary_response.status_code == 200
        summary = summary_response.json()
        strength = summary["outcomes"]["tensile_strength_MPa"]
        assert strength["max"] == 44.23
        assert strength["best_observed_runs"][0]["run_id"] == "12"
        assert "not a success probability" in summary["notice"]


def test_benchmark_summary_rejects_unknown_objective():
    with TestClient(app) as client:
        response = client.get("/api/research/benchmarks/cu_fe_o2_bbd_2026/summary?outcome_key=photocurrent_density_at_0.4V_vs_RHE_mA_cm2&objective=guess")
        assert response.status_code == 422
