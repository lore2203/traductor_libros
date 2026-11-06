"""Análisis de páginas y extracción de segmentos traducibles desde texto digital (PyMuPDF).

Trabaja a nivel de carácter (rawdict) para poder separar con precisión:
- fragmentos de una misma línea separados por tabulaciones/espacios grandes (columnas, índices),
- líneas de puntos del índice y números de página (se conservan intactos),
- párrafos dentro de un bloque y párrafos que PyMuPDF partió en varios bloques.
"""
from __future__ import annotations

import html
import re
import statistics
from dataclasses import dataclass, field
from functools import cached_property

import pymupdf

from app.pipeline.types import PageInfo, Segment, Style

# flags de span en PyMuPDF
F_ITALIC, F_SERIF, F_MONO, F_BOLD = 2, 4, 8, 16

SANS_HINTS = ("sans", "gothic", "helvet", "arial", "futura", "gill", "avenir", "gotham", "frutiger", "myriad",
              "univers", "proxima", "montserrat", "lato", "opensans", "roboto", "verdana", "calibri", "din",
              "franklin", "segoe", "source sans", "sourcesans", "nunito", "inter", "akzidenz", "trade")
SERIF_HINTS = ("serif", "times", "garamond", "minion", "caslon", "baskerville", "georgia", "palatino", "bodoni",
               "didot", "sabon", "bembo", "cambria", "book", "roman", "jenson", "goudy", "chaparral", "utopia",
               "plantin", "janson", "mercury", "miller", "tiempos")
BOLD_HINTS = ("bold", "black", "heavy", "semibold", "demi", "extrabold", "ultra")
ITALIC_HINTS = ("italic", "oblique", "ital")

