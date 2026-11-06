"""OCR para texto que vive dentro de imágenes (portadas, páginas escaneadas, ilustraciones con texto).

Flujo:
1. Solo se aplica a páginas sin texto digital o con imágenes grandes (nunca a texto digital: sería menos preciso).
2. Tesseract localiza líneas de texto con coordenadas y confianza.
3. Las líneas se agrupan en párrafos y se convierten en segmentos 'ocr' (con color y tamaño estimados).
4. En la reconstrucción, el texto original se borra de la imagen con inpainting (OpenCV) y la imagen
   se reemplaza dentro del PDF; luego se escribe la traducción encima con el motor de maquetación.
Las páginas con OCR siempre se marcan para revisión.
"""
from __future__ import annotations

import io
import logging
import re
import shutil
import statistics
from dataclasses import dataclass

import pymupdf

from app.pipeline.types import PageInfo, Segment, Style

log = logging.getLogger(__name__)

OCR_DPI = 200
MIN_CONF = 55
LETTERS_RE = re.compile(r"[A-Za-z]")


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


@dataclass
class OcrLine:
    text: str
    rect: pymupdf.Rect  # coordenadas PDF
    conf: float
    height: float  # alto de la línea en pt
    rotation: int = 0  # 0 horizontal; 90 vertical ascendente; 270 vertical descendente


def _page_pixmap(page: pymupdf.Page) -> pymupdf.Pixmap:
    return page.get_pixmap(dpi=OCR_DPI, alpha=False)


def page_image(page: pymupdf.Page):
    """Render de la página para el OCR (se hace en el hilo principal: PyMuPDF no es seguro entre hilos)."""
    from PIL import Image

    pix = _page_pixmap(page)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def ocr_lines(page: pymupdf.Page) -> list[OcrLine]:
    return ocr_lines_from_image(page_image(page))


def ocr_lines_from_image(img) -> list[OcrLine]:
    """Tesseract sobre una imagen ya renderizada (puede ejecutarse en paralelo en varios hilos)."""
    import pytesseract
    from PIL import Image

    k = 72.0 / OCR_DPI
    W, H = img.size
    lines: dict[tuple, list] = {}

    def to_page(x, y, w, h, rot):
        """Caja en la imagen girada -> caja en la página."""
        if rot == 0:
            return pymupdf.Rect(x * k, y * k, (x + w) * k, (y + h) * k)
        if rot == 270:  # la imagen se giró 90° antihorario: (x', y') -> (W - y', x')
            return pymupdf.Rect((W - y - h) * k, x * k, (W - y) * k, (x + w) * k)
        return pymupdf.Rect(y * k, (H - x - w) * k, (y + h) * k, (H - x) * k)  # giro horario

    inverted = Image.eval(img, lambda v: 255 - v)
    # psm 11: texto disperso (portadas, ilustraciones); también imagen invertida y texto vertical
    # (la imagen girada 90°/270° convierte el texto vertical en horizontal para Tesseract)
    passes = [(img, 0), (inverted, 0), (img.rotate(90, expand=True), 270), (img.rotate(270, expand=True), 90)]
    for n, (variant, rot) in enumerate(passes):
        data = pytesseract.image_to_data(variant, lang="eng", config="--psm 11",
                                         output_type=pytesseract.Output.DICT)
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            conf = float(data["conf"][i])
            if not word or conf < MIN_CONF or not LETTERS_RE.search(word):
                continue
            key = (n, rot, data["block_num"][i], data["par_num"][i], data["line_num"][i])
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            lines.setdefault(key, []).append((word, to_page(x, y, w, h, rot), conf, h * k))
    result: list[OcrLine] = []
    for key, words in sorted(lines.items(), key=lambda kv: kv[0][1] != 0):  # primero las horizontales
        rot = key[1]
        rect = pymupdf.Rect(words[0][1])
        for _, r, _, _ in words[1:]:
            rect |= r
        text = re.sub(r"\s*[:;|]+$", "", " ".join(w for w, _, _, _ in words))
        conf = statistics.mean(c for _, _, c, _ in words)
        if not _looks_like_text(text, conf):
            continue  # ruido de ilustraciones
        # descartar duplicados (misma línea encontrada en imagen normal e invertida)
        if any(abs(rect & o.rect) > 0.5 * abs(rect) for o in result):
            continue
        result.append(OcrLine(text, rect, conf, statistics.median(hh for _, _, _, hh in words), rot))
    result.sort(key=lambda l: (l.rect.y0, l.rect.x0))
    return result


