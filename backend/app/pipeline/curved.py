"""Texto en trayectoria (curvas, cintas onduladas, rótulos de ruedas) a partir del texto vectorial.

No necesita OCR: el PDF trae cada letra con su origen y su dirección. Se encadenan las letras que se
siguen a lo largo de una misma trayectoria, se traduce la frase completa y se dibuja la traducción letra
a letra sobre la misma curva (centrada en ella, con el mismo cuerpo, color y una fuente equivalente).
"""
from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass

import pymupdf

from app.pipeline.types import Segment, Style

WORD_RE = re.compile(r"[^\W\d_]{2,}")


@dataclass
class PChar:
    c: str
    x: float  # origen (sobre la línea base)
    y: float
    ux: float  # dirección del texto (unitaria)
    uy: float
    size: float
    font: str
    flags: int
    color: int
    bbox: tuple[float, float, float, float]



def _chars_of_line(line: dict) -> list[PChar]:
    ux, uy = line["dir"]
    out = []
    for sp in line["spans"]:
        for ch in sp["chars"]:
            out.append(PChar(ch["c"], ch["origin"][0], ch["origin"][1], ux, uy, sp["size"],
                             sp["font"].split("+", 1)[-1], sp["flags"], sp["color"], tuple(ch["bbox"])))
    return out


def _chains(chars: list[PChar]) -> list[list[PChar]]:
    """Encadena cada letra con la siguiente que está delante de ella en su dirección de escritura."""
    edges = []
    for i, a in enumerate(chars):
        for j, b in enumerate(chars):
            if i == j:
                continue
            vx, vy = b.x - a.x, b.y - a.y
            p = vx * a.ux + vy * a.uy  # avance a lo largo de la dirección
            q = abs(-vx * a.uy + vy * a.ux)  # desvío perpendicular
            if not (0.05 < p <= 1.9 * max(a.size, b.size)):
                continue
            if q > 0.45 * max(a.size, b.size):
                continue
            if a.ux * b.ux + a.uy * b.uy < math.cos(math.radians(35)):
                continue
            if abs(a.size - b.size) > 0.35 * max(a.size, b.size) and a.c.isalnum() and b.c.isalnum():
                continue  # los separadores ("|", "·") pueden ir en otro cuerpo
            edges.append((p + 2 * q, i, j))
    edges.sort()
    nxt: dict[int, int] = {}
    prv: dict[int, int] = {}
    for _, i, j in edges:
        if i in nxt or j in prv:
            continue
        # evitar ciclos
        k = i
        while k in prv:
            k = prv[k]
        if k == j:
            continue
        nxt[i], prv[j] = j, i
    chains = []
    for i in range(len(chars)):
        if i in prv:
            continue
        chain = [chars[i]]
        k = i
        while k in nxt:
            k = nxt[k]
            chain.append(chars[k])
        chains.append(chain)
    return chains


