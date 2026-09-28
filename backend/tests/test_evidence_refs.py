import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.database import Base
from app.db.models import Paper, EvidenceChunk
from app.schemas.core import Claim
from app.services.evidence.claims import validate_claim_evidence

def test_citations_must_reference_existing_evidence(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'evidence.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        paper=Paper(title='test',authors='',filename='test.pdf');db.add(paper);db.flush()
        chunk=EvidenceChunk(paper_id=paper.id,page=1,text='recorded text',chunk_index=0);db.add(chunk);db.commit()
        assert validate_claim_evidence(db,Claim(claim='supported',status='SUPPORTED',evidence_ids=[chunk.id]))
        with pytest.raises(ValueError,match='Unknown evidence IDs'):
            validate_claim_evidence(db,Claim(claim='unsupported citation',status='SUPPORTED',evidence_ids=[99999]))
        assert validate_claim_evidence(db,Claim(claim='unknown',status='UNKNOWN'))
