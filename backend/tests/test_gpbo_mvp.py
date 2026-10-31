import math
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.db.models import Experiment, ExperimentMethod, MethodVersion, ProcessStep, ResearchTopic, ScientificObservation
from app.main import app
from app.services.optimization.gpbo import GaussianProcess, OptimizationInputError, acquisition, branin, noisy_expected_improvement, sandbox_benchmark
from app.services.optimization.constraints import compile_constraints, constraints_feasible, feasible_mask, project_candidates_to_equalities
from app.api.optimization import _dataset_counts, _group_holdout_indices


def test_gp_fit_predict_kernels_serialization_and_acquisitions():
    x=np.linspace(-2,2,18)[:,None]; y=np.sin(x[:,0])
    for kernel in ("rbf","matern"):
        model=GaussianProcess.fit(x,y,kernel=kernel,noise=1e-5)
        mean,std=model.predict([[0.2],[1.1]])
        assert np.all(np.isfinite(mean)) and np.all(np.isfinite(std)) and min(std)>=0
        restored=GaussianProcess.from_dict(model.to_dict())
        assert restored.predict([[0.2]])==model.predict([[0.2]])
    assert acquisition([1],[0],0,"ei")[0] == pytest.approx(0.99)
    assert acquisition([-1],[0],0,"ei",maximize=False)[0] == pytest.approx(0.99)
    assert acquisition([2],[0],1,"pi")[0] == 1
    assert acquisition([1],[0],0,"ucb",maximize=False)[0] == -1
    with pytest.raises(OptimizationInputError): GaussianProcess.fit([[1],[1]],[float("nan"),2])
    with pytest.raises(OptimizationInputError): model.predict([[1,2]])


def test_gp_consumes_measurement_uncertainty_and_rejects_invalid_values():
    x=np.array([[0.],[1.],[2.],[3.]])
    y=np.array([0.1,1.2,1.8,3.1])
    model=GaussianProcess.fit(x,y,measurement_std=[0.01,0.02,0.03,0.04])
    assert any(value>0 for value in model.observation_noise_variance)
    restored=GaussianProcess.from_dict(model.to_dict())
    assert restored.observation_noise_variance==model.observation_noise_variance
    with pytest.raises(OptimizationInputError): GaussianProcess.fit(x,y,measurement_std=[0.1])
    with pytest.raises(OptimizationInputError): GaussianProcess.fit(x,y,measurement_std=[0.0,0.1,-0.1,0.0])


def test_posterior_uncertainty_components_and_noisy_ei_are_reproducible():
    x=np.array([[0.],[1.],[2.],[3.]])
    y=np.array([0.3,0.1,0.6,0.2])
    model=GaussianProcess.fit(x,y,measurement_std=[0.02,0.1,0.03,0.2],noise=1e-4)
    mean,epistemic,aleatoric,total=model.predict_components([[0.5],[2.5]])
    assert np.allclose(np.square(total),np.square(epistemic)+np.square(aleatoric))
    assert np.all(np.asarray(aleatoric)>0)
    candidates=np.linspace(0,3,19)[:,None]
    first=noisy_expected_improvement(model,candidates,samples=128,seed=91,maximize=False)
    second=noisy_expected_improvement(model,candidates,samples=128,seed=91,maximize=False)
    assert np.all(np.isfinite(first)) and (first>=0).all()
    assert np.array_equal(first,second)
    high_noise=GaussianProcess.fit(x,y,measurement_std=[0.02,0.5,0.03,0.7],noise=1e-4)
    changed=noisy_expected_improvement(high_noise,candidates,samples=128,seed=91,maximize=False)
    assert not np.allclose(first,changed)


def test_stage1_saved_gp_json_remains_readable():
    model=GaussianProcess.fit([[0.0],[1.0],[2.0]],[0.0,1.0,0.2])
    legacy=model.to_dict()
    legacy["model_version"]="gpbo-mvp-1"
    legacy.pop("observation_noise_variance")
    restored=GaussianProcess.from_dict(legacy)
    mean,std=restored.predict([[0.5]])
    assert np.isfinite(mean).all() and np.isfinite(std).all()
    assert restored.observation_noise_variance==[0.0]*3


def test_group_holdout_never_splits_replicates_from_one_experiment():
    experiments=[11,11,11,12,12,13,13,14,14,15,15]
    train,valid,groups=_group_holdout_indices(experiments,seed=8)
    train_groups={experiments[i] for i in train}; valid_groups={experiments[i] for i in valid}
    assert train_groups.isdisjoint(valid_groups)
    assert len(valid_groups)==groups==1
    with pytest.raises(OptimizationInputError,match="INSUFFICIENT_INDEPENDENT_EXPERIMENTS"):
        _group_holdout_indices([1,1,1,2,2],seed=2)


