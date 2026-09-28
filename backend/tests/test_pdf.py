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
