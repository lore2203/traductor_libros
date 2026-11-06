from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import GlossaryEntry, ProtectedTerm
from app.db.session import get_db

router = APIRouter(prefix="/api", tags=["terms"])


class TermIn(BaseModel):
    term: str = Field(min_length=2, max_length=512)
    category: str = "NAME"
    document_id: int | None = None


class GlossaryIn(BaseModel):
    source: str = Field(min_length=1, max_length=512)
    target: str = Field(min_length=1, max_length=512)
    document_id: int | None = None


@router.get("/protected-terms")
def list_terms(db: Session = Depends(get_db)):
    return [{"id": t.id, "term": t.term, "category": t.category, "origin": t.origin, "document_id": t.document_id}
            for t in db.query(ProtectedTerm).order_by(ProtectedTerm.term)]


@router.post("/protected-terms")
def add_term(body: TermIn, db: Session = Depends(get_db)):
    t = ProtectedTerm(term=body.term.strip(), category=body.category.upper(), origin="manual",
                      document_id=body.document_id)
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.delete("/protected-terms/{term_id}")
def delete_term(term_id: int, db: Session = Depends(get_db)):
    t = db.get(ProtectedTerm, term_id)
    if not t:
        raise HTTPException(404, "Término no encontrado.")
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.get("/glossary")
def list_glossary(db: Session = Depends(get_db)):
    return [{"id": g.id, "source": g.source, "target": g.target, "document_id": g.document_id}
            for g in db.query(GlossaryEntry).order_by(GlossaryEntry.source)]


@router.post("/glossary")
def add_glossary(body: GlossaryIn, db: Session = Depends(get_db)):
    g = GlossaryEntry(source=body.source.strip(), target=body.target.strip(), document_id=body.document_id)
    db.add(g)
    db.commit()
    return {"id": g.id}


@router.delete("/glossary/{entry_id}")
def delete_glossary(entry_id: int, db: Session = Depends(get_db)):
    g = db.get(GlossaryEntry, entry_id)
    if not g:
        raise HTTPException(404, "Entrada no encontrada.")
    db.delete(g)
    db.commit()
    return {"ok": True}
