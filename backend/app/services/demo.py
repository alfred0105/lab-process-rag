from sqlalchemy.orm import Session
from app.db.models import Experiment, ProcessStep, ProcessVariable, ExperimentResult, FailureObservation

DATA=[
 ("EXP-001","Baseline growth","success",50,70,90,60,3,"uniform nanowire growth",{"nanowire_formed":"true","diameter_nm":"75","length_um":"1.2"}),
 ("EXP-002","Reduced seed cycles","failure",50,70,90,60,2,"nanowire not formed",{"nanowire_formed":"false"}),
 ("EXP-003","Higher temperature","success",50,70,95,60,3,"dense growth",{"nanowire_formed":"true","diameter_nm":"92","length_um":"1.5"}),
 ("EXP-004","Short growth","success",50,70,90,45,3,"short nanowires",{"nanowire_formed":"true","diameter_nm":"68","length_um":"0.8"}),
 ("EXP-005","Low precursor","failure",25,70,90,60,3,"solution cloudy; poor growth",{"nanowire_formed":"false"}),
 ("EXP-006","Extended growth","partial_success",50,70,90,90,3,"non-uniform growth",{"nanowire_formed":"true","diameter_nm":"105","length_um":"1.8"}),
]
def seed_demo(db: Session):
    if db.query(Experiment).filter(Experiment.demo.is_(True)).first(): return 0
    for code,name,status,zn,hmta,temp,time,cycles,obs,results in DATA:
        e=Experiment(code=code,name=name,target="ZnO nanowire",status=status,demo=True,notes="DEMO DATA — synthetic example; not paper evidence")
        db.add(e); db.flush()
        step=ProcessStep(experiment_id=e.id,name="Hydrothermal growth",step_type="growth",order_index=1,description="Synthetic demo conditions")
        db.add(step); db.flush()
        for n,v,u in [("zn_concentration",zn,"mM"),("hmta_concentration",hmta,"mM"),("growth_temperature",temp,"°C"),("growth_time",time,"min"),("seed_cycles",cycles,"cycles")]: db.add(ProcessVariable(process_step_id=step.id,name=n,value=str(v),unit=u,source_type="demo"))
        for k,v in results.items(): db.add(ExperimentResult(experiment_id=e.id,key=k,value=v))
        if status in ("failure","partial_success"):
            db.add(FailureObservation(experiment_id=e.id,category="synthetic_demo",description=obs))
    db.commit(); return len(DATA)
