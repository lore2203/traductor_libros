"""Motor de maquetación de párrafos con TextWriter (PyMuPDF).

Permite controlar con precisión lo que el motor HTML no permite:
- primera línea exactamente sobre la línea base original e interlineado original,
- escala horizontal (como la de InDesign) para imitar fuentes condensadas,
- justificación, alineación y saltos de línea forzados (<br>),
- mezcla de pesos/cursivas/colores dentro del mismo párrafo sin solapamientos.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import pymupdf

from app.pipeline.fonts import FontChoice

TOKEN_RE = re.compile(r"<br\s*/?>|</?b>|</?i>|<span style=\"color:(#[0-9a-fA-F]{6})\">|</span>|[^<]+|<", re.I)


@dataclass
class Piece:
    text: str
    bold: bool
    italic: bool
    color: str | None


@dataclass
class Word:
    pieces: list[Piece]
    width: float = 0.0  # sin escala horizontal


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)
    width: float = 0.0
    forced: bool = False  # termina con <br> o es la última


def parse(h: str) -> list[Piece | None]:
    """html restringido -> lista de fragmentos; None = salto de línea forzado."""
    out: list[Piece | None] = []
    bold = italic = 0
    colors: list[str | None] = []
    for m in TOKEN_RE.finditer(h or ""):
        tok = m.group(0)
        low = tok.lower()
        if low.startswith("<br"):
            out.append(None)
        elif low == "<b>":
            bold += 1
        elif low == "</b>":
            bold = max(0, bold - 1)
        elif low == "<i>":
            italic += 1
        elif low == "</i>":
            italic = max(0, italic - 1)
        elif low.startswith("<span"):
            colors.append(m.group(1))
        elif low == "</span>":
            if colors:
                colors.pop()
        else:
            out.append(Piece(html.unescape(tok), bold > 0, italic > 0, colors[-1] if colors else None))
    return out


def plain_text(h: str) -> str:
    return "".join(p.text for p in parse(h) if p is not None)


def words_of(pieces: list[Piece | None]) -> list[Word | None]:
    """Agrupa fragmentos en palabras (sin cortar dentro de una palabra con estilos mezclados)."""
    words: list[Word | None] = []
    cur: list[Piece] = []

    def flush():
        nonlocal cur
        if cur:
            words.append(Word(cur))
            cur = []

    for p in pieces:
        if p is None:
            flush()
            words.append(None)
            continue
        for part in re.split(r"(\s+)", p.text):
            if not part:
                continue
            if part.isspace():
                flush()
            else:
                cur.append(Piece(part, p.bold, p.italic, p.color))
    flush()
    return words


def measure(words: list[Word | None], fonts: FontChoice, size: float) -> None:
    for w in words:
        if w is not None:
            w.width = sum(fonts.face(p.bold, p.italic).text_length(p.text, fontsize=_psize(fonts, p, size))
                          for p in w.pieces)


def _psize(fonts: FontChoice, p: Piece, size: float) -> float:
    return size * getattr(fonts, "bold_scale", 1.0) if p.bold else size


def natural_width(h: str, fonts: FontChoice, size: float) -> float:
    ws = words_of(parse(h))
    measure(ws, fonts, size)
    space = fonts.face(False, False).text_length(" ", fontsize=size)
    real = [w for w in ws if w is not None]
    return sum(w.width for w in real) + space * max(0, len(real) - 1)


def break_lines(words: list[Word | None], max_w: float, space: float,
                indents: list[float] | None = None) -> list[Line]:
    """indents: sangría izquierda (sin escala) de cada línea; la última se repite para las siguientes."""
    lines: list[Line] = [Line()]

    def width_of(i: int) -> float:
        if not indents:
            return max_w
        return max_w - indents[min(i, len(indents) - 1)]

    for w in words:
        line = lines[-1]
        if w is None:
            line.forced = True
            lines.append(Line())
            continue
        add = w.width + (space if line.words else 0)
        if line.words and line.width + add > width_of(len(lines) - 1) + 0.01:
            lines.append(Line(words=[w], width=w.width))
        else:
            line.words.append(w)
            line.width += add
    lines[-1].forced = True
    # eliminar líneas vacías por <br> duplicados al final
    while len(lines) > 1 and not lines[-1].words:
        lines.pop()
        lines[-1].forced = True
    return lines


@dataclass
class LayoutResult:
    lines: list[Line]
    size: float
    hscale: float
    leading: float
    fits: bool
    max_w: float
    indents: list[float] | None = None  # sangría izquierda por línea (sin escala horizontal)

    def indent(self, i: int) -> float:
        if not self.indents:
            return 0.0
        return self.indents[min(i, len(self.indents) - 1)]


def try_layout(words: list[Word | None], fonts: FontChoice, size: float, hscale: float, leading: float,
               width: float, first_baseline: float, bottom_limit: float,
               indents: list[float] | None = None) -> LayoutResult:
    """indents: sangría izquierda de cada línea en puntos de página (p. ej. texto que rodea un ícono)."""
    measure(words, fonts, size)
    space = fonts.face(False, False).text_length(" ", fontsize=size)
    max_w = width / hscale
    ind = [i / hscale for i in indents] if indents and any(i > 0 for i in indents) else None
    lines = break_lines(words, max_w, space, ind)
    res = LayoutResult(lines, size, hscale, leading, False, max_w, ind)
    last_baseline = first_baseline + (len(lines) - 1) * leading
    res.fits = last_baseline <= bottom_limit + 0.5 and all(
        l.width <= max_w - res.indent(i) + 0.5 for i, l in enumerate(lines))
    return res


def _rgb(hexcolor: str) -> tuple[float, float, float]:
    v = int(hexcolor.lstrip("#"), 16)
    return ((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255


def render(page: pymupdf.Page, res: LayoutResult, fonts: FontChoice, x0: float, first_baseline: float,
           align: str, default_color: str, rotation: int = 0) -> None:
    space = fonts.face(False, False).text_length(" ", fontsize=res.size)
    writers: dict[str, pymupdf.TextWriter] = {}
    y = first_baseline
    for n, line in enumerate(res.lines):
        extra_gap = 0.0
        ind = res.indent(n)
        avail = res.max_w - ind
        offset = ind
        gaps = max(0, len(line.words) - 1)
        if align == "justify" and not line.forced and gaps:
            extra_gap = (avail - line.width) / gaps
        elif align == "center":
            offset += (avail - line.width) / 2
        elif align == "right":
            offset += avail - line.width
        x = x0 + offset
        for i, w in enumerate(line.words):
            if i:
                x += space + extra_gap
            for p in w.pieces:
                font = fonts.face(p.bold, p.italic)
                color = p.color or default_color
                tw = writers.setdefault(color, pymupdf.TextWriter(page.rect))
                ps = _psize(fonts, p, res.size)
                tw.append((x, y), p.text, font=font, fontsize=ps)
                x += font.text_length(p.text, fontsize=ps)
        y += res.leading
    # escala horizontal alrededor del borde izquierdo de la caja
    matrix = pymupdf.Matrix(res.hscale, 0, 0, 1, 0, 0)
    if rotation:
        matrix = matrix * pymupdf.Matrix(rotation)  # 90 = texto vertical ascendente
    morph = (pymupdf.Point(x0, first_baseline), matrix)
    needs = abs(res.hscale - 1) > 1e-3 or rotation
    for color, tw in writers.items():
        tw.write_text(page, color=_rgb(color), morph=morph if needs else None)