def test_constraint_engine_checks_units_equalities_relations_and_conflicts():
    ids=["volume_a","volume_b"]
    units=["meter ** 3","meter ** 3"]
    constraint=[{"type":"linear_inequality","parameter_ids":ids,"coefficients":[1,1],
        "coefficient_units":["dimensionless","dimensionless"],"threshold":0.002,"unit":"meter ** 3","sense":"le"}]
    _,inequalities,equalities,_=compile_constraints(constraint,ids,units)
    assert constraints_feasible([[0,0.004],[0,0.003]],inequalities,equalities)
    points=np.array([[0.001,0.0005],[0.001,0.001],[0.003,0.0001]])
    mask,*_=feasible_mask(points,constraint,ids,units,[[0,0.004],[0,0.003]])
    assert mask.tolist()==[True,True,False]
    eq=[{"type":"linear_equality","parameter_ids":["volume_a"],"coefficients":[1],
        "coefficient_units":["dimensionless"],"threshold":0.001,"unit":"meter ** 3","tolerance":0.00001}]
    _,eq_ineq,eq_exact,projection=compile_constraints(eq,ids,units)
    assert not eq_exact and projection
    projected=project_candidates_to_equalities([[0.0002,0.0004],[0.0018,0.0015]],projection)
    eq_mask,*_=feasible_mask(projected,eq,ids,units,[[0,0.002],[0,0.002]])
    assert eq_mask.all()
    assert not constraints_feasible([[0,0.004],[0,0.003]],inequalities+[( [-1.,0.],-0.003,"contradiction")],equalities)
    with pytest.raises(OptimizationInputError,match="INCOMPATIBLE_UNITS"):
        compile_constraints([{"type":"linear_inequality","parameter_ids":ids,"coefficients":[1,1],
            "coefficient_units":["dimensionless","dimensionless"],"threshold":1,"unit":"meter ** 3"}],ids,["kelvin","meter ** 3"])


def test_dataset_counts_keep_experiments_replicates_pairs_and_effective_rows_distinct():
    rows=[{"experiment_id":1,"replicate_id":"a","x":[1],"paired_observation_count":1},
          {"experiment_id":1,"replicate_id":"b","x":[1],"paired_observation_count":1},
          {"experiment_id":2,"replicate_id":"a","x":[2],"paired_observation_count":1}]
    counts=_dataset_counts(rows)
    assert counts=={"independent_experiment_count":2,"unique_replicate_count":3,
        "paired_observation_count":3,"effective_training_sample_count":3,"unique_input_condition_count":2}


