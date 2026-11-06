"""Orquestador del pipeline completo. Independiente de la API: lo usan la CLI y el worker."""
from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf

from app.pipeline.analyze import analyze
from app.pipeline.fonts import FontResolver
from app.pipeline.ocr import ocr_available, ocr_segments
from app.pipeline.protect import Protector
from app.pipeline.rebuild import rebuild
from app.pipeline.translate import Cache, Translator, collect_proper_names, shorten_segments, translate_segments
from app.pipeline.types import PageInfo, Segment
from app.pipeline.validate import validate

log = logging.getLogger(__name__)

CREDITS_RE = re.compile(r"ISBN|©|copyright|all rights reserved|published by|publisher|editor|printed in|"
                        r"written by|illustrat|consultant|photograph|design(?:er|ed) by", re.I)
INVALID_FN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

STAGES = ["analyze", "ocr", "protect", "translate", "rebuild", "validate"]

ProgressFn = Callable[[str, int, int, int | None], None]  # etapa, hechos, total, página


class Cancelled(Exception):
    pass


@dataclass
class PipelineOptions:
    min_font_scale: float = 0.75
    min_font_size_pt: float = 5.5
    concurrency: int = 4
    batch_chars: int = 6000
    batch_items: int = 40
    fonts_dirs: str = ""
    only_pages: set[int] | None = None  # para pruebas: traducir solo estas páginas
    detect_names: bool = True
    ocr: bool = True
    visual_check: bool = True


@dataclass
class PipelineResult:
    output_pdf: Path
    report_path: Path
    report: dict
    pages: list[PageInfo] = field(default_factory=list)
    title: str = ""
    title_es: str = ""


