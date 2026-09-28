from abc import ABC, abstractmethod
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.db.models import EvidenceChunk, Paper

class RetrievalProvider(ABC):
    @abstractmethod
    def search(self, db: Session, query: str, limit: int = 10): ...

class SQLiteFTSProvider(RetrievalProvider):
    """FTS5 retrieval with portable LIKE fallback for SQLite builds lacking FTS5."""
    def __init__(self): self._fts_ready = False
    def ensure_index(self, db: Session):
        if self._fts_ready: return
        try:
            db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(text, content='evidence_chunks', content_rowid='id')"))
            db.execute(text("INSERT INTO evidence_fts(evidence_fts) VALUES('rebuild')")); db.commit(); self._fts_ready = True
        except Exception:
            db.rollback()
    def search(self, db: Session, query: str, limit: int = 10):
        self.ensure_index(db)
        terms = [t for t in query.split() if t]
        if not terms: return []
        try:
            match_query = " OR ".join('"'+t.replace('"','')+'"' for t in terms)
            rows = db.execute(text("SELECT rowid, bm25(evidence_fts) AS rank FROM evidence_fts WHERE evidence_fts MATCH :q ORDER BY rank LIMIT :limit"), {"q":match_query,"limit":limit}).all()
            ids = [r.rowid for r in rows]; scores = {r.rowid: 1/(1+abs(float(r.rank))) for r in rows}
            chunks = db.query(EvidenceChunk).filter(EvidenceChunk.id.in_(ids)).all()
            order = {i:n for n,i in enumerate(ids)}
            chunks.sort(key=lambda c: order[c.id])
            return [self._format(db,c,scores[c.id]) for c in chunks]
        except Exception:
            q = "%"+terms[0]+"%"
            chunks = db.query(EvidenceChunk).filter(EvidenceChunk.text.ilike(q)).limit(limit).all()
            return [self._format(db,c,0.1) for c in chunks]
    @staticmethod
    def _format(db,c,score):
        p=db.get(Paper,c.paper_id)
        return {"evidence_id":c.id,"paper_id":c.paper_id,"paper_title":p.title if p else "Unknown","page":c.page,"section":c.section,"text":c.text,"relevance_score":score,"source_type":"paper"}
