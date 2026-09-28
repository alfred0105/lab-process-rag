from sqlalchemy.orm import Session
from app.db.models import EvidenceChunk
from app.schemas.core import Claim, EvidenceStatus

def validate_claim_evidence(db: Session, claim: Claim) -> Claim:
    """Ensure every supplied citation points to an existing paper evidence chunk."""
    if claim.status == EvidenceStatus.UNKNOWN:
        return claim
    found = {row[0] for row in db.query(EvidenceChunk.id).filter(EvidenceChunk.id.in_(claim.evidence_ids)).all()}
    missing = sorted(set(claim.evidence_ids) - found)
    if missing:
        raise ValueError(f"Unknown evidence IDs: {missing}")
    return claim