def _step(chain: list[PChar]) -> float:
    """Distancia típica entre letras consecutivas de la cadena."""
    d = sorted(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(chain, chain[1:])
               if not a.c.isspace() and not b.c.isspace())
    return d[len(d) // 2] if d else 0.6 * chain[0].size


def _text_of(chain: list[PChar]) -> str:
    step = _step(chain)
    parts = []
    for a, b in zip(chain, chain[1:] + [None]):
        parts.append(a.c)
        if b is not None and not a.c.isspace() and not b.c.isspace():
            if math.hypot(b.x - a.x, b.y - a.y) > 1.7 * step:  # hueco sin carácter de espacio
                parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _path_of(chain: list[PChar]) -> list[tuple[float, float]]:
    """Polilínea por los orígenes de las letras, prolongada con el avance de la última."""
    pts = [(c.x, c.y) for c in chain if not c.c.isspace()] or [(chain[0].x, chain[0].y)]
    last = [c for c in chain if not c.c.isspace()][-1] if any(not c.c.isspace() for c in chain) else chain[-1]
    step = _step(chain)
    pts.append((last.x + last.ux * step, last.y + last.uy * step))
    return pts


def build_curved_segments(page: pymupdf.Page, info, lines: list[dict],
                          extra_chars: list[PChar] | None = None) -> tuple[list[Segment], list[str], list[PChar]]:
    """(segmentos curvos traducibles, textos con palabras que no se pudieron encadenar, letras usadas)."""
    from app.pipeline.analyze import _hex, _is_bold, _is_italic, _is_mono, _is_serif, is_symbol_font

    chars = [c for line in lines for c in _chars_of_line(line)] + list(extra_chars or [])
    chars = [c for c in chars if not is_symbol_font(c.font)]
    segs: list[Segment] = []
    leftovers: list[str] = []
    used: list[PChar] = []
    for chain in _chains(chars):
        text = _text_of(chain)
        if not WORD_RE.search(text):
            continue  # números alrededor de una rueda, símbolos sueltos
        if len(chain) < 3 and len(text) < 3:
            leftovers.append(text)
            continue
        ink = [c for c in chain if not c.c.isspace()]
        main = max(ink, key=lambda c: c.size)
        style = Style(font=main.font, size=round(main.size, 2), color=_hex(main.color),
                      bold=_is_bold(main.font, main.flags), italic=_is_italic(main.font, main.flags),
                      serif=_is_serif(main.font, main.flags), mono=_is_mono(main.font, main.flags), align="center")
        bbox = pymupdf.Rect(ink[0].bbox)
        for c in ink[1:]:
            bbox |= pymupdf.Rect(c.bbox)
        # zonas de borrado: un cuadrado pequeño en el centro de cada letra (la redacción quita los
        # glifos que tocan el rectángulo; uno pequeño no toca el texto vecino)
        rects = []
        for c in ink:
            cx = (c.bbox[0] + c.bbox[2]) / 2
            cy = (c.bbox[1] + c.bbox[3]) / 2
            h = 0.12 * c.size
            rects.append((cx - h, cy - h, cx + h, cy + h))
        seg = Segment(key="", page_no=info.number, bbox=tuple(bbox), line_rects=rects, style=style, text=text,
                      html=html.escape(text, quote=False), block_type="curved")
        seg.path = _path_of([c for c in chain if c.size >= 0.75 * main.size or c.c.isspace()] or chain)
        # separadores en otro cuerpo (p. ej. "|" más pequeño y elevado): tamaño y desplazamiento relativos
        small = {}
        for k, c in enumerate(chain):
            if not c.c.isspace() and not c.c.isalnum() and c.size < 0.85 * main.size:
                prev = next((p for p in reversed(chain[:k]) if p.c.isalnum()), None)
                off = 0.0
                if prev is not None:
                    off = (-(c.x - prev.x) * prev.uy + (c.y - prev.y) * prev.ux) / main.size
                small.setdefault(c.c, []).append((c.size / main.size, off))
        seg.small_chars = {ch: (sum(v[0] for v in vals) / len(vals), sum(v[1] for v in vals) / len(vals))
                           for ch, vals in small.items()}
        segs.append(seg)
        used += chain
    return segs, leftovers, used


# ----------------------------------------------------------------------------- dibujo

def _arc(path: list[tuple[float, float]]) -> list[float]:
    acc = [0.0]
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        acc.append(acc[-1] + math.hypot(x1 - x0, y1 - y0))
    return acc


def _at(path, acc, s: float) -> tuple[float, float, float, float]:
    """Punto y tangente unitaria a la distancia s (se prolonga en línea recta fuera de los extremos)."""
    n = len(path)
    if n == 1:
        return path[0][0], path[0][1], 1.0, 0.0
    i = 0
    while i < n - 2 and acc[i + 1] < s:
        i += 1
    (x0, y0), (x1, y1) = path[i], path[i + 1]
    seg = max(1e-6, acc[i + 1] - acc[i])
    ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
    t = s - acc[i]
    return x0 + ux * t, y0 + uy * t, ux, uy


def place_curved(page: pymupdf.Page, seg: Segment, fonts, min_scale: float, dry: bool = False):
    """Dibuja la traducción sobre la trayectoria original. Devuelve (escala, cabe, zona ocupada)."""
    from app.pipeline import layout

    text = layout.plain_text(seg.translation or "").replace("\n", " ").strip()
    st = seg.style
    choice = fonts.choose(st, text)
    letters = [c for c in text if c.isalpha()]
    upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.7
    base = st.size * (choice.scale_cap if upper else choice.scale_x)
    font = choice.face(st.bold, st.italic)
    path = list(seg.path or [])
    acc = _arc(path)
    length = acc[-1] if acc else 0.0
    avail = length * 1.06

    small = getattr(seg, "small_chars", None) or {}

    def width(size, hs):
        return sum(font.text_length(ch, fontsize=size * small.get(ch, (1.0, 0.0))[0]) for ch in text) * hs

    size, hs, ok = base, 1.0, True
    for h in (1.0, 0.95, 0.9, 0.85, 0.8):
        hs = h
        if width(size, hs) <= avail:
            break
    else:
        sc = 1.0
        while width(base * sc, hs) > avail and sc > 0.3:
            sc -= 0.03
        size = base * sc
        ok = sc >= min_scale - 1e-6
    scale = size / base if base else 1.0
    w = width(size, hs)
    # en cintas con varias palabras ("SHINE | NURTURE | …") el espacio sobrante se reparte entre las
    # palabras, como en el original, en lugar de dejar el texto apretado en el centro
    spaces = text.count(" ")
    extra_space = 0.0
    if spaces and w < 0.97 * length:
        extra_space = min((0.97 * length - w) / spaces, 1.2 * size)
        w += extra_space * spaces
    s = (length - w) / 2
    occupied = pymupdf.Rect(seg.bbox)
    small = getattr(seg, "small_chars", None) or {}
    for ch in text:
        ratio, off = small.get(ch, (1.0, 0.0))
        csize = size * ratio
        adv = font.text_length(ch, fontsize=csize) * hs + (extra_space if ch == " " else 0.0)
        x, y, ux, uy = _at(path, acc, s + adv / 2)
        ox, oy = x - ux * adv / 2, y - uy * adv / 2
        if off:  # desplazamiento perpendicular a la línea base (normal = (-uy, ux))
            ox, oy = ox - uy * off * size, oy + ux * off * size
        if not dry and not ch.isspace():
            tw = pymupdf.TextWriter(page.rect)
            tw.append((ox, oy), ch, font=font, fontsize=csize)
            # convención de morph de PyMuPDF (verificada): Matrix(ux, -uy, uy, ux) orienta el texto a (ux, uy)
            m = pymupdf.Matrix(hs, 0, 0, 1, 0, 0) * pymupdf.Matrix(ux, -uy, uy, ux, 0, 0)
            tw.write_text(page, color=layout._rgb(st.color), morph=(pymupdf.Point(ox, oy), m))
        occupied |= pymupdf.Rect(ox - size, oy - size, ox + size, oy + size)
        s += adv
    return scale, ok, occupied
