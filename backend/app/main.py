from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import sqlite3
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.db.database import DB_PATH, ROOT, Base, engine, SessionLocal
from app.db.models import Experiment, ExperimentMethod, MethodVersion, ResearchTopic, ResearchMaterial, ExperimentMaterial, Paper, MaterialAnalysisRun, SimulationRun, ScientificObservation
from app.services.scientific_data import make_observation

def migrate_legacy_data():
    """Idempotent data backfill retained for pre-Alembic lab databases."""
    db=SessionLocal()
    try:
        old_runs=db.query(Experiment).filter(Experiment.method_version_id.is_(None)).all()
        old_papers=db.query(Paper).filter(Paper.topic_id.is_(None)).all()
        old_analysis=db.query(MaterialAnalysisRun).filter(MaterialAnalysisRun.topic_id.is_(None)).all()
        if not old_runs and not old_papers and not old_analysis: return
        topic=ResearchTopic(name="기존 연구 자료",description="이전 버전에서 가져온 실험 기록, 논문, 분석 자료")
        db.add(topic); db.flush()
        for run in old_runs:
            method=ExperimentMethod(topic_id=topic.id,name=run.name,description="기존 실험 기록에서 가져온 방법 초안",category="custom")
            db.add(method); db.flush()
            process_map=[]; conditions=[]
            for step in sorted(run.steps,key=lambda item:item.order_index):
                process_map.append({"name":step.name,"description":step.description,"step_type":step.step_type})
                for variable in step.variables:
                    conditions.append({"step_name":step.name,"name":variable.name,"unit":variable.unit or "","value_type":"text","required":False})
            materials=[{"name":item.name,"role":item.role,"unit":item.unit or "","lot_number":item.lot_number,"supplier":item.supplier} for item in run.materials]
            version=MethodVersion(method_id=method.id,version_number=1,version_label="1",process_map=process_map,condition_definitions=conditions,material_definitions=materials)
            db.add(version); db.flush()
            run.topic_id=topic.id; run.method_version_id=version.id; run.method_run_number=1
        for paper in old_papers: paper.topic_id=topic.id
        for analysis in old_analysis:
            linked=db.get(Experiment,analysis.experiment_id) if analysis.experiment_id else None
            analysis.topic_id=linked.topic_id if linked and linked.topic_id else topic.id
        db.commit()
    finally:
        db.close()

def merge_legacy_method_drafts():
    """Group imported runs that share the same saved method schema."""
    db=SessionLocal()
    try:
        drafts=db.query(ExperimentMethod).filter(ExperimentMethod.description=="기존 실험 기록에서 가져온 방법 초안").all()
        groups={}
        for method in drafts:
            version=method.versions[0] if method.versions else None
            if not version: continue
            signature=(method.topic_id,json.dumps(version.process_map,ensure_ascii=False,sort_keys=True),json.dumps(version.condition_definitions,ensure_ascii=False,sort_keys=True),json.dumps(version.material_definitions,ensure_ascii=False,sort_keys=True))
            groups.setdefault(signature,[]).append((method,version))
        for members in groups.values():
            if len(members)<2: continue
            canonical,version=members[0]
            canonical.name=(version.process_map[0].get("name") if version.process_map else canonical.name) or canonical.name
            duplicates=[method.id for method,_ in members[1:]]
            all_versions=[item.id for _,item in members]
            runs=db.query(Experiment).filter(Experiment.method_version_id.in_(all_versions)).order_by(Experiment.id).all()
            for run_number,run in enumerate(runs,1):
                run.method_version_id=version.id
                run.method_run_number=run_number
            db.flush()
            for method,_ in members[1:]: db.delete(method)
        db.commit()
    finally:
        db.close()

def import_used_materials_to_library():
    """Make previously recorded topic materials reusable in the saved-material list."""
    db=SessionLocal()
    try:
        existing={(item.topic_id,item.name.strip().casefold()) for item in db.query(ResearchMaterial).all()}
        for used in db.query(ExperimentMaterial).join(Experiment).filter(Experiment.topic_id.is_not(None)).all():
            key=(used.experiment.topic_id,used.name.strip().casefold())
            if not key[1] or key in existing: continue
            db.add(ResearchMaterial(topic_id=key[0],name=used.name.strip(),role=used.role or "",unit=used.unit or "",supplier=used.supplier or "",catalog_number=""))
            existing.add(key)
        db.commit()
    finally:
        db.close()

