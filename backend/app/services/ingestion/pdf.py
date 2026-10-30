import re
import pymupdf
from sqlalchemy.orm import Session
from app.db.models import Paper, EvidenceChunk


MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 500


def ingest_pdf(db: Session, payload: bytes, filename: str, title: str | None = None, authors: str = "", year: int | None = None):
    if not payload:
        raise ValueError("The uploaded PDF is empty.")
    if len(payload) > MAX_PDF_SIZE_BYTES:
        raise ValueError(f"PDF exceeds the {MAX_PDF_SIZE_BYTES // (1024 * 1024)} MB upload limit.")
    safe_filename = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not safe_filename:
        raise ValueError("A PDF filename is required.")

    with pymupdf.open(stream=payload, filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if doc.page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page processing limit.")

        paper=Paper(title=title or safe_filename.rsplit('.',1)[0],authors=authors,year=year,filename=safe_filename)
        db.add(paper); db.flush()
        idx=0
        for page_no,page in enumerate(doc,1):
            raw=page.get_text("text")
            section=None
            for block in re.split(r"\n\s*\n",raw):
                text=" ".join(block.split())
                if not text: continue
                if len(text)<100 and text.isupper(): section=text
                for start in range(0,len(text),1000):
                    piece=text[start:start+1000].strip()
                    if piece:
                        db.add(EvidenceChunk(paper_id=paper.id,page=page_no,section=section,text=piece,chunk_index=idx)); idx+=1
        # The caller owns the transaction so Paper, chunks, summary, and topic
        # association can commit or roll back together.
        db.flush()
        return paper
