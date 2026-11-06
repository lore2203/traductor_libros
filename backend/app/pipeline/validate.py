"""Validación automática del PDF traducido frente al original y generación del reporte."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw

from app.pipeline.protect import PLACEHOLDER_RE
from app.pipeline.types import PageInfo

WS_RE = re.compile(r"\s+")


def _norm(t: str) -> str:
    return WS_RE.sub("", t)


def _render(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False, annots=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _visual_diff_outside_text(p_orig: pymupdf.Page, p_new: pymupdf.Page, info: PageInfo, dpi: int = 40) -> float:
    """Fracción de píxeles que cambian FUERA de las zonas de texto (debería ser ~0)."""
    a, b = _render(p_orig, dpi), _render(p_new, dpi)
    if a.size != b.size:
        return 1.0
    k = dpi / 72.0
    mask = Image.new("L", a.size, 255)
    draw = ImageDraw.Draw(mask)
    zones = [pymupdf.Rect(s.bbox) for s in info.segments]
    for blk in p_new.get_text("blocks"):
        zones.append(pymupdf.Rect(blk[:4]))
    for r in zones:
        draw.rectangle([r.x0 * k - 3, r.y0 * k - 3, r.x1 * k + 3, r.y1 * k + 3], fill=0)
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 40 else 0)
    diff = ImageChops.multiply(diff, mask)
    changed = sum(diff.histogram()[1:])
    total = sum(mask.histogram()[1:]) or 1
    return changed / total


def validate(original: Path, translated: Path, pages: list[PageInfo], visual: bool = True) -> dict:
    checks: dict[str, bool] = {}
    warnings: list[str] = []
    errors: list[str] = []
    a = pymupdf.open(original)
    try:
        b = pymupdf.open(translated)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errores": [f"El PDF traducido no abre: {e}"], "validaciones": {"abre": False}}
    checks["abre_correctamente"] = True
    try:
        from pypdf import PdfReader
        PdfReader(str(translated)).pages[0]
        checks["abre_con_pypdf"] = True
    except Exception as e:  # noqa: BLE001
        checks["abre_con_pypdf"] = False
        errors.append(f"pypdf no puede leer el archivo: {e}")

    checks["mismo_numero_de_paginas"] = len(a) == len(b)
    if not checks["mismo_numero_de_paginas"]:
        errors.append(f"El original tiene {len(a)} páginas y el traducido {len(b)}")

    dims_ok = blanks_ok = images_ok = vectors_ok = protected_ok = no_markers = complete = kept_ok = True
    for info in pages:
        i = info.number - 1
        if i >= len(b):
            break
        pa, pb = a[i], b[i]
        if (round(pa.rect.width, 1), round(pa.rect.height, 1), pa.rotation) != \
                (round(pb.rect.width, 1), round(pb.rect.height, 1), pb.rotation):
            dims_ok = False
            info.flag("El tamaño u orientación de la página cambió")
        if info.kind == "blank":
            if _norm(pb.get_text()) or pb.get_image_info() or pb.get_cdrawings():
                blanks_ok = False
                info.flag("La página estaba vacía y ya no lo está")
            continue
        if len(pa.get_image_info()) != len(pb.get_image_info()):
            images_ok = False
            info.flag("Cambió el número de imágenes de la página")
        if len(pb.get_cdrawings()) < len(pa.get_cdrawings()):
            vectors_ok = False
            info.flag("Faltan elementos gráficos vectoriales")
        text_b = pb.get_text()
        if PLACEHOLDER_RE.search(text_b):
            no_markers = False
            info.flag("Quedaron marcadores internos sin restaurar")
        nb = _norm(text_b)
        # lo que se conserva sin traducir (números de capítulo y página, símbolos, íconos) debe seguir ahí
        chars_b = [(c["c"], pymupdf.Rect(c["bbox"])) for blk in pb.get_text("rawdict")["blocks"]
                   if blk.get("type") == 0 for l in blk["lines"] for sp in l["spans"] for c in sp["chars"]]
        for s in info.segments:
            if s.action != "keep":
                continue
            box = pymupdf.Rect(s.bbox)
            need = [ch for ch in s.text if not ch.isspace()]
            have = [c for c, r in chars_b if abs(r & box) > 0.3 * abs(r)]
            if any(have.count(ch) < need.count(ch) for ch in set(need)):
                kept_ok = False
                info.flag(f"Se perdió un elemento que debía conservarse: «{s.text[:20]}» ({s.key})")
        for s in info.segments:
            if s.action == "translate" and not s.translation:
                complete = False
                info.flag(f"Bloque sin traducir ({s.key})")
            if s.action == "review":
                info.flag(f"Bloque que no se pudo traducir ({s.key})")
            for value in s.placeholders.values():
                if _norm(value) not in nb:
                    protected_ok = False
                    info.flag(f"No se encontró el término protegido «{value}»")
            for issue in s.issues:
                if issue.startswith(("los términos protegidos", "falta el término", "los números no coinciden",
                                     "posible texto sin traducir", "longitud sospechosa", "traducción vacía")):
                    info.flag(f"{issue} ({s.key})")
        # texto fuera de la página (solo si el original no lo tenía ya)
        def _outside(pg):
            return sum(1 for blk in pg.get_text("blocks") if not pymupdf.Rect(blk[:4]).is_empty
                       and abs(pymupdf.Rect(blk[:4]) & pg.rect) < 0.98 * abs(pymupdf.Rect(blk[:4])))
        if _outside(pb) > _outside(pa):
            info.flag("Hay texto que sale de los bordes de la página")
        if visual and info.segments:
            frac = _visual_diff_outside_text(pa, pb, info)
            if frac > 0.01:
                info.flag(f"Posible cambio en imágenes o gráficos ({frac:.1%} de la zona no textual)")

    checks.update({
        "mismas_dimensiones": dims_ok,
        "paginas_vacias_conservadas": blanks_ok,
        "imagenes_conservadas": images_ok,
        "graficos_vectoriales_conservados": vectors_ok,
        "terminos_protegidos_intactos": protected_ok,
        "sin_marcadores_residuales": no_markers,
        "traduccion_completa": complete,
        "elementos_conservados_intactos": kept_ok,
    })
    review = [{"pagina": p.number, "motivos": p.review_reasons} for p in pages if p.needs_review]
    ok_pages = [p.number for p in pages if not p.needs_review]
    return {
        "ok": all(checks.values()) and not errors,
        "validaciones": checks,
        "paginas_totales": len(b),
        "paginas_correctas": ok_pages,
        "paginas_para_revision": review,
        "errores": errors,
        "advertencias": warnings,
    }