def upgrade_schema():
    """Apply versioned additive schema updates after the legacy bootstrap."""
    config=Config(str(ROOT / "backend" / "alembic.ini"))
    command.upgrade(config,"head")

def backup_before_schema_upgrade():
    """Take a consistent SQLite backup before applying pending Alembic revisions."""
    if not DB_PATH.exists():
        return None
    config=Config(str(ROOT / "backend" / "alembic.ini"))
    current_connection=engine.connect()
    try:
        current=MigrationContext.configure(current_connection).get_current_revision()
        head=ScriptDirectory.from_config(config).get_current_head()
    finally:
        current_connection.close()
    if current == head:
        return None
    backup_dir=ROOT / "data" / "backups"
    backup_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination=backup_dir / f"lab_process_pre_alembic_{stamp}.db"
    source=engine.raw_connection()
    backup=sqlite3.connect(destination)
    try:
        source.driver_connection.backup(backup)
    finally:
        backup.close()
        source.close()
    return destination

def classify_observation_source(experiment, variable=None, *, is_result=False):
    if experiment.demo or (variable is not None and variable.source_type=="demo"):
        return "SYNTHETIC_DEMO"
    if experiment.status=="reference" or (variable is not None and variable.source_type in {"literature","reference","paper"}):
        return "LITERATURE"
    return "LAB_RESULT" if is_result else "LAB_RECORD"

def backfill_scientific_observations():
    """Copy legacy scalar records into an additive view; never edit source rows."""
    db=SessionLocal()
    try:
        # Early versions of the extension table lacked topic_id. Recover that
        # context from the linked original experiment without changing the
        # source experiment or its recorded values.
        for observation in db.query(ScientificObservation).filter(
            ScientificObservation.topic_id.is_(None), ScientificObservation.experiment_id.is_not(None)
        ).all():
            source_experiment = db.get(Experiment, observation.experiment_id)
            if source_experiment:
                observation.topic_id = source_experiment.topic_id
                if observation.method_version_id is None:
                    observation.method_version_id = source_experiment.method_version_id
        existing={row[0] for row in db.query(ScientificObservation.source_id).all()}
        # Correct legacy reference rows in the normalized view. The original
        # experiment and its scalar values remain untouched.
        by_source={row.source_id:row for row in db.query(ScientificObservation).all()}
        for experiment in db.query(Experiment).all():
            for step in experiment.steps:
                for variable in step.variables:
                    source_id=f"process-variable:{variable.id}"
                    source_type=classify_observation_source(experiment,variable)
                    if source_id in existing:
                        observation=by_source.get(source_id)
                        if observation and source_type=="LITERATURE" and observation.source_type in {"LAB_RECORD","LAB_RESULT"}:
                            observation.source_type="LITERATURE"
                        continue
                    db.add(make_observation(topic_id=experiment.topic_id,experiment_id=experiment.id,method_version_id=experiment.method_version_id,
                        process_step_id=step.id,step_name=step.name,name=variable.name,value=variable.value,unit=variable.unit,
                        material=variable.material,source_type=source_type,source_id=source_id))
                    existing.add(source_id)
            for result in experiment.results:
                source_id=f"experiment-result:{result.id}"
                source_type=classify_observation_source(experiment,is_result=True)
                if source_id in existing:
                    observation=by_source.get(source_id)
                    if observation and source_type=="LITERATURE" and observation.source_type in {"LAB_RECORD","LAB_RESULT"}:
                        observation.source_type="LITERATURE"
                    continue
                db.add(make_observation(topic_id=experiment.topic_id,experiment_id=experiment.id,method_version_id=experiment.method_version_id,
                    process_step_id=None,step_name="experiment result",name=result.key,value=result.value,unit=result.unit,
                    source_type=source_type,source_id=source_id))
                existing.add(source_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app:FastAPI):
    backup_before_schema_upgrade()
    Base.metadata.create_all(bind=engine)
    upgrade_schema()
    migrate_legacy_data()
    merge_legacy_method_drafts()
    import_used_materials_to_library()
    backfill_scientific_observations()
    yield

app=FastAPI(title="Lab Process RAG",version="0.1.0",description="Paper-backed claims are cited; Gemma general knowledge is labeled separately.",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router,prefix="/api")
FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