def test_research_pairing_requires_explicit_downstream_link_and_grouped_replicates(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'stage2-pairing.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False); Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        db=sessions(); topic=ResearchTopic(name="Stage 2 pairing",description=""); db.add(topic); db.flush()
        method=ExperimentMethod(topic_id=topic.id,name="ordered method"); db.add(method); db.flush()
        version=MethodVersion(method_id=method.id,version_number=1,version_label="1",process_map=[{"name":"Growth"},{"name":"Final measurement"}],condition_definitions=[],material_definitions=[]); db.add(version); db.flush()
        feature_anchor=target_anchor=None
        for run in range(6):
            exp=Experiment(code=f"S2-{run}",name=f"independent experiment {run}",target="length",status="success",demo=False,topic_id=topic.id,method_version_id=version.id)
            db.add(exp); db.flush()
            feature_step=ProcessStep(experiment_id=exp.id,name="Growth",order_index=0); outcome_step=ProcessStep(experiment_id=exp.id,name="Final measurement",order_index=1)
            db.add_all([feature_step,outcome_step]); db.flush()
            if run==0: feature_anchor=feature_step.id
            if run==1: target_anchor=outcome_step.id
            db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,process_step_id=feature_step.id,
                parameter_id="growth_temperature",original_value=str(300+run),original_unit="K",normalized_value=float(300+run),normalized_unit="K",
                value_type="number",source_type="LAB_RECORD",source_id=f"exp-{run}:temperature",review_status="ACCEPTED"))
            for replicate,result in (("r1",1.0+run*0.1),("r2",1.1+run*0.1)):
                db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,process_step_id=outcome_step.id,
                    parameter_id="final_length",original_value=str(result),original_unit="um",normalized_value=float(result*1e-6),normalized_unit="m",
                    measurement_uncertainty=0.02e-6,replicate_id=replicate,value_type="number",source_type="LAB_RESULT",
                    source_id=f"exp-{run}:length:{replicate}",review_status="ACCEPTED"))
        db.commit(); topic_id=topic.id; version_id=version.id; db.close()
        with TestClient(app) as client:
            base={"topic_id":topic_id,"mode":"research","method_version_id":version_id,"feature_ids":["growth_temperature"],"target_id":"final_length",
                "process_step_id":feature_anchor,"target_process_step_id":target_anchor,"pairing_policy":"downstream_explicit"}
            unconfirmed=client.post("/api/optimization/models/train",json=base)
            assert unconfirmed.status_code==422 and unconfirmed.json()["detail"]["code"]=="AMBIGUOUS_PROCESS_STEP"
            valid={**base,"downstream_link_confirmed":True,"downstream_relation_label":"growth temperature to final measured length"}
            preview=client.get("/api/optimization/dataset",params={"topic_id":topic_id,"method_version_id":version_id,"feature_ids":"growth_temperature","target_id":"final_length",
                "process_step_id":feature_anchor,"target_process_step_id":target_anchor,"pairing_policy":"downstream_explicit","downstream_link_confirmed":"true",
                "downstream_relation_label":"growth temperature to final measured length"})
            assert preview.status_code==200,preview.text
            data=preview.json()
            assert data["independent_experiment_count"]==6
            assert data["unique_replicate_count"]==12
            assert data["paired_observation_count"]==12
            assert data["effective_training_sample_count"]==12
            assert data["unique_input_condition_count"]==6
            trained=client.post("/api/optimization/models/train",json=valid)
            assert trained.status_code==200,trained.text
            assert trained.json()["config"]["validation_scheme"].startswith("experiment-grouped")
            assert trained.json()["config"]["dataset_counts"]["independent_experiment_count"]==6
            assert trained.json()["config"]["validation_group_count"]==1
            provenance=trained.json()["config"]["provenance"]
            assert all(len(row["source_ids"])==2 and row["replicate_id"] in {"r1","r2"} for row in provenance)
            # Same-step pairing cannot silently connect feature and later outcome.
            same_step=client.get("/api/optimization/dataset",params={"topic_id":topic_id,"method_version_id":version_id,"feature_ids":"growth_temperature","target_id":"final_length",
                "process_step_id":feature_anchor,"target_process_step_id":target_anchor,"pairing_policy":"same_step"})
            assert same_step.status_code==422 and same_step.json()["detail"]["code"]=="AMBIGUOUS_PROCESS_STEP"
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_dataset_minimums_do_not_confuse_rows_with_experiments_or_conditions(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'stage2-counts.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False); Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        db=sessions(); topic=ResearchTopic(name="Distinct sample counts",description=""); db.add(topic); db.flush()
        method=ExperimentMethod(topic_id=topic.id,name="replicate method"); db.add(method); db.flush()
        versions=[]
        for index in range(3):
            version=MethodVersion(method_id=method.id,version_number=index+1,version_label=str(index+1),process_map=[],condition_definitions=[],material_definitions=[])
            db.add(version); db.flush(); versions.append(version)
        def add_pair(version,run,x,target_values,feature_replicates=None,target_replicates=None):
            exp=Experiment(code=f"V{version.version_number}-{run}",name=f"run {run}",target="outcome",status="success",demo=False,topic_id=topic.id,method_version_id=version.id)
            db.add(exp); db.flush()
            feature_replicates=feature_replicates or [None]
            target_replicates=target_replicates or [None]*len(target_values)
            for i,replicate in enumerate(feature_replicates):
                db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,parameter_id="input_x",
                    original_value=str(x),original_unit="K",normalized_value=float(x),normalized_unit="K",replicate_id=replicate,
                    value_type="number",source_type="LAB_RECORD",source_id=f"{exp.id}:x:{i}",review_status="ACCEPTED"))
            for i,value in enumerate(target_values):
                db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,parameter_id="outcome_y",
                    original_value=str(value),original_unit="dimensionless",normalized_value=float(value),normalized_unit="dimensionless",
                    replicate_id=target_replicates[i],value_type="number",source_type="LAB_RESULT",source_id=f"{exp.id}:y:{i}",review_status="ACCEPTED"))
        # One Experiment with 10 rows must still fail the independent-run gate.
        add_pair(versions[0],0,300,[float(i) for i in range(10)])
        # Three independent repeats at one condition pass run count, but fail
        # the distinct-input-condition gate.
        for i in range(3): add_pair(versions[1],i,300,[float(i),float(i+1)],target_replicates=["r1","r2"])
        # Replicate-specific feature rX must never be substituted for outcome r1.
        for i in range(3): add_pair(versions[2],i,300+i,[float(i)],feature_replicates=["rX"],target_replicates=["r1"])
        db.commit(); topic_id=topic.id; ids=[version.id for version in versions]; db.close()
        with TestClient(app) as client:
            params={"topic_id":topic_id,"feature_ids":"input_x","target_id":"outcome_y"}
            one=client.get("/api/optimization/dataset",params={**params,"method_version_id":ids[0]})
            assert one.status_code==422 and one.json()["detail"]["code"]=="INSUFFICIENT_INDEPENDENT_EXPERIMENTS"
            assert one.json()["detail"]["paired_observation_count"]==10
            same_condition=client.get("/api/optimization/dataset",params={**params,"method_version_id":ids[1]})
            assert same_condition.status_code==422 and same_condition.json()["detail"]["code"]=="INSUFFICIENT_APPROVED_DATA"
            assert same_condition.json()["detail"]["unique_input_condition_count"]==1
            mismatch=client.get("/api/optimization/dataset",params={**params,"method_version_id":ids[2]})
            assert mismatch.status_code==422 and mismatch.json()["detail"]["code"]=="AMBIGUOUS_OBSERVATION_PAIRING"
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_synthetic_branin_bo_benchmark_is_reproducible_and_not_labeled_research():
    first=sandbox_benchmark(seed=23,budget=8); second=sandbox_benchmark(seed=23,budget=8)
    assert {key:value for key,value in first.items() if key!="wall_clock_seconds"}=={key:value for key,value in second.items() if key!="wall_clock_seconds"}
    assert first["wall_clock_seconds"]>0
    assert first["function"].startswith("Branin")
    assert "do not establish" in first["notice"]
    assert first["seeds"]==5
    assert set(first["policies"])=={"random_search","latin_hypercube","gp_ei","gp_ucb"}
    assert first["policies"]["gp_ei"]["runs"]==5
    assert len(first["policies"]["gp_ei"]["mean_best_trace"])==8
    assert np.isfinite(branin(np.array([[math.pi,2.275]]))).all()


