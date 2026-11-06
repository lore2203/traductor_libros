from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Document, Job, Page
from app.db.session import SessionLocal, get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

STAGES = [("upload", "Carga"), ("analyze", "Análisis"), ("ocr", "OCR"), ("protect", "Protección"), ("translate", "Traducción"),
          ("rebuild", "Maquetación"), ("validate", "Validación"), ("done", "Descarga")]
STAGE_INDEX = {k: i for i, (k, _) in enumerate(STAGES)}


def _job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "No encontramos ese trabajo.")
    return job


def job_status(job: Job) -> dict:
    current = STAGE_INDEX.get(job.stage, 0)
    stages = []
    for i, (key, label) in enumerate(STAGES):
        if job.status == "done" or i < current:
            state = "completed"
        elif i == current:
            state = {"running": "in_progress", "queued": "pending", "failed": "error",
                     "cancelled": "cancelled", "paused": "paused"}.get(job.status, "pending")
        else:
            state = "pending"
        stages.append({"key": key, "label": label, "state": state})
    review = [{"page": p.number, "reasons": p.review_reasons} for p in job.pages if p.needs_review]
    return {
        "id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "current_page": job.current_page,
        "page_count": job.document.page_count,
        "original_name": job.document.original_name,
        "title_es": job.document.title_es,
        "output_name": Path(job.output_path).name if job.output_path else None,
        "error": job.error,
        "stages": stages,
        "review_pages": review,
    }


@router.post("")
async def create_job(
    file: UploadFile = File(...),
    rights_confirmed: bool = Form(...),
    source_lang: str = Form("en"),
    target_lang: str = Form("es"),
    db: Session = Depends(get_db),
):
    st = get_settings()
    if not rights_confirmed:
        raise HTTPException(400, "Debes confirmar que tienes derechos de uso sobre el libro.")
    if (source_lang, target_lang) != ("en", "es"):
        raise HTTPException(400, "Por ahora solo se admite traducción de inglés a español.")
    data = await file.read(st.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > st.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"El archivo supera el límite de {st.max_upload_mb} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "El archivo no es un PDF válido.")
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise HTTPException(400, "No pudimos abrir el PDF. Puede estar dañado.")
    if pdf.is_encrypted or pdf.needs_pass:
        raise HTTPException(400, "El PDF está protegido con contraseña. Sube una versión sin protección.")
    if len(pdf) == 0:
        raise HTTPException(400, "El PDF no tiene páginas.")

    sha = hashlib.sha256(data).hexdigest()
    folder = st.uploads_dir / sha
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "original.pdf"
    if not path.exists():
        path.write_bytes(data)
    doc = Document(original_name=file.filename or "libro.pdf", path=str(path), sha256=sha, page_count=len(pdf))
    db.add(doc)
    db.flush()
    job = Job(document_id=doc.id, status="queued", stage="analyze", source_lang=source_lang, target_lang=target_lang)
    db.add(job)
    db.commit()
    return job_status(job)


@router.get("")
def list_jobs(db: Session = Depends(get_db)):
    return [job_status(j) for j in db.query(Job).order_by(Job.id.desc()).limit(50)]


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    return job_status(_job_or_404(db, job_id))


@router.get("/{job_id}/events")
async def job_events(job_id: int):
    """Progreso en tiempo real (Server-Sent Events)."""

    async def gen():
        last = None
        while True:
            with SessionLocal() as s:
                job = s.get(Job, job_id)
                if not job:
                    yield "event: error\ndata: {}\n\n"
                    return
                payload = json.dumps(job_status(job), ensure_ascii=False)
                status = job.status
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if status in ("done", "failed", "cancelled"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status in ("queued", "running"):
        job.status = "cancelled"
        db.commit()
    return job_status(job)


@router.post("/{job_id}/resume")
def resume_job(job_id: int, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status in ("cancelled", "failed", "paused"):
        job.status, job.error = "queued", None
        db.commit()
    return job_status(job)


@router.get("/{job_id}/download")
def download(job_id: int, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if job.status != "done" or not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(409, "El libro traducido todavía no está listo.")
    return FileResponse(job.output_path, media_type="application/pdf", filename=Path(job.output_path).name)


@router.get("/{job_id}/report")
def report(job_id: int, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    if not job.report_path or not Path(job.report_path).exists():
        raise HTTPException(409, "El reporte todavía no está listo.")
    return FileResponse(job.report_path, media_type="application/json", filename="reporte-traduccion.json")


@router.get("/{job_id}/pages/{number}/preview")
def preview(job_id: int, number: int, version: str = "translated", dpi: int = 80, db: Session = Depends(get_db)):
    job = _job_or_404(db, job_id)
    path = job.document.path if version == "original" else job.output_path
    if not path or not Path(path).exists():
        raise HTTPException(409, "La vista previa todavía no está disponible.")
    pdf = pymupdf.open(path)
    if not 1 <= number <= len(pdf):
        raise HTTPException(404, "Esa página no existe.")
    png = pdf[number - 1].get_pixmap(dpi=max(30, min(dpi, 200))).tobytes("png")
    return Response(png, media_type="image/png")


@router.get("/{job_id}/pages")
def pages(job_id: int, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    rows = db.query(Page).filter(Page.job_id == job_id).order_by(Page.number)
    return [{"number": p.number, "kind": p.kind, "needs_review": p.needs_review, "reasons": p.review_reasons}
            for p in rows]