def _looks_like_text(text: str, conf: float) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", text)
    if len(letters) < 5 or conf < 75:
        return False
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) >= 3]
    if not words:
        return False
    vowel_words = [w for w in words if re.search(r"[aeiouyAEIOUY]", w)]
    return len(vowel_words) >= 0.6 * len(words)


def _colors(pix: pymupdf.Pixmap, rect: pymupdf.Rect) -> tuple[str, tuple[int, int, int], float]:
    """(color del texto en hex, color de fondo, densidad de tinta) estimados dentro del rectángulo."""
    import numpy as np

    k = OCR_DPI / 72.0
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    x0, y0 = max(0, int(rect.x0 * k)), max(0, int(rect.y0 * k))
    x1, y1 = min(pix.width, int(rect.x1 * k)), min(pix.height, int(rect.y1 * k))
    box = arr[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    if box.size == 0:
        return "#000000", (255, 255, 255), 0.0
    ring = np.concatenate([arr[max(0, y0 - 4):y0, x0:x1].reshape(-1, 3), arr[y1:y1 + 4, x0:x1].reshape(-1, 3)])
    bg = np.median(ring if ring.size else box, axis=0)
    dist = np.abs(box - bg).sum(axis=1)
    fg = box[dist >= np.percentile(dist, 85)] if len(box) > 10 else box
    if fg.size == 0:
        fg = box
    c = np.clip(np.nan_to_num(np.median(fg, axis=0)), 0, 255).astype(int)
    ink = float((np.abs(box - c).sum(axis=1) < 90).mean())  # proporción de píxeles del color del texto
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}", tuple(int(v) for v in bg), ink


def ocr_segments(page: pymupdf.Page, info: PageInfo, lines: list[OcrLine] | None = None) -> list[Segment]:
    """Segmentos traducibles a partir del texto encontrado en la imagen de la página."""
    if lines is None:
        lines = ocr_lines(page)
    if not lines:
        return []
    pix = _page_pixmap(page)
    # agrupar líneas consecutivas de alto parecido y cercanas en párrafos
    paras: list[list[OcrLine]] = []
    for ln in lines:
        if ln.rotation:
            paras.append([ln])  # texto vertical: cada línea es una etiqueta
            continue
        if paras and not paras[-1][-1].rotation:
            prev = paras[-1][-1]
            close = 0 <= ln.rect.y0 - prev.rect.y1 < 0.9 * prev.height
            similar = abs(ln.height - prev.height) < 0.25 * prev.height
            overlap = min(ln.rect.x1, prev.rect.x1) - max(ln.rect.x0, prev.rect.x0) > 0
            if close and similar and overlap:
                paras[-1].append(ln)
                continue
        paras.append([ln])

    segments: list[Segment] = []
    start = len(info.segments)
    for i, para in enumerate(paras, start=start + 1):
        rect = pymupdf.Rect(para[0].rect)
        for ln in para[1:]:
            rect |= ln.rect
        h = statistics.median(ln.height for ln in para)
        size = h * 0.95  # el alto de la caja OCR ≈ altura de mayúsculas + descendentes
        color, _bg, ink = _colors(pix, rect)
        cx = (rect.x0 + rect.x1) / 2
        centered = abs(cx - info.width / 2) < 0.06 * info.width
        text = " ".join(ln.text for ln in para)
        letters = [c for c in text if c.isalpha()]
        upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.7
        deltas = [b.rect.y1 - a.rect.y1 for a, b in zip(para, para[1:])]
        lh = statistics.median(deltas) / size if deltas else 1.2
        # grosor estimado por densidad de tinta (texto grueso de portada => Black)
        weight = "Black" if ink > 0.38 else "Bold" if ink > 0.26 else "Regular"
        style = Style(font=f"OCR-Slab-{weight}", size=round(size, 2), color=color,
                      bold=weight != "Regular", serif=True, align="center" if centered else "left",
                      line_height=round(max(1.0, min(1.8, lh)), 3))
        seg = Segment(key=f"p{info.number:03d}_s{i:03d}", page_no=info.number, bbox=tuple(rect),
                      line_rects=[tuple(ln.rect) for ln in para], style=style, text=text,
                      html=_escape(text), block_type="ocr", baseline=round(para[0].rect.y1 - 0.18 * h, 2),
                      ocr_confidence=round(statistics.mean(ln.conf for ln in para), 1))
        rot = para[0].rotation
        if rot:
            # origen de la primera letra sobre la línea base (como el texto vertical digital)
            seg.rotation = rot
            seg.style.align = "left"
            seg.origin = ((rect.x1 - 0.22 * h, rect.y1) if rot == 90 else (rect.x0 + 0.22 * h, rect.y0))
        if seg.ocr_confidence < 70:
            seg.issues.append(f"texto reconocido con baja confianza ({seg.ocr_confidence:.0f} %)")
        segments.append(seg)
    return segments


