import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Experiment, ExperimentMethod, MethodVersion, ProcessStep, ResearchTopic, ScientificObservation
from app.main import app
from app.services.optimization.gpbo import GaussianProcess, OptimizationInputError
from app.services.optimization.multiobjective import greedy_batch, hypervolume_2d, mc_hvi, pareto_front, run_moo_benchmarks, zdt1


def test_pareto_mixed_directions_duplicates_and_feasibility():
    values = [[1, 8], [2, 7], [3, 6], [4, 9], [1, 8], [0, 100]]
    result = pareto_front(values, ["minimize", "maximize"], ids=list("abcdef"), feasible=[1, 1, 1, 1, 1, 0])
    assert result["ids"] == ["a", "d"]
    assert result["rank"] == [0, 1, 2, 0, 0, -1]
    assert result["duplicate_front_ids"]["a"] == ["a", "e"]
    assert pareto_front([[1, 1], [1, 1]])["indices"] == [0]
    with pytest.raises(OptimizationInputError): pareto_front([[1, np.nan]])


def test_exact_hypervolume_reference_scaling_and_direction():
    front = [[1, 3], [2, 2], [3, 1], [4, 4]]
    assert hypervolume_2d(front, [4, 4]) == pytest.approx(6.0)
    assert hypervolume_2d(front + [[1, 3]], [4, 4]) == pytest.approx(6.0)
    assert hypervolume_2d(front[:3], [4, 4], scale=[2, 2]) == pytest.approx(1.5)
    assert hypervolume_2d([[4, 1], [3, 2]], [1, 3], ["maximize", "minimize"]) == pytest.approx(6.0)
    assert hypervolume_2d([], [4, 4]) == 0
    with pytest.raises(OptimizationInputError, match="Reference point"):
        hypervolume_2d([[1, 5]], [4, 4])
    with pytest.raises(OptimizationInputError): hypervolume_2d([[1, 1]], [2, 2], scale=[1, 0])


def test_mc_hvi_and_joint_greedy_batch_are_seeded_and_use_uncertainty():
    x = np.linspace(0, 1, 12)[:, None]
    y1 = (x[:, 0] - .25) ** 2
    y2 = (x[:, 0] - .8) ** 2
    models = [GaussianProcess.fit(x, y1), GaussianProcess.fit(x, y2)]
    candidates = np.linspace(.05, .95, 10)[:, None]
    front = np.array([[.1, .5], [.5, .1]])
    a = mc_hvi(models, candidates, front, [1, 1], ["minimize", "minimize"], samples=64, seed=11)
    b = mc_hvi(models, candidates, front, [1, 1], ["minimize", "minimize"], samples=64, seed=11)
    assert np.array_equal(a, b) and (a >= 0).all() and np.isfinite(a).all()
    batch = greedy_batch(models, candidates, front, [1, 1], ["minimize", "minimize"], samples=64, seed=11, q=3, min_distance=.03)
    assert len(set(batch["indices"])) == 3
    assert batch["total_expected_batch_hvi"] >= 0
    assert batch["batch_method"] == "greedy_mc_hvi"
    with pytest.raises(OptimizationInputError, match=r"\[1, 4\]"):
        greedy_batch(models, candidates, front, [1, 1], ["minimize", "minimize"], q=5)