LEADER_RE = re.compile(r"(?:\.\s?){4,}|…{2,}|(?:·\s?){4,}|_{4,}")
ROMAN_RE = re.compile(r"^(?=[ivxlcdm]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)
HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
URL_EMAIL_ISBN_RE = re.compile(
    r"^(?:(?:https?://|www\.)\S+|[\w.+-]+@[\w-]+\.[\w.-]+|(?:ISBN[:\s-]*)?(?:97[89][\s-]?)?\d[\d\s-]{8,}[\dX])$", re.I)


# ----------------------------------------------------------------------------- utilidades de estilo

def _clean_font_name(name: str) -> str:
    return name.split("+", 1)[1] if "+" in name[:8] else name


def _is_bold(font: str, flags: int) -> bool:
    n = font.lower()
    return bool(flags & F_BOLD) or any(h in n for h in BOLD_HINTS)


def _is_italic(font: str, flags: int) -> bool:
    n = font.lower()
    return bool(flags & F_ITALIC) or any(h in n for h in ITALIC_HINTS)


def _is_serif(font: str, flags: int) -> bool:
    n = font.lower().replace("-", "").replace(" ", "")
    if any(h.replace(" ", "") in n for h in SANS_HINTS):
        return False
    if any(h in n for h in SERIF_HINTS):
        return True
    return bool(flags & F_SERIF)


def _is_mono(font: str, flags: int) -> bool:
    n = font.lower()
    return bool(flags & F_MONO) or "mono" in n or "courier" in n or "consol" in n


def _hex(color: int) -> str:
    return f"#{color & 0xFFFFFF:06x}"


@dataclass(frozen=True)
class CharStyle:
    font: str
    size: float
    color: str
    bold: bool
    italic: bool
    serif: bool
    mono: bool
    symbolic: bool = False  # fuente de símbolos/pictogramas: nunca se traduce ni se redibuja


SYMBOL_FONT_HINTS = ("astrolog", "symbol", "dingbat", "wingding", "zapf", "ornament", "pilt", "pistd", "picons",
                     "fontawesome", "icons", "emoji")


def is_symbol_font(name: str) -> bool:
    n = name.lower().replace("-", "")
    return any(h in n for h in SYMBOL_FONT_HINTS)


@dataclass
class Char:
    c: str
    rect: pymupdf.Rect
    style: CharStyle
    origin_y: float


@dataclass
class PLine:
    """Pseudo-línea: fragmento horizontal continuo de texto."""
    chars: list[Char]
    block_no: int
    _text: str | None = field(default=None, repr=False)
    has_sibling: bool = False
    row_start: bool = False  # tiene un marcador (símbolo/número) a su izquierda: empieza una fila

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = "".join(ch.c for ch in self.chars)
        return self._text

    @cached_property
    def _bbox(self) -> tuple[float, float, float, float]:
        rs = [ch.rect for ch in self.chars]
        return (min(r.x0 for r in rs), min(r.y0 for r in rs), max(r.x1 for r in rs), max(r.y1 for r in rs))

    @property
    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(self._bbox)  # copia: quien la recibe puede modificarla

    @cached_property
    def dominant(self) -> CharStyle:
        counts: dict[CharStyle, int] = {}
        for ch in self.chars:
            if not ch.c.isspace():
                counts[ch.style] = counts.get(ch.style, 0) + 1
        return max(counts, key=counts.get) if counts else self.chars[0].style

    @property
    def symbolic(self) -> bool:
        return all(ch.style.symbolic for ch in self.chars if not ch.c.isspace())

    @property
    def size(self) -> float:
        return self.dominant.size

    @cached_property
    def baseline(self) -> float:
        return statistics.median(ch.origin_y for ch in self.chars)

    def slice(self, a: int, b: int) -> PLine | None:
        chars = self.chars[a:b]
        while chars and chars[0].c.isspace():
            chars = chars[1:]
        while chars and chars[-1].c.isspace():
            chars = chars[:-1]
        return PLine(chars, self.block_no) if chars else None


# ----------------------------------------------------------------------------- extracción

def _raw_lines(page: pymupdf.Page) -> tuple[list[PLine], list[dict]]:
    """Devuelve pseudo-líneas horizontales y las líneas no horizontales (rawdict) por separado."""
    raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    plines: list[PLine] = []
    rotated: list[dict] = []
    for b_no, block in enumerate(raw["blocks"]):
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            dx, dy = line["dir"]
            if abs(dy) > 0.02 or dx < 0:
                rotated.append(line)
                continue
            current: list[Char] = []
            prev: Char | None = None
            for span in line["spans"]:
                font = _clean_font_name(span["font"])
                fl = span["flags"]
                st = CharStyle(font, round(span["size"], 2), _hex(span["color"]), _is_bold(font, fl),
                               _is_italic(font, fl), _is_serif(font, fl), _is_mono(font, fl))
                if is_symbol_font(font):
                    st = CharStyle(**{**st.__dict__, "symbolic": True})
                for ch in span["chars"]:
                    r = pymupdf.Rect(ch["bbox"])
                    c = Char(ch["c"], r, st, ch["origin"][1])
                    # hueco horizontal grande (tabulación / columna) => nueva pseudo-línea
                    if prev is not None and (r.x0 - prev.rect.x1 > max(1.6 * st.size, 12)
                                             or prev.style.symbolic != st.symbolic):
                        plines.append(PLine(current, b_no))
                        current = []
                    current.append(c)
                    prev = c
            if current:
                plines.append(PLine(current, b_no))

    # separar líneas de puntos de índice: "Sun signs ........ 12" -> ["Sun signs", "........", "12"]
    result: list[PLine] = []
    for pl in plines:
        pieces: list[PLine | None] = []
        pos = 0
        for m in LEADER_RE.finditer(pl.text):
            rest = pl.text[m.end():].strip()
            if rest and not rest[:1].isdigit():
                continue  # puntos suspensivos dentro de una frase ("and so on.... Together"), no guía de índice
            pieces.append(pl.slice(pos, m.start()))
            pieces.append(pl.slice(m.start(), m.end()))
            pos = m.end()
        pieces.append(pl.slice(pos, len(pl.chars)))
        # número final separado del texto: "Sun signs 12" cuando el número está alejado
        for p in pieces:
            if p is not None:
                result.append(p)
    return [p for p in result if p.text.strip()], rotated


def _is_keep_text(text: str) -> bool:
    t = text.strip()
    if not HAS_LETTER_RE.search(t):
        return True  # números, símbolos, puntuación, líneas de puntos
    if len(t) <= 6 and ROMAN_RE.match(t):
        return True  # numeración romana de página
    if URL_EMAIL_ISBN_RE.match(t):
        return True
    return False


def _continues(prev: PLine, nxt: PLine, para_left: float) -> bool:
    """¿La pseudo-línea `nxt` continúa el párrafo cuya última línea es `prev`?"""
    ps, ns = prev.dominant, nxt.dominant
    if abs(ps.size - ns.size) > 0.12 * max(ps.size, ns.size):
        return False
    shared = {(c.style.font, c.style.size, c.style.color) for c in prev.chars if not c.c.isspace()} &         {(c.style.font, c.style.size, c.style.color) for c in nxt.chars if not c.c.isspace()}
    if not shared and (ps.color != ns.color or ps.bold != ns.bold):
        return False  # sin fuente común: estilos distintos (título vs. cuerpo)
    if prev.has_sibling or nxt.has_sibling:
        return False  # fila de índice/tabla: texto con número u otra celda en la misma línea
    if _is_keep_text(nxt.text) or _is_keep_text(prev.text) or nxt.symbolic or prev.symbolic:
        return False
    pr, nr = prev.rect, nxt.rect
    size = ps.size
    # debe estar debajo, sin gran separación vertical
    if nxt.baseline <= prev.baseline + 0.5 * size:
        return False
    if nxt.baseline - prev.baseline > 1.9 * size:
        return False
    # solapamiento horizontal suficiente (misma columna)
    overlap = min(pr.x1, nr.x1) - max(pr.x0, nr.x0)
    if overlap < 0.3 * min(pr.width, nr.width):
        return False
    # sangría de primera línea tras una frase terminada => nuevo párrafo
    if nr.x0 > para_left + 0.8 * size and prev.text.rstrip().endswith((".", "!", "?", ":", "”", '"')):
        return False
    return True


def _group_paragraphs(plines: list[PLine], page_width: float = 0.0) -> list[list[PLine]]:
    # símbolos que encabezan una fila (♈ Aries…): tienen texto inmediatamente a su derecha
    markers = set()
    for m in plines:
        if m.symbolic:
            mr = m.rect
            if any(not t.symbolic and 0 <= t.rect.x0 - mr.x1 < 1.5 * max(t.size, 1)
                   and abs(t.baseline - m.baseline) < 0.5 * m.size for t in plines):
                markers.add(id(m))
    # marcar pseudo-líneas que comparten línea base con otra separada horizontalmente
    for i, a in enumerate(plines):
        for b in plines[i + 1:]:
            if not (_is_keep_text(a.text) or _is_keep_text(b.text) or a.symbolic or b.symbolic):
                continue  # dos columnas de texto alineadas no son una fila de índice
            # un ícono mucho más grande que el texto es una viñeta decorativa, no una celda de tabla
            if max(a.size, b.size) > 1.7 * min(a.size, b.size):
                continue
            gap = max(b.rect.x0 - a.rect.x1, a.rect.x0 - b.rect.x1)
            if page_width and gap > 0.6 * page_width:
                continue  # está en otra columna
            apart = b.rect.x0 >= a.rect.x1 - 1 or a.rect.x0 >= b.rect.x1 - 1
            if apart and abs(a.baseline - b.baseline) < 0.3 * a.size:
                # marcador a la izquierda de un texto (♈ Aries…): la fila empieza ahí, pero sus líneas
                # siguientes sí continúan el párrafo. Número/celda a la derecha: fila cerrada (índice).
                for txt, other in ((a, b), (b, a)):
                    marker = _is_keep_text(other.text) or other.symbolic
                    if marker and not (_is_keep_text(txt.text) or txt.symbolic) and other.rect.x1 <= txt.rect.x0 + 1:
                        txt.row_start = True
                    elif id(other) in markers and not txt.symbolic and other.rect.x0 >= txt.rect.x1 - 1:
                        pass  # símbolo a la derecha que encabeza la fila de otra columna
                    else:
                        txt.has_sibling = True
    paragraphs: list[list[PLine]] = []
    for pl in plines:
        placed = False
        # intentar continuar alguno de los últimos párrafos abiertos (columnas intercaladas)
        for para in reversed(paragraphs[-4:]):
            left = min(p.rect.x0 for p in para)
            if pl.row_start:
                break
            if len(para) >= 2:
                # espacio extra entre párrafos: mayor que el interlineado ya establecido
                lead = para[-1].baseline - para[-2].baseline
                if lead > 0 and pl.baseline - para[-1].baseline > 1.2 * lead + 0.5:
                    continue
            if _continues(para[-1], pl, left):
                para.append(pl)
                placed = True
                break
        if not placed:
            paragraphs.append([pl])
    return paragraphs


def _alignment(lines: list[PLine], page_width: float) -> str:
    rects = [l.rect for l in lines]
    if len(rects) == 1:
        cx = (rects[0].x0 + rects[0].x1) / 2
        return "center" if abs(cx - page_width / 2) < 0.02 * page_width and rects[0].x0 > 0.15 * page_width else "left"
    body = rects[:-1]
    tol = 2.5
    lefts = [r.x0 for r in rects]
    rights = [r.x1 for r in body]
    centers = [(r.x0 + r.x1) / 2 for r in rects]
    # alineado a la izquierda (se tolera sangría en la primera línea si hay más de dos líneas)
    left_ok = max(lefts) - min(lefts) < tol * 2 or (len(lefts) > 2 and max(lefts[1:]) - min(lefts[1:]) < tol)
    right_ok = max(rights) - min(rights) < tol
    if left_ok and right_ok and len(rects) > 3:  # con solo 2 líneas de cuerpo la coincidencia es casual
        return "justify"
    if max(centers) - min(centers) < tol and not left_ok:
        return "center"
    if max(r.x1 for r in rects) - min(r.x1 for r in rects) < tol and not left_ok:
        return "right"
    return "left"


def font_weight(font: str, bold_flag: bool = False) -> int:
    """Peso tipográfico (100-900) deducido del nombre de la fuente."""
    n = font.lower().replace("-", "").replace(" ", "")
    for words, w in ((("thin", "hairline"), 100), (("extralight", "ultralight"), 200), (("semibold", "demibold", "demi"), 600),
                     (("extrabold", "ultrabold"), 800), (("heavy", "black", "fat"), 900), (("light",), 300),
                     (("medium",), 500), (("bold",), 700), (("book", "regular", "roman"), 400)):
        if any(x in n for x in words):
            return w
    return 700 if bold_flag else 400


def _hard_breaks(lines: list[PLine], align: str) -> set[int]:
    """Índices de líneas tras las cuales el original tiene un salto intencional (listas, créditos,
    versos, entradas de índice). Una línea corta que no es la última indica un salto forzado."""
    if len(lines) < 2:
        return set()
    widths = [l.rect.width for l in lines]
    full = max(widths)
    hard = set()
    for i in range(len(lines) - 1):
        text = lines[i].text.rstrip()
        nxt = lines[i + 1].text.lstrip()[:1]
        size = lines[i].size
        # cabe la primera palabra de la siguiente línea en el hueco => el salto no fue automático
        next_word = lines[i + 1].text.split()[0] if lines[i + 1].text.split() else ""
        room = full - widths[i]
        fits_next = room > (len(next_word) + 1) * 0.5 * size
        last_ch = next((c for c in reversed(lines[i].chars) if not c.c.isspace()), None)
        first_ch = next((c for c in lines[i + 1].chars if not c.c.isspace()), None)
        if last_ch and first_ch and last_ch.style.font != first_ch.style.font and not text.endswith(","):
            hard.add(i)  # p. ej. "Editor <b>Nombre</b>" / "Consultor <b>Nombre</b>"
            continue
        last_word = text.split()[-1] if text.split() else ""
        if align == "center":
            if (nxt.isupper() or nxt.isdigit()) and (fits_next or last_word[:1].isupper()
                                                    or text.endswith((".", ":", "!", "?"))):
                hard.add(i)
        elif fits_next and room > 0.15 * full and (
                text.endswith((".", ":", "!", "?", ";", "”", '"')) or nxt.isupper() or nxt.isdigit()
                or not nxt.isalpha()):
            # en texto en bandera una línea corta seguida de minúscula es solo el corte natural de la columna
            hard.add(i)
    return hard


def _runs_html(lines: list[PLine], dom: CharStyle, base_weight: int = 400,
               base_italic: bool = False, hard: set[int] | None = None) -> tuple[str, str]:
    """Texto plano y html inline (<b>, <i>, color) del párrafo. Las líneas se unen con espacio y se
    eliminan guiones de corte de palabra."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for i, line in enumerate(lines):
        chars = line.chars
        text = line.text
        if i > 0 and hard and (i - 1) in hard:
            plain_parts.append(" ")
            html_parts.append("<br>")
        elif i > 0:
            prev_plain = plain_parts[-1] if plain_parts else ""
            if prev_plain.endswith("-") and len(prev_plain) > 1 and prev_plain[-2].isalpha() and text[:1].islower():
                # deshacer guion de corte
                plain_parts[-1] = prev_plain[:-1]
                html_parts[-1] = html_parts[-1][:-1] if html_parts[-1].endswith("-") else html_parts[-1]
            else:
                plain_parts.append(" ")
                html_parts.append(" ")
        plain_parts.append(text)
        # agrupar caracteres por estilo
        run: list[str] = []
        run_style: CharStyle | None = None

        def flush():
            if not run:
                return
            t = html.escape("".join(run), quote=False)
            st = run_style
            if st.color != dom.color:
                t = f'<span style="color:{st.color}">{t}</span>'
            if st.italic and not base_italic:
                t = f"<i>{t}</i>"
            if font_weight(st.font, st.bold) > base_weight + 50:
                t = f"<b>{t}</b>"
            html_parts.append(t)

        for ch in chars:
            changed = run_style is not None and (_tag_key(ch.style, dom, base_weight, base_italic)
                                                 != _tag_key(run_style, dom, base_weight, base_italic))
            if changed and not ch.c.isspace():
                flush()
                run = []
            if not run:
                run_style = ch.style
            run.append(ch.c)
        flush()
    plain = re.sub(r"\s+", " ", "".join(plain_parts)).strip()
    htm = re.sub(r"\s*<br>\s*", "<br>", re.sub(r"\s+", " ", "".join(html_parts))).strip()
    return plain, htm


def _tag_key(st: CharStyle, dom: CharStyle, base_weight: int, base_italic: bool) -> tuple:
    return (st.color != dom.color and st.color, st.italic and not base_italic,
            font_weight(st.font, st.bold) > base_weight + 50)


def _rotated_segments(lines: list[dict], info: PageInfo) -> tuple[list[Segment], list[str]]:
    """Texto vertical (90°/270°) -> segmentos traducibles de una línea. Texto en curva o con otros
    ángulos (p. ej. números alrededor de una rueda) se conserva; solo se avisa si contiene palabras."""
    segs: list[Segment] = []
    curved: list[str] = []
    for line in lines:
        dx, dy = line["dir"]
        chars = [c for s in line["spans"] for c in s["chars"]]
        text = re.sub(r"\s+", " ", "".join(c["c"] for c in chars)).strip()
        if not text:
            continue
        span = max(line["spans"], key=lambda s: len(s["chars"]))
        font = _clean_font_name(span["font"])
        if abs(dx) > 0.02:  # ángulo arbitrario o curva
            if re.search(r"[^\W\d_]{3,}", text):
                curved.append(text)
            continue
        if is_symbol_font(font) or _is_keep_text(text):
            continue
        fl = span["flags"]
        style = Style(font=font, size=round(span["size"], 2), color=_hex(span["color"]), bold=_is_bold(font, fl),
                      italic=_is_italic(font, fl), serif=_is_serif(font, fl), mono=_is_mono(font, fl), align="left")
        r = pymupdf.Rect(line["bbox"])
        segs.append(Segment(key="", page_no=info.number, bbox=tuple(r), line_rects=[tuple(r)], style=style,
                            text=text, html=html.escape(text, quote=False), block_type="label",
                            rotation=90 if dy < 0 else 270, origin=tuple(chars[0]["origin"])))
    return segs, curved


def classify_page(page: pymupdf.Page, number: int) -> PageInfo:
    text = page.get_text("text")
    chars = len(re.sub(r"\s", "", text))
    garbled = text.count("�")
    images = page.get_image_info()
    area = abs(page.rect)
    img_cover = sum(abs(pymupdf.Rect(im["bbox"]) & page.rect) for im in images) / area if area else 0
    drawings = len(page.get_cdrawings())
    info = PageInfo(number=number, width=page.rect.width, height=page.rect.height, rotation=page.rotation,
                    kind="digital", image_count=len(images), drawing_count=drawings, text_chars=chars)
    if chars == 0:
        if not images and drawings == 0:
            info.kind = "blank"
        else:
            info.kind = "image_only"  # ilustración o escaneo: el OCR decide si hay texto
    elif garbled > 0.2 * chars:
        info.kind = "scanned"  # texto sin mapeo Unicode: requiere OCR
    elif img_cover > 0.6 and chars < 200:
        info.kind = "mixed"  # posible escaneo con capa OCR o poco texto sobre imagen
    return info


def extract_segments(page: pymupdf.Page, info: PageInfo) -> list[Segment]:
    plines, rotated = _raw_lines(page)
    vertical_segments, _ = _rotated_segments(rotated, info)
    paragraphs = _group_paragraphs(plines, info.width)
    sizes = [p.size for p in plines if not _is_keep_text(p.text)]
    body_size = statistics.median(sizes) if sizes else 10.0
    keep_lines_end_num = sum(1 for p in plines if p.text.strip().isdigit())

    segments: list[Segment] = []
    for idx, para in enumerate(paragraphs, start=1):
        dom_counts: dict[CharStyle, int] = {}
        for l in para:
            for ch in l.chars:
                if not ch.c.isspace():
                    dom_counts[ch.style] = dom_counts.get(ch.style, 0) + 1
        dom = max(dom_counts, key=dom_counts.get) if dom_counts else para[0].dominant
        # fuente base = la más ligera del párrafo; los fragmentos más pesados se marcan con <b>
        upright = [st for st in dom_counts if st.italic == dom.italic] or list(dom_counts)
        base = min(upright, key=lambda st: (font_weight(st.font, st.bold), -dom_counts[st]))
        bw = font_weight(base.font, base.bold)
        align = _alignment(para, info.width)
        plain, htm = _runs_html(para, dom, bw, base.italic, _hard_breaks(para, align))
        rect = pymupdf.Rect(para[0].rect)
        for l in para[1:]:
            rect |= l.rect
        baselines = [l.baseline for l in para]
        if len(baselines) > 1:
            deltas = [b - a for a, b in zip(baselines, baselines[1:])]
            lh = max(1.0, min(2.2, statistics.median(deltas) / dom.size))
        else:
            lh = 1.2
        variants: dict[str, str] = {}
        for st in sorted(dom_counts, key=dom_counts.get, reverse=True):
            heavy = font_weight(st.font, st.bold) > bw + 50
            it = st.italic and not base.italic
            key = ("bold" if heavy else "") + ("italic" if it else "")
            if key:
                variants.setdefault(key, st.font)
        heavy_sizes = [st.size for st in dom_counts for _ in range(dom_counts[st])
                       if font_weight(st.font, st.bold) > bw + 50]
        bold_scale = round(statistics.median(heavy_sizes) / dom.size, 3) if heavy_sizes else 1.0
        if abs(bold_scale - 1) < 0.04:
            bold_scale = 1.0
        style = Style(variants=variants, bold_scale=bold_scale, font=base.font, size=dom.size, color=dom.color, bold=base.bold,
                      italic=base.italic, serif=base.serif, mono=base.mono, align=align,
                      line_height=round(lh, 3))
        if dom.size >= body_size * 1.25 or (dom.bold and len(plain.split()) <= 12 and len(para) <= 2):
            btype = "heading"
        elif dom.size <= body_size * 0.85:
            btype = "caption"
        else:
            btype = "body"
        if keep_lines_end_num >= 5 and btype != "heading":
            btype = "toc"
        line_rects = []
        for l in para:
            # rectángulos por carácter agrupados por línea, ligeramente reducidos en vertical
            r = l.rect
            pad = 0.15 * (r.height)
            line_rects.append((r.x0, r.y0 + pad, r.x1, r.y1 - pad))
        seg = Segment(key=f"p{info.number:03d}_s{idx:03d}", page_no=info.number, bbox=tuple(rect),
                      line_rects=line_rects, style=style, text=plain, html=htm, block_type=btype,
                      baseline=round(para[0].baseline, 2))
        if _is_keep_text(plain) or all(l.symbolic for l in para):
            seg.action = "keep"
        segments.append(seg)

    # fragmentos horizontales pegados a texto en curva (p. ej. "SERT" de "ASSERT") se conservan
    frags: list[Segment] = []
    curved = [(pymupdf.Rect(l["bbox"]), max((sp["size"] for sp in l["spans"]), default=0)) for l in rotated
              if abs(l["dir"][0]) > 0.02 and abs(l["dir"][1]) > 0.02]
    for sg in segments:
        r = pymupdf.Rect(sg.bbox)
        # solo fragmentos del mismo cuerpo de letra que la curva y cortos (p. ej. "SERT" de "ASSERT");
        # un título vecino más grande ("Fixed" junto a una rueda) se traduce
        near = [c for c, size in curved
                if abs(size - sg.style.size) <= 0.15 * max(size, sg.style.size)
                and abs(pymupdf.Rect(c.x0 - sg.style.size, c.y0 - sg.style.size,
                                     c.x1 + sg.style.size, c.y1 + sg.style.size) & r) > 0]
        if near and len(sg.text.split()) <= 2 and len(re.sub(r"\W", "", sg.text)) <= 6:
            sg.action = "keep"
            frags.append(sg)

    # texto en curva o inclinado: se encadena letra a letra y se traduce sobre su misma trayectoria
    from app.pipeline.curved import PChar, build_curved_segments

    frag_chars: dict[int, list[PChar]] = {}
    for sg, para in zip(segments, paragraphs):
        if sg in frags:
            frag_chars[id(sg)] = [
                PChar(ch.c, ch.rect.x0, ch.origin_y, 1.0, 0.0, ch.style.size, ch.style.font,
                      (16 if ch.style.bold else 0) | (2 if ch.style.italic else 0), int(ch.style.color[1:], 16),
                      tuple(ch.rect)) for l in para for ch in l.chars]
    slanted = [l for l in rotated if abs(l["dir"][0]) > 0.02]
    curved_segments, leftovers, used = build_curved_segments(
        page, info, slanted, [c for cs in frag_chars.values() for c in cs])
    used_ids = {id(c) for c in used}
    segments = [sg for sg in segments
                if not (id(sg) in frag_chars and any(id(c) in used_ids for c in frag_chars[id(sg)]))]
    words = [t for t in leftovers if re.search(r"[^\W\d_]{3,}", t)]
    if words:
        info.flag(f"Texto en curva o inclinado conservado sin traducir: {', '.join(words[:4])}")
    for cs in curved_segments:
        cs.key = f"p{info.number:03d}_s{len(segments) + 1:03d}"
        segments.append(cs)

    for vs in vertical_segments:
        vs.key = f"p{info.number:03d}_s{len(segments) + 1:03d}"
        segments.append(vs)

    # alineación de líneas sueltas según sus vecinas (créditos centrados, columnas, textos a la derecha)
    def _near(a, b, tol=2.0):
        return abs(a - b) < tol

    for sg in segments:
        if len(sg.line_rects) != 1:
            continue
        x0, _, x1, _ = sg.bbox
        cx = (x0 + x1) / 2
        others = [o for o in segments if o is not sg]
        same_left = any(_near(o.bbox[0], x0) for o in others)
        same_center = any(_near((o.bbox[0] + o.bbox[2]) / 2, cx) and not _near(o.bbox[0], x0, 3) for o in others)
        same_right = any(_near(o.bbox[2], x1) and not _near(o.bbox[0], x0, 3) for o in others)
        if same_center and not same_left:
            sg.style.align = "center"
        elif same_right and not same_left:
            sg.style.align = "right"
        elif same_left and sg.style.align == "center":
            sg.style.align = "left"
    return segments


def analyze(doc: pymupdf.Document) -> list[PageInfo]:
    pages: list[PageInfo] = []
    for i, page in enumerate(doc):
        info = classify_page(page, i + 1)
        if info.kind in ("digital", "mixed"):
            info.segments = extract_segments(page, info)
        elif info.kind == "scanned":
            info.flag("La página tiene texto sin codificación legible y necesita OCR")
        pages.append(info)
    return pages