def _escape(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def erase_text_in_images(page: pymupdf.Page, rects: list[pymupdf.Rect]) -> int:
    """Borra el texto de las imágenes rasterizadas que lo contienen (inpainting) y reemplaza la imagen
    en el PDF. Devuelve cuántas imágenes se modificaron."""
    import cv2
    import numpy as np

    changed = 0
    doc = page.parent
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref")
        if not xref:
            continue
        ibox = pymupdf.Rect(info["bbox"])
        targets = [r for r in rects if abs(r & ibox) > 0.5 * abs(r)]
        if not targets:
            continue
        pix = pymupdf.Pixmap(doc, xref)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        if pix.n == 4:  # CMYK: se trabaja en RGB (único caso con posible variación de color)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        n = pix.n
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n).copy()
        rgb = img if n == 3 else np.repeat(img, 3, axis=2)
        sx, sy = pix.width / ibox.width, pix.height / ibox.height
        mask = np.zeros(img.shape[:2], dtype=np.uint8)
        for r in targets:
            pad = 0.15 * r.height
            x0, y0 = max(0, int((r.x0 - pad - ibox.x0) * sx)), max(0, int((r.y0 - pad - ibox.y0) * sy))
            x1, y1 = int((r.x1 + pad - ibox.x0) * sx), int((r.y1 + pad - ibox.y0) * sy)
            region = rgb[y0:y1, x0:x1].astype(int)
            if region.size == 0:
                continue
            ring = np.concatenate([rgb[max(0, y0 - 6):y0, x0:x1].reshape(-1, 3),
                                   rgb[y1:y1 + 6, x0:x1].reshape(-1, 3)])
            bg = np.median(ring if ring.size else region.reshape(-1, 3), axis=0)
            diff = np.abs(region - bg).sum(axis=2)
            # color del texto = píxeles más alejados del fondo; la máscara solo toma ese color
            # (así no se borran otros objetos de la ilustración que caen dentro de la caja)
            strong = region[diff >= np.percentile(diff, 85)]
            text_color = np.median(strong, axis=0) if strong.size else bg
            close = np.abs(region - text_color).sum(axis=2) < 90
            local = (close & (diff > 50)).astype(np.uint8) * 255
            # incluir contornos/antialias pegados al texto
            local = cv2.dilate(local, np.ones((3, 3), np.uint8), iterations=max(2, int(0.06 * (y1 - y0))))
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], local)
        if not mask.any():
            continue
        src = cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if n == 3 else img[:, :, 0]
        out = cv2.inpaint(src, mask, 9, cv2.INPAINT_TELEA)
        ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 94])
        if not ok:
            continue
        keys = {k: doc.xref_get_key(xref, k) for k in ("ColorSpace", "Intent")}
        page.replace_image(xref, stream=enc.tobytes())
        # replace_image reescribe el objeto con un perfil ICC propio: se restaura el perfil original
        # (p. ej. Adobe RGB) para que los tonos de la ilustración no cambien
        if n == 3:
            for k, (kind, val) in keys.items():
                if kind not in ("null", None):
                    doc.xref_set_key(xref, k, val)
        changed += 1
    return changed
