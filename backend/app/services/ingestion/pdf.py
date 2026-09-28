import re
import pymupdf
from sqlalchemy.orm import Session
from app.db.models import Paper, EvidenceChunk

def ingest_pdf(db: Session, payload: bytes, filename: str, title: str | None = None, authors: str = "", year: int | None = None):
    doc = pymupdf.open(stream=payload, filetype="pdf")
    paper=Paper(title=title or filename.rsplit('.',1)[0],authors=authors,year=year,filename=filename)
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
    db.commit(); db.refresh(paper)
    return paper
