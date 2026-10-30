from pathlib import Path
import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.getenv("LAB_PROCESS_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
DB_PATH = Path(os.getenv("LAB_PROCESS_DB_PATH",str(ROOT / "data" / "lab_process.db"))).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    # SQLite leaves FK checks disabled on every new connection unless enabled.
    # Register on Engine so test/in-memory SQLite engines get the same guarantee.
    if dbapi_connection.__class__.__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
