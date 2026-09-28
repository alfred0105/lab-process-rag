from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload
from app.db.database import get_db
from app.db.models import Experiment, Paper, EvidenceChunk, ProcessStep, ProcessVariable, ExperimentResult, FailureObservation
from app.schemas.core import ExperimentIn, DesignRequest, ProcessChange
from app.services.ingestion.pdf import ingest_pdf
from app.services.retrieval.provider import SQLiteFTSProvider
from app.services.experiment.compare import compare
from app.services.failure_analysis.service import analyze
from app.services.demo import seed_demo
from app.services.calculator.service import amount, mass_from_concentration, dilution, ratio
router=APIRouter(); retrieval=SQLiteFTSProvider()

def exp_query(db):
    return db.query(Experiment).options(selectinload(Experiment.steps).selectinload(ProcessStep.variables),selectinload(Experiment.results),selectinload(Experiment.observations))
def serialize_exp(e):
    return {"id":e.id,"code":e.code,"name":e.name,"target":e.target,"date":e.date,"operator":e.operator,"notes":e.notes,"status":e.status,"demo":e.demo,"steps":[{"id":s.id,"name":s.name,"step_type":s.step_type,"order_index":s.order_index,"description":s.description,"variables":[{"id":v.id,"name":v.name,"value":v.value,"unit":v.unit,"material":v.material,"source_type":v.source_type,"source_id":v.source_id} for v in s.variables]} for s in e.steps],"results":[{"key":r.key,"value":r.value,"unit":r.unit} for r in e.results],"observations":[{"category":o.category,"description":o.description,"severity":o.severity} for o in e.observations]}

def create_exp(db,payload):
    code=payload.code or f"EXP-{(db.query(Experiment).count()+1):03d}"
    if db.query(Experiment).filter_by(code=code).first(): raise HTTPException(409,"Experiment code already exists")
    e=Experiment(code=code,name=payload.name,target=payload.target,date=payload.date,operator=payload.operator,notes=payload.notes,status=payload.status,demo=payload.demo)
    db.add(e); db.flush()
    for si,s in enumerate(payload.steps):
        step=ProcessStep(experiment_id=e.id,name=s.name,step_type=s.step_type,order_index=s.order_index or si,description=s.description); db.add(step); db.flush()
        for v in s.variables: db.add(ProcessVariable(process_step_id=step.id,name=v.name,value=str(v.value),unit=v.unit,material=v.material,source_type=v.source_type,source_id=v.source_id))
    for r in payload.results: db.add(ExperimentResult(experiment_id=e.id,key=r.key,value=str(r.value),unit=r.unit))
    for o in payload.observations: db.add(FailureObservation(experiment_id=e.id,category=o.category,description=o.description,severity=o.severity))
    db.commit(); return exp_query(db).filter_by(id=e.id).first()

@router.get("/health")
def health(): return {"status":"ok","evidence_policy":"No Evidence → No Claim"}
@router.get("/experiments")
def experiments(db:Session=Depends(get_db)): return [serialize_exp(e) for e in exp_query(db).order_by(Experiment.id).all()]
@router.post("/experiments")
def add_experiment(payload:ExperimentIn,db:Session=Depends(get_db)): return serialize_exp(create_exp(db,payload))
@router.post("/experiments/import")
def import_experiments(payload:list[ExperimentIn],db:Session=Depends(get_db)):
    made=[]
    try:
        for item in payload: made.append(serialize_exp(create_exp(db,item)))
        return {"imported":len(made),"experiments":made}
    except Exception:
        db.rollback(); raise
@router.get("/experiments/{experiment_id}")
def experiment(experiment_id:int,db:Session=Depends(get_db)):
    e=exp_query(db).filter_by(id=experiment_id).first()
    if not e: raise HTTPException(404,"Experiment not found")
    return serialize_exp(e)
@router.put("/experiments/{experiment_id}")
def update_experiment(experiment_id:int,payload:ExperimentIn,db:Session=Depends(get_db)):
    e=exp_query(db).filter_by(id=experiment_id).first()
    if not e: raise HTTPException(404,"Experiment not found")
    db.delete(e); db.commit(); payload.code=e.code; return serialize_exp(create_exp(db,payload))
@router.delete("/experiments/{experiment_id}")
def delete_experiment(experiment_id:int,db:Session=Depends(get_db)):
    e=db.get(Experiment,experiment_id)
    if not e: raise HTTPException(404,"Experiment not found")
    db.delete(e); db.commit(); return {"deleted":experiment_id}
@router.get("/experiments/{experiment_id}/compare/{other_id}")
def compare_experiments(experiment_id:int,other_id:int,db:Session=Depends(get_db)):
    a=exp_query(db).filter_by(id=experiment_id).first(); b=exp_query(db).filter_by(id=other_id).first()
    if not a or not b: raise HTTPException(404,"Experiment not found")
    return {"experiment_a":a.code,"experiment_b":b.code,**compare(a,b)}
