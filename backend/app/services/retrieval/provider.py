from abc import ABC, abstractmethod
from sqlalchemy import String, cast, text
from sqlalchemy.orm import Session
from app.db.models import EvidenceChunk, Paper, PaperSummary

class RetrievalProvider(ABC):
    @abstractmethod
    def search(self, db: Session, query: str, limit: int = 10, topic_id: int | None = None): ...

class SQLiteFTSProvider(RetrievalProvider):
    """FTS5 retrieval with portable LIKE fallback for SQLite builds lacking FTS5."""
    def __init__(self): self._fts_ready = False
    def ensure_index(self, db: Session):
        if self._fts_ready: return
        try:
            db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(text, content='evidence_chunks', content_rowid='id')"))
            db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS paper_summary_fts USING fts5(summary, topics, content='paper_summaries', content_rowid='id')"))
            db.execute(text("INSERT INTO evidence_fts(evidence_fts) VALUES('rebuild')"))
            db.execute(text("INSERT INTO paper_summary_fts(paper_summary_fts) VALUES('rebuild')")); db.commit(); self._fts_ready = True
        except Exception:
            db.rollback()
    def search(self, db: Session, query: str, limit: int = 10, topic_id: int | None = None):
        self.ensure_index(db)
        terms = [t for t in query.split() if t]
        if not terms: return []
        try:
            match_query = " OR ".join('"'+t.replace('"','')+'"' for t in terms)
            if topic_id is None:
                summary_sql="SELECT rowid, bm25(paper_summary_fts) AS rank FROM paper_summary_fts WHERE paper_summary_fts MATCH :q ORDER BY rank LIMIT :limit"
                summary_params={"q":match_query,"limit":limit}
                full_sql="SELECT rowid, bm25(evidence_fts) AS rank FROM evidence_fts WHERE evidence_fts MATCH :q ORDER BY rank LIMIT :limit"
                full_params=summary_params
            else:
                summary_sql="SELECT ps.id AS rowid, bm25(paper_summary_fts) AS rank FROM paper_summary_fts JOIN paper_summaries ps ON ps.id=paper_summary_fts.rowid JOIN papers p ON p.id=ps.paper_id WHERE paper_summary_fts MATCH :q AND p.topic_id=:topic_id ORDER BY rank LIMIT :limit"
                summary_params={"q":match_query,"limit":limit,"topic_id":topic_id}
                full_sql="SELECT ec.id AS rowid, bm25(evidence_fts) AS rank FROM evidence_fts JOIN evidence_chunks ec ON ec.id=evidence_fts.rowid JOIN papers p ON p.id=ec.paper_id WHERE evidence_fts MATCH :q AND p.topic_id=:topic_id ORDER BY rank LIMIT :limit"
                full_params=summary_params
            summary_rows = db.execute(text(summary_sql), summary_params).all()
            summary_ids = [row.rowid for row in summary_rows]
            summary_scores = {row.rowid: 2.0/(1+abs(float(row.rank))) for row in summary_rows}
            summary_query=db.query(PaperSummary).filter(PaperSummary.id.in_(summary_ids)) if summary_ids else None
            if summary_query is not None and topic_id is not None: summary_query=summary_query.join(Paper).filter(Paper.topic_id==topic_id)
            summaries=summary_query.all() if summary_query is not None else []
            summary_chunk_ids = []
            summary_chunk_scores = {}
            for summary in summaries:
                for chunk_id in summary.source_chunk_ids:
                    if chunk_id not in summary_chunk_scores:
                        summary_chunk_ids.append(chunk_id)
                        summary_chunk_scores[chunk_id] = summary_scores[summary.id]
            rows = db.execute(text(full_sql), full_params).all()
            direct_ids = [row.rowid for row in rows]
            scores = {row.rowid: 1/(1+abs(float(row.rank))) for row in rows}
            # Summary matches identify papers; direct full-text matches are the
            # first passages opened for the answer. Summary-linked excerpts fill
            # remaining slots when they reveal relevant papers with different wording.
            ids = list(dict.fromkeys(direct_ids + summary_chunk_ids))
            chunk_query=db.query(EvidenceChunk).filter(EvidenceChunk.id.in_(ids)) if ids else None
            if chunk_query is not None and topic_id is not None: chunk_query=chunk_query.join(Paper).filter(Paper.topic_id==topic_id)
            chunks=chunk_query.all() if chunk_query is not None else []
            order = {chunk_id:index for index,chunk_id in enumerate(ids)}
            chunks.sort(key=lambda chunk: order[chunk.id])
            return [self._format(db,chunk,max(scores.get(chunk.id,0),summary_chunk_scores.get(chunk.id,0)),"paper summary" if chunk.id in summary_chunk_scores else "full text") for chunk in chunks[:limit]]
        except Exception:
            q = "%"+terms[0]+"%"
            chunk_query=db.query(EvidenceChunk).join(Paper).filter(EvidenceChunk.text.ilike(q))
            if topic_id is not None: chunk_query=chunk_query.filter(Paper.topic_id==topic_id)
            chunks = chunk_query.limit(limit).all()
            if len(chunks)<limit:
                summary_query=db.query(PaperSummary).join(Paper).filter(PaperSummary.summary.ilike(q)|cast(PaperSummary.topics,String).ilike(q))
                if topic_id is not None: summary_query=summary_query.filter(Paper.topic_id==topic_id)
                summaries=summary_query.limit(limit-len(chunks)).all()
                extra_ids=[chunk_id for summary in summaries for chunk_id in summary.source_chunk_ids]
                extra=db.query(EvidenceChunk).filter(EvidenceChunk.id.in_(extra_ids)).all() if extra_ids else []
                seen={chunk.id for chunk in chunks}; chunks += [chunk for chunk in extra if chunk.id not in seen]
            return [self._format(db,chunk,0.1) for chunk in chunks[:limit]]
    @staticmethod
    def _format(db,c,score,retrieved_via="full text"):
        p=db.get(Paper,c.paper_id)
        return {"evidence_id":c.id,"paper_id":c.paper_id,"paper_title":p.title if p else "Unknown","page":c.page,"section":c.section,"text":c.text,"relevance_score":score,"source_type":"paper","retrieved_via":retrieved_via}
