from contextlib import asynccontextmanager
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.db.database import ROOT, Base, engine, SessionLocal
from app.db.models import Experiment, ExperimentMethod, MethodVersion, ResearchTopic, ResearchMaterial, ExperimentMaterial, Paper, MaterialAnalysisRun

def migrate_legacy_experiments():
    # create_all creates new tables, while these nullable columns upgrade older SQLite files in place.
    with engine.begin() as connection:
        columns={row[1] for row in connection.exec_driver_sql("PRAGMA table_info(experiments)").fetchall()}
        if "topic_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE experiments ADD COLUMN topic_id INTEGER REFERENCES research_topics(id)")
        if "method_version_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE experiments ADD COLUMN method_version_id INTEGER REFERENCES method_versions(id)")
        if "method_run_number" not in columns:
            connection.exec_driver_sql("ALTER TABLE experiments ADD COLUMN method_run_number INTEGER")
        if "duration_minutes" not in columns:
            connection.exec_driver_sql("ALTER TABLE experiments ADD COLUMN duration_minutes INTEGER")
        paper_columns={row[1] for row in connection.exec_driver_sql("PRAGMA table_info(papers)").fetchall()}
        if "topic_id" not in paper_columns:
            connection.exec_driver_sql("ALTER TABLE papers ADD COLUMN topic_id INTEGER REFERENCES research_topics(id)")
        analysis_columns={row[1] for row in connection.exec_driver_sql("PRAGMA table_info(material_analysis_runs)").fetchall()}
        if "topic_id" not in analysis_columns:
            connection.exec_driver_sql("ALTER TABLE material_analysis_runs ADD COLUMN topic_id INTEGER REFERENCES research_topics(id)")
        if "analysis_status" not in analysis_columns:
            connection.exec_driver_sql("ALTER TABLE material_analysis_runs ADD COLUMN analysis_status VARCHAR(30) NOT NULL DEFAULT 'completed'")
        if "result_key" not in analysis_columns:
            connection.exec_driver_sql("ALTER TABLE material_analysis_runs ADD COLUMN result_key VARCHAR(200)")
        if "process_step_id" not in analysis_columns:
            connection.exec_driver_sql("ALTER TABLE material_analysis_runs ADD COLUMN process_step_id INTEGER REFERENCES process_steps(id) ON DELETE SET NULL")
        version_columns={row[1] for row in connection.exec_driver_sql("PRAGMA table_info(method_versions)").fetchall()}
        if "version_label" not in version_columns:
            connection.exec_driver_sql("ALTER TABLE method_versions ADD COLUMN version_label VARCHAR(40)")
        connection.exec_driver_sql("UPDATE method_versions SET version_label = CAST(version_number AS TEXT) WHERE version_label IS NULL OR version_label = ''")
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

@asynccontextmanager
async def lifespan(app:FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_legacy_experiments()
    merge_legacy_method_drafts()
    import_used_materials_to_library()
    yield

app=FastAPI(title="Lab Process RAG",version="0.1.0",description="Paper-backed claims are cited; Gemma general knowledge is labeled separately.",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(router,prefix="/api")
FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