@router.get("/experiments/{experiment_id}/failure-analysis")
def failure_analysis(experiment_id:int,db:Session=Depends(get_db)):
    e=exp_query(db).filter_by(id=experiment_id).first()
    if not e: raise HTTPException(404,"Experiment not found")
    pool=exp_query(db).all(); return analyze(e,pool)
@router.post("/papers")
def upload_paper(file:UploadFile=File(...),title:str|None=Form(None),authors:str=Form(""),year:int|None=Form(None),db:Session=Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"): raise HTTPException(400,"PDF files only")
    try: p=ingest_pdf(db,file.file.read(),file.filename,title,authors,year)
    except Exception as exc: db.rollback(); raise HTTPException(400,f"Unable to parse PDF: {exc}")
    return {"id":p.id,"title":p.title,"filename":p.filename,"pages":len({c.page for c in p.chunks}),"chunks":len(p.chunks)}
@router.get("/papers")
def papers(db:Session=Depends(get_db)):
    return [{"id":p.id,"title":p.title,"authors":p.authors,"year":p.year,"filename":p.filename,"chunk_count":len(p.chunks)} for p in db.query(Paper).all()]
@router.get("/papers/{paper_id}/evidence")
def paper_evidence(paper_id:int,db:Session=Depends(get_db)):
    if not db.get(Paper,paper_id): raise HTTPException(404,"Paper not found")
    return [{"evidence_id":c.id,"page":c.page,"section":c.section,"text":c.text} for c in db.query(EvidenceChunk).filter_by(paper_id=paper_id).order_by(EvidenceChunk.page,EvidenceChunk.chunk_index)]
@router.get("/search")
def search(q:str,limit:int=10,db:Session=Depends(get_db)): return retrieval.search(db,q,limit)
@router.post("/search")
def search_post(payload:dict,db:Session=Depends(get_db)): return retrieval.search(db,str(payload.get("query","")),int(payload.get("limit",10)))
@router.post("/demo/seed")
def seed(db:Session=Depends(get_db)): return {"seeded":seed_demo(db),"label":"DEMO DATA"}
@router.post("/calculate/mass")
def calc_mass(p:dict):
    try:return mass_from_concentration(float(p["concentration"]),p.get("concentration_unit","M"),float(p["volume"]),p.get("volume_unit","L"),float(p["molar_mass"]))
    except (KeyError,ValueError) as e: raise HTTPException(400,str(e))
@router.post("/calculate/amount")
def calc_amount(p:dict):
    try:return amount(float(p["concentration"]),p.get("concentration_unit","M"),float(p["volume"]),p.get("volume_unit","L"))
    except (KeyError,ValueError) as e: raise HTTPException(400,str(e))
@router.post("/calculate/dilution")
def calc_dilution(p:dict):
    try:return dilution(float(p["c1"]),float(p["v1"]),float(p["c2"]) if p.get("c2") is not None else None,float(p["v2"]) if p.get("v2") is not None else None)
    except (KeyError,ValueError) as e: raise HTTPException(400,str(e))
@router.post("/calculate/molar-ratio")
def calc_ratio(p:dict):
    try:return ratio(float(p["a"]),float(p["b"]),p.get("basis","molar"))
    except (KeyError,ValueError) as e: raise HTTPException(400,str(e))
@router.post("/designs")
def design(req:DesignRequest,db:Session=Depends(get_db)):
    results=retrieval.search(db,req.target,10)
    return {"target":req.target,"constraints":req.constraints,"candidate":{"steps":[],"evidence":results,"status":"UNKNOWN" if not results else "SUPPORTED"},"message":"V0.1 returns supplied evidence for review; it does not autonomously invent a process."}
@router.post("/process-changes/analyze")
def change_analysis(req:ProcessChange,db:Session=Depends(get_db)):
    e=exp_query(db).filter_by(id=req.experiment_id).first()
    if not e: raise HTTPException(404,"Experiment not found")
    old=[]
    for s in e.steps:
        for v in s.variables:
            if v.name==req.variable_name: old.append({"value":v.value,"unit":v.unit})
    related=retrieval.search(db,req.variable_name,10)
    return {"changed_variable":req.variable_name,"original_values":old,"new_value":req.new_value,"new_unit":req.new_unit,"related_evidence":related,"related_experiment_results":[{"code":x.code,"status":x.status,"results":[{"key":r.key,"value":r.value} for r in x.results]} for x in exp_query(db).all() if any(v.name==req.variable_name for s in x.steps for v in s.variables)],"evidence_status":"SUPPORTED" if related else "UNKNOWN"}
