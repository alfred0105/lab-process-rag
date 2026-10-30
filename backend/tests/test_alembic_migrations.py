from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_legacy_sqlite_schema_upgrades_twice_without_duplicate_columns(tmp_path):
    path=tmp_path/"legacy-schema.db"
    engine=create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE research_topics (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE method_versions (id INTEGER PRIMARY KEY, version_number INTEGER)")
        connection.exec_driver_sql("CREATE TABLE process_steps (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE research_materials (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE experiments (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE experiment_materials (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE papers (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE material_analysis_runs (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE integrated_analysis_sessions (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE simulation_runs (id INTEGER PRIMARY KEY, status VARCHAR(30))")
        # Simulate the early extension tables produced before Alembic tracked
        # their schema: topic_id and observation review targets are missing.
        connection.exec_driver_sql("""CREATE TABLE scientific_observations (
            id INTEGER PRIMARY KEY, experiment_id INTEGER, method_version_id INTEGER,
            process_step_id INTEGER, parameter_id VARCHAR(300) NOT NULL, material_id INTEGER,
            original_value TEXT NOT NULL, original_unit VARCHAR(100), normalized_value FLOAT,
            normalized_unit VARCHAR(100), value_type VARCHAR(30) NOT NULL,
            measurement_uncertainty FLOAT, replicate_id VARCHAR(200), source_type VARCHAR(40) NOT NULL,
            source_id VARCHAR(200) NOT NULL, analysis_run_id INTEGER, review_status VARCHAR(30) NOT NULL,
            normalization_error TEXT, created_at DATETIME NOT NULL)""")
        connection.exec_driver_sql("""CREATE TABLE measurement_review_events (
            id INTEGER PRIMARY KEY, analysis_run_id INTEGER NOT NULL, review_status VARCHAR(30) NOT NULL,
            reviewer VARCHAR(200) NOT NULL, opinion TEXT NOT NULL, reason TEXT NOT NULL,
            tool_id VARCHAR(100) NOT NULL, tool_version VARCHAR(100) NOT NULL,
            original_file_hash VARCHAR(64) NOT NULL, settings_json JSON NOT NULL, created_at DATETIME NOT NULL)""")
        connection.exec_driver_sql("INSERT INTO scientific_observations (id,parameter_id,original_value,value_type,source_type,source_id,review_status,created_at) VALUES (7,'temperature','25','number','LAB_RECORD','legacy:7','PENDING','2026-10-30')")
        connection.exec_driver_sql("INSERT INTO measurement_review_events (id,analysis_run_id,review_status,reviewer,opinion,reason,tool_id,tool_version,original_file_hash,settings_json,created_at) VALUES (9,1,'REVIEWED','old reviewer','checked','ok','legacy.tool','1','abc','{}','2026-10-30')")
    config=Config("alembic.ini")
    config.set_main_option("sqlalchemy.url",f"sqlite:///{path}")
    command.upgrade(config,"head")
    command.upgrade(config,"head")
    inspector=inspect(engine)
    expected={
        "experiments":{"topic_id","method_version_id","method_run_number","duration_minutes"},
        "experiment_materials":{"source_material_id"},
        "papers":{"topic_id"},
        "material_analysis_runs":{"topic_id","analysis_status","result_key","process_step_id"},
        "method_versions":{"version_label"},
        "integrated_analysis_sessions":{"simulation_run_ids"},
        "scientific_observations":{"parameter_id","normalized_value","source_type","review_status"},
        "measurement_review_events":{"review_status","reviewer","original_file_hash","observation_id"},
        "simulation_runs":{"idempotency_key"},
    }
    for table,columns in expected.items():
        assert columns <= {column["name"] for column in inspector.get_columns(table)}
    review_columns={column["name"]:column for column in inspector.get_columns("measurement_review_events")}
    assert review_columns["analysis_run_id"]["nullable"] is True
    assert review_columns["observation_id"]["nullable"] is True
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()=="0004_simulation_idempotency"
        assert connection.exec_driver_sql("SELECT parameter_id FROM scientific_observations WHERE id=7").scalar_one()=="temperature"
        assert connection.exec_driver_sql("SELECT reviewer FROM measurement_review_events WHERE id=9").scalar_one()=="old reviewer"
    assert any(index["name"]=="uq_simulation_run_idempotency_key" and index["unique"] for index in inspector.get_indexes("simulation_runs"))
    engine.dispose()