def test_sandbox_zdt1_api_and_model_persistence_are_isolated(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'moo.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False); Base.metadata.create_all(bind=engine)
    def get_test_db():
        db = sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = get_test_db
    try:
        db = sessions(); topic = ResearchTopic(name="MOO sandbox", description=""); db.add(topic); db.commit(); topic_id = topic.id; db.close()
        with TestClient(app) as client:
            trained = client.post("/api/optimization/multiobjective/models/train", json={
                "topic_id": topic_id, "mode": "sandbox", "feature_ids": ["x1", "x2"],
                "objective_ids": ["f1", "f2"], "objective_directions": ["minimize", "minimize"], "sandbox_samples": 24, "seed": 3})
            assert trained.status_code == 200, trained.text
            payload = trained.json(); mid = payload["model_id"]
            assert payload["model_type"] == "gpbo-moo-stage3-1"
            assert payload["config"]["data_contract"]["mode"] == "sandbox"
            got = client.get(f"/api/optimization/multiobjective/models/{mid}?topic_id={topic_id}")
            assert got.status_code == 200 and got.json()["dataset_hash"] == payload["dataset_hash"]
            pred = client.post(f"/api/optimization/multiobjective/models/{mid}/predict", json={"topic_id": topic_id, "candidates": [[.2, .3], [.7, .1]]})
            assert pred.status_code == 200 and len(pred.json()["predictions"]) == 2
            pareto = client.get(f"/api/optimization/multiobjective/pareto?model_id={mid}&topic_id={topic_id}&reference_point=%5B1.1%2C10.1%5D")
            assert pareto.status_code == 200 and pareto.json()["hypervolume"] > 0
            rec = client.post(f"/api/optimization/multiobjective/models/{mid}/recommend", json={
                "topic_id": topic_id, "bounds": [[0, 1], [0, 1]], "reference_point": [1.1, 10.1],
                "batch_size": 2, "search_budget": 50, "monte_carlo_samples": 32, "seed": 9})
            assert rec.status_code == 200, rec.text
            recommendation = rec.json(); assert len(recommendation["candidates"]) == 2
            assert recommendation["approval_status"] == "PENDING_RESEARCHER_REVIEW"
            assert all(c["approval_status"] == "PENDING_RESEARCHER_REVIEW" for c in recommendation["candidates"])
            persisted = client.get(f"/api/optimization/multiobjective/recommendations/{recommendation['recommendation_id']}?topic_id={topic_id}")
            assert persisted.status_code == 200 and len(persisted.json()["candidates"]) == 2
            wrong_topic = client.get(f"/api/optimization/multiobjective/models/{mid}?topic_id={topic_id+1}")
            assert wrong_topic.status_code == 404
            no_batch = client.post(f"/api/optimization/multiobjective/models/{mid}/recommend", json={
                "topic_id": topic_id, "bounds": [[0, 1], [0, 1]], "reference_point": [1.1, 10.1], "batch_size": 5})
            assert no_batch.status_code == 422
            infeasible = client.post(f"/api/optimization/multiobjective/models/{mid}/recommend", json={
                "topic_id": topic_id, "bounds": [[0, 1], [0, 1]], "reference_point": [1.1, 10.1],
                "constraints": [{"type":"linear_inequality","parameter_ids":["x1","x2"],"coefficients":[1,1],"coefficient_units":["dimensionless","dimensionless"],"threshold":-1,"unit":"dimensionless","sense":"le"}]})
            assert infeasible.status_code == 422 and infeasible.json()["detail"]["code"] == "INFEASIBLE_CONSTRAINT_SET"
            invalid_constraint = client.post(f"/api/optimization/multiobjective/models/{mid}/recommend", json={
                "topic_id": topic_id, "bounds": [[0, 1], [0, 1]], "reference_point": [1.1, 10.1],
                "constraints": [{"type":"variable_relation","left_parameter_id":"missing","right_parameter_id":"x2","relation":"ge"}]})
            assert invalid_constraint.status_code == 422
            benchmark = client.post("/api/optimization/multiobjective/sandbox/benchmark?seed=4&samples=30")
            assert benchmark.status_code == 200 and benchmark.json()["benchmark"] == "ZDT1"
            assert "no research observation" in benchmark.json()["notice"]
        assert len(zdt1([[0, 0], [1, 0]])) == 2
        db=sessions(); assert db.query(ScientificObservation).count()==0; db.close()
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_research_complete_case_pairs_only_same_experiment_and_replicate(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'moo-research.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False); Base.metadata.create_all(bind=engine)
    def get_test_db():
        db = sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = get_test_db
    try:
        db=sessions(); topic=ResearchTopic(name="Approved paired outcomes",description="");db.add(topic);db.flush()
        method=ExperimentMethod(topic_id=topic.id,name="MOO process");db.add(method);db.flush()
        version=MethodVersion(method_id=method.id,version_number=1,version_label="1",process_map=[{"name":"Growth"}],condition_definitions=[],material_definitions=[]);db.add(version);db.flush()
        feature_anchor=None
        for run in range(4):
            exp=Experiment(code=f"MOO-{run}",name=f"run {run}",target="two objectives",status="success",demo=False,topic_id=topic.id,method_version_id=version.id);db.add(exp);db.flush()
            step=ProcessStep(experiment_id=exp.id,name="Growth",order_index=0);db.add(step);db.flush()
            if feature_anchor is None: feature_anchor=step.id
            base={"topic_id":topic.id,"experiment_id":exp.id,"method_version_id":version.id,"process_step_id":step.id,"review_status":"ACCEPTED","value_type":"number"}
            db.add(ScientificObservation(**base,parameter_id="temperature",original_value=str(300+run),original_unit="K",normalized_value=float(300+run),normalized_unit="K",source_type="LAB_RECORD",source_id=f"{exp.id}:x"))
            db.add(ScientificObservation(**base,parameter_id="length",original_value=str(1+run),original_unit="um",normalized_value=float(1+run)*1e-6,normalized_unit="m",source_type="LAB_RESULT",source_id=f"{exp.id}:length"))
            db.add(ScientificObservation(**base,parameter_id="variation",original_value=str(4-run),original_unit="um",normalized_value=float(4-run)*1e-6,normalized_unit="m",source_type="LAB_RESULT",source_id=f"{exp.id}:variation"))
        db.commit();topic_id=topic.id;version_id=version.id;db.close()
        with TestClient(app) as client:
            trained=client.post("/api/optimization/multiobjective/models/train",json={"topic_id":topic_id,"mode":"research","method_version_id":version_id,"process_step_id":feature_anchor,"objective_process_step_id":feature_anchor,"feature_ids":["temperature"],"objective_ids":["length","variation"],"objective_directions":["maximize","minimize"]})
            assert trained.status_code==200,trained.text
            body=trained.json()
            assert body["mode"]=="research" and body["config"]["dataset_count"]==4
            provenance=body["config"]["data_contract"]["provenance"]
            assert len(provenance)==4 and all(len(row["observation_ids"])==3 for row in provenance)
            assert all(row["source_types"]==["LAB_RECORD","LAB_RESULT","LAB_RESULT"] for row in provenance)
            assert body["metrics"]["group_validation"]["validation_experiment_ids"]
            assert set(body["metrics"]["group_validation"]["training_experiment_ids"]).isdisjoint(body["metrics"]["group_validation"]["validation_experiment_ids"])
            recommendation=client.post(f"/api/optimization/multiobjective/models/{body['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[27,32]],"bounds_units":["degC"],"reference_point":[0,5e-6],"objective_scales":[1e-6,1e-6],"batch_size":1,"search_budget":48,"monte_carlo_samples":32})
            assert recommendation.status_code==200,recommendation.text
            assert 300 <= recommendation.json()["candidates"][0]["parameters"][0] <= 305.2
            assert recommendation.json()["acquisition"]=="mc_ehvi"
            assert np.isfinite(recommendation.json()["total_expected_batch_hv_improvement_mc_standard_error"])
            db=sessions(); absent_experiments=[row[0] for row in db.query(ScientificObservation.experiment_id).filter(ScientificObservation.parameter_id=="variation").all()][1:]
            db.query(ScientificObservation).filter(ScientificObservation.parameter_id=="variation",ScientificObservation.experiment_id.in_(absent_experiments)).delete(synchronize_session=False);db.commit();db.close()
            separated=client.post("/api/optimization/multiobjective/models/train",json={"topic_id":topic_id,"mode":"research","method_version_id":version_id,"feature_ids":["temperature"],"objective_ids":["length","variation"],"objective_directions":["maximize","minimize"]})
            assert separated.status_code==422 and separated.json()["detail"]["code"]=="INSUFFICIENT_COMPLETE_CASE_DATA"
            # A requested objective with only one accepted complete pairing is not
            # padded with a value from another experiment.
            missing=client.post("/api/optimization/multiobjective/models/train",json={"topic_id":topic_id,"mode":"research","method_version_id":version_id,"feature_ids":["temperature"],"objective_ids":["length","not_measured"],"objective_directions":["maximize","minimize"]})
            assert missing.status_code==422 and missing.json()["detail"]["code"]=="INSUFFICIENT_COMPLETE_CASE_DATA"
    finally:
        app.dependency_overrides.clear();engine.dispose()


def test_stage3_two_benchmarks_compare_equal_budget_policies_and_repeat_seeds():
    result=run_moo_benchmarks(seed=17,seeds=5,budget=8,mc_samples=32,candidate_pool_size=24)
    assert set(result["benchmarks"])=={"ZDT1","Branin-Currin"}
    expected={"random_feasible_search","scalarized_gp","single_mc_ehvi","greedy_batch_mc_hvi"}
    for benchmark in result["benchmarks"].values():
        assert set(benchmark["policies"])==expected
        assert benchmark["evaluation_budget_per_policy_per_seed"]==8
        for policy in benchmark["policies"].values():
            assert len(policy["runs"])==5
            assert all(run["evaluation_budget"]==8 and run["feasible_recommendation_rate"]==1 for run in policy["runs"])
            assert np.isfinite(policy["mean_hypervolume"]) and policy["mean_hypervolume"]>=0
    assert result["runtime_seconds"]>0 and result["peak_rss_bytes_process_high_water"]>0
    with pytest.raises(OptimizationInputError):run_moo_benchmarks(seeds=4)