def _plain(h: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", h or "")).strip()


def _title_segments(pages: list[PageInfo], doc: pymupdf.Document) -> tuple[list[Segment], Segment | None]:
    """(partes del título, subtítulo) de la portada: el bloque más grande, los bloques destacados pegados a
    él (p. ej. "THE SECRETS OF" + "ASTROLOGY") y el bloque de texto que sigue justo debajo (subtítulo)."""
    for info in pages[:6]:
        cands = [s for s in info.segments if s.action == "translate" and len(s.text) > 2]
        if not cands:
            continue
        top = max(cands, key=lambda s: s.style.size)
        ordered = sorted(cands, key=lambda s: s.bbox[1])
        i = ordered.index(top)
        title = [top]
        # bloques contiguos (arriba/abajo) en mayúsculas o grandes forman parte del título
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(ordered):
                s = ordered[j]
                near = abs((s.bbox[1] if step > 0 else s.bbox[3]) - (title[-1].bbox[3] if step > 0 else title[0].bbox[1]))
                if near < 0.6 * top.style.size and (s.text.isupper() or s.style.size >= 0.3 * top.style.size):
                    title = title + [s] if step > 0 else [s] + title
                    j += step
                else:
                    break
        below = [s for s in ordered if s.bbox[1] >= title[-1].bbox[3] - 1 and s not in title and len(s.text) > 10]
        subtitle = below[0] if below and below[0].bbox[1] - title[-1].bbox[3] < 1.5 * top.style.size else None
        return title, subtitle
    return [], None


def _sentence_case(t: str) -> str:
    """'LOS SECRETOS DE LA ASTROLOGÍA' -> 'Los secretos de la astrología' (solo si viene todo en mayúsculas)."""
    t = re.sub(r"\s+", " ", t).strip(" :.")
    if t.isupper():
        t = t.lower()
        t = t[:1].upper() + t[1:]
    return t


def spanish_filename(title_es: str, fallback: str) -> str:
    name = INVALID_FN_RE.sub("", title_es).strip(" .") or fallback
    name = re.sub(r"\s+", " ", name)
    return f"{name[:150].rstrip()} (ES).pdf"


def run_pipeline(
    input_pdf: Path,
    out_dir: Path,
    translator: Translator,
    cache: Cache,
    protected_terms: dict[str, str] | None = None,
    glossary: dict[str, str] | None = None,
    options: PipelineOptions | None = None,
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> PipelineResult:
    opts = options or PipelineOptions()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_extra: dict = {"advertencias": []}

    timings: dict[str, float] = {}
    current = {"stage": None, "t": time.time()}

    def tick(stage: str, done: int, total: int, page: int | None = None):
        if stage != current["stage"]:
            now = time.time()
            if current["stage"]:
                timings[current["stage"]] = round(timings.get(current["stage"], 0) + now - current["t"], 1)
                log.info("Etapa %s: %.1f s", current["stage"], now - current["t"])
            current["stage"], current["t"] = stage, now
        if should_stop and should_stop():
            raise Cancelled()
        if progress:
            progress(stage, done, total, page)

    # ---------------------------------------------------------------- análisis
    doc = pymupdf.open(input_pdf)
    if doc.is_encrypted:
        raise ValueError("El PDF está protegido con contraseña")
    tick("analyze", 0, len(doc))
    pages = analyze(doc)
    tick("analyze", len(doc), len(doc))

    # ---------------------------------------------------------------- OCR (solo donde hace falta)
    candidates = [p for p in pages if p.kind in ("image_only", "scanned", "mixed")
                  and (not opts.only_pages or p.number in opts.only_pages)]
    if candidates and opts.ocr:
        if ocr_available():
            from concurrent.futures import ThreadPoolExecutor

            from app.pipeline.ocr import ocr_lines_from_image, page_image

            # Tesseract es un proceso externo: varias páginas a la vez (el render se hace aquí, en serie)
            pool = ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1)))
            futures: dict[int, object] = {}
            ahead = 8  # páginas renderizadas por adelantado (limita la memoria: ~8 MB por página)

            def submit(j: int) -> None:
                if j < len(candidates) and candidates[j].number not in futures:
                    n = candidates[j].number
                    futures[n] = pool.submit(ocr_lines_from_image, page_image(doc[n - 1]))

            for j in range(ahead):
                submit(j)
            for i, info in enumerate(candidates):
                submit(i + ahead)
                tick("ocr", i, len(candidates), info.number)
                try:
                    found = ocr_segments(doc[info.number - 1], info, futures.pop(info.number).result())
                except Exception as e:  # noqa: BLE001
                    log.warning("OCR falló en la página %s: %s", info.number, e)
                    info.flag("No se pudo aplicar OCR a esta página")
                    continue
                # lo que ya es texto real del PDF (en cualquier orientación, también curvo) no se lee por OCR
                page = doc[info.number - 1]
                digital = [pymupdf.Rect(s.bbox) for s in info.segments]
                digital += [pymupdf.Rect(l["bbox"]) for b in page.get_text("dict")["blocks"] if b.get("type") == 0
                            for l in b["lines"] if l["spans"] and "".join(sp["text"] for sp in l["spans"]).strip()]
                found = [s for s in found
                         if sum(abs(pymupdf.Rect(s.bbox) & d) for d in digital) < 0.3 * abs(pymupdf.Rect(s.bbox))]
                if found:
                    info.segments.extend(found)
                    low = [s for s in found if (s.ocr_confidence or 0) < 85]
                    if low:
                        info.flag(f"Texto reconocido en una imagen con baja confianza ({len(low)} bloque(s)); "
                                  "revisar el resultado")
                    else:
                        report_extra["advertencias"].append(
                            f"Página {info.number}: se tradujo texto dentro de una imagen ({len(found)} bloque(s))")
            pool.shutdown(wait=False, cancel_futures=True)
            tick("ocr", len(candidates), len(candidates))
        else:
            report_extra["advertencias"].append(
                f"OCR no disponible: {len(candidates)} página(s) con imágenes grandes no se revisaron en busca "
                "de texto dentro de imágenes (ejecuta con Docker para habilitarlo).")
    if opts.only_pages:
        for p in pages:
            if p.number not in opts.only_pages:
                p.segments = []
                p.needs_review, p.review_reasons = False, []

    # ---------------------------------------------------------------- protección
    tick("protect", 0, 1)
    protector = Protector(protected_terms or {})
    if opts.detect_names:
        credit_texts = [" / ".join(s.text for s in p.segments) for p in pages
                        if p.segments and (p.number <= 4 or CREDITS_RE.search(" ".join(s.text for s in p.segments)))]
        for n in collect_proper_names(credit_texts[:12], translator):
            protector.add(n["text"], "BRAND" if str(n.get("type", "")).upper() == "BRAND" else "NAME")
    report_extra["terminos_protegidos"] = sorted(protector.terms)
    tick("protect", 1, 1)

    # ---------------------------------------------------------------- traducción
    segments = [s for p in pages for s in p.segments]
    title_segs, subtitle_seg = _title_segments(pages, doc)
    title = doc.metadata.get("title") or " ".join(s.text for s in title_segs)
    stats = translate_segments(
        segments, translator, cache, protector, glossary=glossary or {}, title=title,
        concurrency=opts.concurrency, max_chars=opts.batch_chars, max_items=opts.batch_items,
        on_progress=lambda d, t: tick("translate", d, t), should_stop=should_stop,
    )
    if should_stop and should_stop():
        raise Cancelled()
    title_es = _sentence_case(" ".join(_plain(s.translation) or s.text for s in title_segs))
    if subtitle_seg is not None:
        sub = (_plain(subtitle_seg.translation) or subtitle_seg.text).strip(" .:")
        title_es = f"{title_es} - {sub[:1].upper()}{sub[1:]}" if title_es else sub
    title_es = title_es or Path(input_pdf).stem

    # ---------------------------------------------------------------- reconstrucción
    fonts = FontResolver(doc, out_dir / "_fonts", opts.fonts_dirs)
    def shorten(segs, limits):
        shorten_segments(segs, limits, translator, cache, title, concurrency=opts.concurrency)

    # progreso: la mitad para preparar, la otra mitad para dibujar
    def on_page(n, phase):
        done = n if phase == "prepare" else len(pages) + n
        tick("rebuild", done, 2 * len(pages), n)

    rebuild(doc, pages, fonts, opts.min_font_scale, opts.min_font_size_pt, on_page=on_page, shorten=shorten)
    out_pdf = out_dir / spanish_filename(title_es, Path(input_pdf).stem + " ES")
    # No se usa doc.subset_fonts(): también vuelve a recortar las fuentes originales (subconjuntos CFF de
    # InDesign) y en algunos libros cambia sus glifos (un "81" pasaba a verse "28"). Cada fuente nueva se
    # incrusta una sola vez en el documento, así que el tamaño apenas crece.
    # garbage=1: elimina objetos sin uso sin renumerar. Con 2 o más (compactar/renumerar) algunos PDF de
    # InDesign pierden referencias (desaparecen números de página o fuentes); el tamaño es prácticamente igual.
    doc.save(out_pdf, garbage=1, deflate=True)
    doc.close()
    shutil.rmtree(out_dir / "_fonts", ignore_errors=True)

    # ---------------------------------------------------------------- validación
    tick("validate", 0, 1)
    report = validate(Path(input_pdf), out_pdf, pages, visual=opts.visual_check)
    report.update({
        "archivo_original": Path(input_pdf).name,
        "archivo_traducido": out_pdf.name,
        "titulo_original": title,
        "titulo_traducido": title_es,
        "estadisticas": {
            "segmentos_a_traducir": stats.total,
            "desde_cache": stats.cached,
            "traducidos": stats.translated,
            "fallidos": stats.failed,
            "llamadas_api": stats.api_calls,
            "segmentos_reducidos": sum(1 for s in segments if s.fit_scale and s.fit_scale < 0.999),
        },
        **report_extra,
    })
    timings["validate"] = round(time.time() - current["t"], 1)
    report["tiempos_por_etapa_s"] = timings
    report_path = out_dir / "reporte-traduccion.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tick("validate", 1, 1)
    return PipelineResult(out_pdf, report_path, report, pages, title, title_es)
