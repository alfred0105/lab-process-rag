from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.database import Base
from app.services.ingestion.pdf import ingest_pdf
import pymupdf

def test_pdf_chunks_keep_page_provenance(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'pdf-test.db'}")
    Base.metadata.create_all(engine)
    pdf=pymupdf.open()
    pdf.new_page().insert_text((72,72),'First page evidence about temperature.')
    pdf.new_page().insert_text((72,72),'Second page evidence about concentration.')
    with Session(engine) as db:
        paper=ingest_pdf(db,pdf.tobytes(),'fixture.pdf')
        assert len(paper.chunks)==2
        assert [c.page for c in paper.chunks]==[1,2]
    pdf.close()

def test_pdf_ingestion_is_part_of_callers_transaction(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'pdf-rollback.db'}")
    Base.metadata.create_all(engine)
    pdf=pymupdf.open(); pdf.new_page().insert_text((72,72),'Evidence that should roll back.')
    with Session(engine) as db:
        ingest_pdf(db,pdf.tobytes(),'fixture.pdf')
        db.rollback()
        from app.db.models import Paper, EvidenceChunk
        assert db.query(Paper).count() == 0
        assert db.query(EvidenceChunk).count() == 0
    pdf.close()

def test_pdf_upload_limits_and_unsafe_path_are_rejected(tmp_path):
    from app.services.ingestion.pdf import MAX_PDF_SIZE_BYTES
    import pytest
    engine=create_engine(f"sqlite:///{tmp_path/'pdf-invalid.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(ValueError, match='filename'):
            ingest_pdf(db,b'%PDF-1.4','')
        with pytest.raises(ValueError, match='50 MB'):
            ingest_pdf(db,b'x'*(MAX_PDF_SIZE_BYTES+1),'large.pdf')
        pdf=pymupdf.open(); pdf.new_page().insert_text((72,72),'Valid page.')
        paper=ingest_pdf(db,pdf.tobytes(),'../safe.pdf')
        assert paper.filename == 'safe.pdf'
        pdf.close()

def test_sqlite_foreign_key_checks_are_enabled_for_new_connections(tmp_path):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.db.models import EvidenceChunk
    engine=create_engine(f"sqlite:///{tmp_path/'foreign-keys.db'}")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one() == 1
    with Session(engine) as db:
        db.add(EvidenceChunk(paper_id=987654,page=1,section=None,text='orphan',chunk_index=0))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
