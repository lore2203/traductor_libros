"""Worker local: toma trabajos de la cola (tabla jobs en SQLite) y ejecuta el pipeline.

python -m app.worker
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy import select, text

from app.config import get_settings
from app.db.cache import SqlCache
from app.db.models import Document, GlossaryEntry, Job, Page, ProtectedTerm, Segment
from app.db.session import SessionLocal
from app.pipeline.runner import Cancelled, PipelineOptions, run_pipeline
from app.pipeline.translate import DeepSeekTranslator, FakeTranslator, FatalAPIError

log = logging.getLogger("worker")

# peso de cada etapa en el progreso global (%)
STAGE_WEIGHTS = {"analyze": (0, 4), "ocr": (4, 10), "protect": (10, 12), "translate": (12, 78),
                 "rebuild": (78, 93), "validate": (93, 100)}


def friendly_error(e: Exception) -> str:
    msg = str(e)
    if isinstance(e, FatalAPIError):
        if "DEEPSEEK_API_KEY" in msg:
            return "El servicio de traducción no está configurado (falta la llave de DeepSeek)."
        if "401" in msg:
            return "La llave de DeepSeek no es válida. Revisa la configuración."
        if "402" in msg:
            return "La cuenta de DeepSeek no tiene saldo suficiente."
        return "El servicio de traducción rechazó la solicitud. Revisa la configuración."
    if "contraseña" in msg:
        return msg
    return "Ocurrió un error inesperado al procesar el libro. Puedes intentar reanudar el proceso."


def claim_job() -> int | None:
    with SessionLocal() as s:
        row = s.execute(text(
            "UPDATE jobs SET status='running', error=NULL WHERE id = ("
            "SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1) AND status='queued' RETURNING id"
        )).first()
        s.commit()
        return row[0] if row else None


def save_results(s, job: Job, pages) -> None:
    s.query(Page).filter(Page.job_id == job.id).delete()
    for info in pages:
        page = Page(job_id=job.id, number=info.number, width=info.width, height=info.height,
                    rotation=info.rotation, kind=info.kind, image_count=info.image_count,
                    drawing_count=info.drawing_count, status="done", needs_review=info.needs_review,
                    review_reasons=info.review_reasons)
        page.segments = [Segment(seg_key=sg.key, bbox=list(sg.bbox), block_type=sg.block_type,
                                 style=sg.style.to_dict(), source_text=sg.text, source_html=sg.html,
                                 protected_text=sg.protected, placeholders=sg.placeholders,
                                 translation=sg.translation, action=sg.action, status="done",
                                 fit_scale=sg.fit_scale, issues=sg.issues, ocr_confidence=sg.ocr_confidence)
                         for sg in info.segments]
        s.add(page)


def process(job_id: int) -> None:
    st = get_settings()
    s = SessionLocal()
    job = s.get(Job, job_id)
    doc: Document = job.document
    last_commit = [0.0]
    last_check = [0.0, False]

    def should_stop() -> bool:
        now = time.time()
        if now - last_check[0] > 2:
            last_check[0] = now
            with SessionLocal() as s2:
                status = s2.execute(select(Job.status).where(Job.id == job_id)).scalar()
            last_check[1] = status in ("cancelled", "paused")
        return last_check[1]

    def progress(stage: str, done: int, total: int, page: int | None) -> None:
        a, b = STAGE_WEIGHTS.get(stage, (0, 100))
        job.stage = stage
        job.progress = round(a + (b - a) * (done / total if total else 1), 1)
        if page:
            job.current_page = page
        now = time.time()
        if now - last_commit[0] > 1 or done == total:
            last_commit[0] = now
            s.commit()

    try:
        if st.fake_translator:
            translator = FakeTranslator()
        else:
            translator = DeepSeekTranslator(st.deepseek_api_key, st.deepseek_model, st.deepseek_base_url,
                                            thinking=st.deepseek_thinking)
        terms = {t.term: t.category for t in s.scalars(select(ProtectedTerm).where(
            (ProtectedTerm.document_id.is_(None)) | (ProtectedTerm.document_id == doc.id)))}
        glossary = {g.source: g.target for g in s.scalars(select(GlossaryEntry).where(
            (GlossaryEntry.document_id.is_(None)) | (GlossaryEntry.document_id == doc.id)))}
        opts = PipelineOptions(min_font_scale=st.min_font_scale, min_font_size_pt=st.min_font_size_pt,
                               concurrency=st.translation_concurrency, batch_chars=st.translation_batch_chars,
                               batch_items=st.translation_batch_max_segments, fonts_dirs=st.fonts_dirs,
                               detect_names=not st.fake_translator)
        out_dir = st.outputs_dir / f"job_{job.id}"
        result = run_pipeline(Path(doc.path), out_dir, translator, SqlCache(SessionLocal()), terms, glossary,
                              opts, progress, should_stop)
        save_results(s, job, result.pages)
        doc.title, doc.title_es = result.title, result.title_es
        job.output_path, job.report_path = str(result.output_pdf), str(result.report_path)
        job.status, job.stage, job.progress = "done", "done", 100.0
        s.commit()
        log.info("Trabajo %s terminado: %s", job.id, result.output_pdf)
    except Cancelled:
        s.rollback()
        job = s.get(Job, job_id)
        log.info("Trabajo %s detenido (%s)", job_id, job.status)
    except Exception as e:  # noqa: BLE001
        log.exception("Trabajo %s falló", job_id)
        s.rollback()
        job = s.get(Job, job_id)
        job.status, job.error = "failed", friendly_error(e)
        s.commit()
    finally:
        s.close()


def recover_orphans() -> None:
    """Trabajos que quedaron 'running' tras un reinicio vuelven a la cola (la caché evita repetir costos)."""
    with SessionLocal() as s:
        s.execute(text("UPDATE jobs SET status='queued' WHERE status='running'"))
        s.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    recover_orphans()
    log.info("Worker iniciado, esperando trabajos...")
    while True:
        job_id = claim_job()
        if job_id is None:
            time.sleep(2)
            continue
        log.info("Procesando trabajo %s", job_id)
        process(job_id)


if __name__ == "__main__":
    main()