def test_gpbo_api_sandbox_persistence_and_research_data_isolation(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'gpbo.db'}",connect_args={"check_same_thread":False})
    sessions=sessionmaker(bind=engine,autoflush=False,autocommit=False); Base.metadata.create_all(bind=engine)
    def get_test_db():
        db=sessions()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db]=get_test_db
    try:
        with TestClient(app) as client:
            db=sessions(); topic=ResearchTopic(name="GP test",description=""); db.add(topic); db.flush()
            other=ResearchTopic(name="GP other",description=""); db.add(other); db.flush()
            method=ExperimentMethod(topic_id=topic.id,name="test process"); db.add(method); db.flush()
            version=MethodVersion(method_id=method.id,version_number=1,version_label="1",process_map=[],condition_definitions=[],material_definitions=[]); db.add(version); db.flush()
            for i,(x,y) in enumerate([(0,0.2),(1,0.8),(2,0.5),(3,1.1),(4,0.7)]):
                exp=Experiment(code=f"GP-{i}",name=f"run {i}",target="test",status="success",demo=False,topic_id=topic.id,method_version_id=version.id)
                db.add(exp); db.flush()
                for param,value,source in (("temperature",x,"LAB_RECORD"),("yield",y,"LAB_RESULT")):
                    unit="K" if param=="temperature" else "dimensionless"
                    db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,
                        parameter_id=param,original_value=str(value),original_unit=unit,normalized_value=float(value),normalized_unit=unit,
                        value_type="number",source_type=source,source_id=f"{exp.id}:{param}",review_status="ACCEPTED"))
                # This simulation-only row must never join the measured target.
                db.add(ScientificObservation(topic_id=topic.id,experiment_id=exp.id,method_version_id=version.id,
                    parameter_id="yield",original_value="99",original_unit="dimensionless",normalized_value=99.,normalized_unit="dimensionless",
                    value_type="number",source_type="SIMULATION",source_id=f"{exp.id}:sim",review_status="ACCEPTED"))
            db.commit(); topic_id=topic.id; other_id=other.id; version_id=version.id; db.close()
            preview=client.get(f"/api/optimization/dataset?topic_id={topic_id}&method_version_id={version_id}&feature_ids=temperature&target_id=yield")
            assert preview.status_code==200 and preview.json()["sample_count"]==5
            assert preview.json()["features"][0]["unit"]=="kelvin"
            assert len(preview.json()["dataset_hash"])==64
            train=client.post("/api/optimization/models/train",json={"topic_id":topic_id,"mode":"research","method_version_id":version_id,"feature_ids":["temperature"],"target_id":"yield","kernel":"matern"})
            assert train.status_code==200,train.text
            model=train.json(); assert model["mode"]=="research" and model["config"]["sample_count"]==5
            assert model["config"]["validation_scheme"].startswith("experiment-grouped deterministic")
            assert len(model["config"]["provenance"])==5
            assert len(model["dataset_hash"])==64
            prediction=client.post(f"/api/optimization/models/{model['model_id']}/predict",json={"topic_id":topic_id,"candidates":[[2.5]]})
            assert prediction.status_code==200 and np.isfinite(prediction.json()["predictions"][0]["predicted_mean"])
            rec=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"maximize":True,"candidate_count":3,"search_samples":500})
            assert rec.status_code==200 and len(rec.json()["candidates"])==3
            assert rec.json()["candidates"][0]["approval_status"]=="PENDING_RESEARCHER_REVIEW"
            assert "not a predicted outcome" in rec.json()["notice"]
            for acquisition in ("pi","ucb"):
                alternate=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"maximize":False,"acquisition":acquisition,"candidate_count":2,"search_samples":500,"seed":11})
                assert alternate.status_code==200 and len(alternate.json()["candidates"])==2
                assert alternate.json()["candidates"][0]["acquisition_score"]>=alternate.json()["candidates"][1]["acquisition_score"]
            noisy=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"maximize":True,
                "acquisition":"noisy_ei","candidate_count":2,"search_samples":500,"seed":11,"noisy_ei_samples":64})
            assert noisy.status_code==200 and all(candidate["epistemic_std"]>=0 and candidate["aleatoric_std"]>=0 for candidate in noisy.json()["candidates"])
            constrained=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"bounds_units":["degC"],
                "constraints":[{"type":"linear_inequality","parameter_ids":["temperature"],"coefficients":[1],"unit":"K","threshold":275}],
                "candidate_count":3,"search_samples":1000,"seed":17})
            assert constrained.status_code==200,constrained.text
            assert all(273.15<=row["values"][0]<=275 for row in constrained.json()["candidates"])
            assert constrained.json()["candidates"][0]["constraint_evaluation"][0]["status"]=="SATISFIED"
            impossible=client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],
                "constraints":[{"type":"linear_inequality","parameter_ids":["temperature"],"coefficients":[1],"unit":"K","threshold":-1}],
                "candidate_count":1,"search_samples":300})
            assert impossible.status_code==422 and impossible.json()["detail"]["code"]=="INFEASIBLE_CONSTRAINT_SET"
            assert client.get(f"/api/optimization/models/{model['model_id']}?topic_id={other_id}").status_code==404
            approved=client.get(f"/api/optimization/observations/approved?topic_id={topic_id}").json()
            assert all(row["source_type"]!="SIMULATION" for row in approved["observations"])
            assert client.post(f"/api/optimization/models/{model['model_id']}/recommend",json={"topic_id":topic_id,"bounds":[[0,4]],"constraints":[{"type":"unknown"}]}).status_code==422
            sandbox=client.post("/api/optimization/models/train",json={"topic_id":topic_id,"mode":"sandbox","feature_ids":["x1","x2"],"target_id":"branin","seed":31})
            assert sandbox.status_code==200 and sandbox.json()["mode"]=="sandbox"
            assert sandbox.json()["config"]["sample_count"]==24
            assert client.get("/api/optimization/recommendations/1?topic_id="+str(topic_id)).status_code==200
            insufficient=client.post("/api/optimization/models/train",json={"topic_id":other_id,"mode":"research","method_version_id":version_id,"feature_ids":["temperature"],"target_id":"yield"})
            assert insufficient.status_code==422 and insufficient.json()["detail"]["code"]=="INSUFFICIENT_INDEPENDENT_EXPERIMENTS"
            bench=client.post(f"/api/optimization/sandbox/benchmark?topic_id={topic_id}&budget=5&seed=9")
            assert bench.status_code==200 and bench.json()["policies"]["gp_ei"]["runs"]==5
            stage2=client.post(f"/api/optimization/sandbox/benchmark/stage2?topic_id={topic_id}&kind=all&budget=3&seeds=5&seed=29")
            assert stage2.status_code==200,stage2.text
            stage2_data=stage2.json()
            assert stage2_data["noisy"]["policies"]["gp_noisy_ei"]["runs"]==5
            assert stage2_data["constrained"]["policies"]["constraint_aware_gp_ei"]["feasible_recommendation_rate"]==1.0
            assert "Synthetic software benchmark only" in stage2_data["notice"]
    finally:
        app.dependency_overrides.clear(); engine.dispose()
