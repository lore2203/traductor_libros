"""Reconstrucción de páginas: borra solo el texto original traducible y escribe la traducción en la
misma zona, conservando imágenes, vectores, fondos y colores.

Prioridades ante la expansión del español (nunca se corta ni se oculta texto):
  1. misma caja y tamaño
  2. ampliar la caja hacia espacio libre contiguo
  3. reducir ligeramente el tamaño (hasta el mínimo legible)
  4. si aún no cabe: se inserta completo reduciendo lo necesario y la página va a revisión
"""
from __future__ import annotations

import logging

import pymupdf

from app.pipeline import layout
from app.pipeline.fonts import FontResolver
from app.pipeline.types import PageInfo, Segment

log = logging.getLogger(__name__)


class InkMap:
    """Render de la página original para saber si una zona está realmente libre (sin ilustraciones,
    líneas ni texto) antes de dejar crecer un bloque hacia ella."""

    def __init__(self, page: pymupdf.Page, dpi: int = 36):
        import numpy as np

        pix = page.get_pixmap(dpi=dpi, alpha=False, annots=False)
        self.k = dpi / 72.0
        self.arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3] \
            .astype(np.int16)
        self.h, self.w = self.arr.shape[:2]

    def _px(self, v: float, limit: int) -> int:
        return max(0, min(limit, int(round(v * self.k))))

    def background(self, rect: pymupdf.Rect):
        import numpy as np

        x0, x1 = self._px(rect.x0, self.w), self._px(rect.x1, self.w)
        y0, y1 = self._px(rect.y0, self.h), self._px(rect.y1, self.h)
        region = self.arr[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)].reshape(-1, 3)
        return np.median(region, axis=0) if region.size else np.array([255, 255, 255])

    def _inked(self, band, bg) -> bool:
        if band.size == 0:
            return False
        diff = abs(band - bg).sum(axis=-1)
        return (diff > 60).mean() > 0.02

    def free_down(self, rect: pymupdf.Rect, limit: float, bg) -> float:
        x0, x1 = self._px(rect.x0, self.w), self._px(rect.x1, self.w)
        y = self._px(rect.y1, self.h) + 1
        end = self._px(limit, self.h)
        while y < end:
            if self._inked(self.arr[y, x0:x1], bg):
                return max(rect.y1, y / self.k - 1.5)
            y += 1
        return limit

    def free_side(self, rect: pymupdf.Rect, limit: float, bg, direction: int) -> float:
        y0, y1 = self._px(rect.y0, self.h), self._px(rect.y1, self.h)
        x = self._px(rect.x1 if direction > 0 else rect.x0, self.w) + direction
        end = self._px(limit, self.w)
        while (x < end) if direction > 0 else (x > end):
            if self._inked(self.arr[y0:y1, x], bg):
                edge = x / self.k - 2.0 * direction
                return max(rect.x1, edge) if direction > 0 else min(rect.x0, edge)
            x += direction
        return limit


def _drawings(page: pymupdf.Page) -> tuple[list[pymupdf.Rect], list[pymupdf.Rect]]:
    """(cajas de color que pueden contener texto, gráficos vectoriales que actúan como obstáculos)."""
    area = abs(page.rect)
    containers, shapes = [], []
    try:
        for d in page.get_drawings():
            r = pymupdf.Rect(d["rect"])
            if r.is_empty or abs(r) >= 0.6 * area:
                continue  # fondos de página completa
            if (d.get("fill") is not None or d.get("color") is not None) and r.width > 20 and r.height > 10:
                containers.append(r)  # caja rellena o con contorno
            if r.width > 4 and r.height > 4:
                shapes.append(r)
    except Exception as e:  # noqa: BLE001
        log.debug("get_drawings falló: %s", e)
    return containers, shapes


def _container_for(rect: pymupdf.Rect, containers: list[pymupdf.Rect]) -> pymupdf.Rect | None:
    best = None
    for c in containers:
        if abs(rect & c) >= 0.9 * abs(rect) and (best is None or abs(c) < abs(best)):
            best = c
    return best


def _bounds(rect: pymupdf.Rect, page_rect: pymupdf.Rect, container: pymupdf.Rect | None) -> pymupdf.Rect:
    """Zona máxima donde puede crecer el texto: la caja de color (respetando parte de su margen interior)
    o la página menos sus márgenes."""
    if container is not None:
        def pad(gap: float) -> float:
            return max(2.0, 0.6 * max(0.0, gap))

        bound = pymupdf.Rect(container.x0 + pad(rect.x0 - container.x0), container.y0 + pad(rect.y0 - container.y0),
                             container.x1 - pad(container.x1 - rect.x1), container.y1 - pad(container.y1 - rect.y1))
    else:
        m = max(8.0, 0.03 * page_rect.height)
        bound = pymupdf.Rect(page_rect.x0 + m, page_rect.y0 + m, page_rect.x1 - m, page_rect.y1 - m)
    return bound | rect  # nunca menor que la caja original


def _grow_down(rect: pymupdf.Rect, bound: pymupdf.Rect, obstacles: list[pymupdf.Rect], size: float,
               ink: InkMap | None = None, bg=None) -> pymupdf.Rect:
    bottom = bound.y1
    for o in obstacles:
        # está "debajo" si empieza por debajo de la mitad de la caja (aunque las cajas se toquen)
        if o.y0 >= rect.y0 + 0.6 * rect.height and min(o.x1, rect.x1) - max(o.x0, rect.x0) > 1:
            bottom = min(bottom, o.y0 - 0.2 * size)
    if ink is not None and bottom > rect.y1:
        bottom = ink.free_down(rect, bottom, bg)
    return pymupdf.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, bottom))


def _grow_sideways(rect: pymupdf.Rect, seg: Segment, bound: pymupdf.Rect, obstacles: list[pymupdf.Rect],
                   size: float, ink: InkMap | None = None, bg=None) -> pymupdf.Rect:
    gutter = max(3.0, 0.6 * size)
    left, right = bound.x0, bound.x1
    for o in obstacles:
        if min(o.y1, rect.y1) - max(o.y0, rect.y0) > 1:
            if o.x1 <= rect.x0 + 0.4 * rect.width:
                left = max(left, o.x1 + gutter)
            elif o.x0 >= rect.x0 + 0.6 * rect.width:
                right = min(right, o.x0 - gutter)
    if ink is not None:
        if right > rect.x1:
            right = ink.free_side(rect, right, bg, +1)
        if left < rect.x0:
            left = ink.free_side(rect, left, bg, -1)
    new = pymupdf.Rect(rect)
    if seg.style.align == "center":
        # todo el espacio libre a ambos lados (puede ser asimétrico; ver _align_for)
        new.x0, new.x1 = min(rect.x0, left), max(rect.x1, right)
    else:
        # espacio libre a ambos lados; place_segment prueba primero el lado natural de la alineación
        new.x0, new.x1 = min(rect.x0, left), max(rect.x1, right)
    return new


def _align_for(align: str, rect: pymupdf.Rect, box: pymupdf.Rect) -> str:
    """Un texto centrado que solo pudo crecer hacia un lado se ancla al lado bloqueado (p. ej. un
    encabezado junto al número de página) en lugar de desplazar su centro."""
    lg, rg = rect.x0 - box.x0, box.x1 - rect.x1
    if align in ("left", "justify"):
        return "right" if lg > 1.0 and rg <= 1.0 else align  # solo pudo crecer hacia la izquierda
    if align == "right":
        return "left" if rg > 1.0 and lg <= 1.0 else align
    if abs(lg - rg) <= 1.0:
        return align
    return "left" if lg < rg else "right"


def place_rotated(page: pymupdf.Page, seg: Segment, fonts: FontResolver, min_scale: float,
                  min_size: float, dry: bool = False) -> tuple[float, bool, pymupdf.Rect]:
    """Etiqueta vertical: se maqueta en horizontal (una línea) y se gira alrededor de su origen."""
    st = seg.style
    choice = fonts.choose(st, (seg.translation or "") + seg.html)
    rect = pymupdf.Rect(seg.bbox)
    length = rect.height  # longitud original a lo largo del eje del texto
    letters = [c for c in layout.plain_text(seg.translation or "") if c.isalpha()]
    upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.7
    size = st.size * (choice.scale_cap if upper else choice.scale_x)
    hscale = 1.0
    if choice.source != "embedded":
        nat = layout.natural_width(seg.html, choice, size)
        if nat > 0:
            hscale = max(0.55, min(1.0, length / nat))
    words = layout.words_of(layout.parse((seg.translation or "").replace("<br>", " ")))
    avail = length * 1.12  # margen pequeño: las etiquetas suelen tener aire alrededor
    floor = max(min_scale, min(1.0, min_size / max(size, 0.1)))
    ox, oy = seg.origin or (rect.x1, rect.y1)
    res, ok, sc = None, False, 1.0
    for cond in (1.0, 0.96, 0.92):
        res = layout.try_layout(words, choice, size, hscale * cond, size, avail, 0, 0)
        if res.fits:
            ok = True
            break
    if not ok:
        sc = 0.97
        while sc > 0.3:
            res = layout.try_layout(words, choice, size * sc, hscale * 0.92, size, avail, 0, 0)
            if res.fits:
                break
            sc -= 0.03
        ok = sc >= floor - 1e-6
        if not ok and not dry:
            seg.issues.append(f"la traducción no cabe en el espacio original (reducida al {sc:.0%})")
    if not dry:
        layout.render(page, res, choice, ox, oy, "left", st.color, rotation=seg.rotation)
    return sc, ok, rect


def place_segment(page: pymupdf.Page, seg: Segment, fonts: FontResolver, obstacles: list[pymupdf.Rect],
                  containers: list[pymupdf.Rect], min_scale: float, min_size: float,
                  ink: InkMap | None = None, dry: bool = False) -> tuple[float, bool, pymupdf.Rect]:
    """Inserta la traducción con el motor propio. Devuelve (escala aplicada, cabe sin revisión, zona ocupada).
    Con dry=True solo calcula cómo quedaría, sin dibujar."""
    if seg.rotation:
        return place_rotated(page, seg, fonts, min_scale, min_size, dry)
    if seg.block_type == "curved" and seg.path:
        from app.pipeline.curved import place_curved

        return place_curved(page, seg, fonts, min_scale, dry)
    st = seg.style
    choice = fonts.choose(st, (seg.translation or "") + seg.html)
    choice.bold_scale = st.bold_scale
    rect = pymupdf.Rect(seg.bbox)
    n_orig = max(1, len(seg.line_rects))
    # igualar el tamaño visual: altura de mayúsculas si el texto es casi todo mayúsculas, si no la de x
    letters = [c for c in layout.plain_text(seg.translation or "") if c.isalpha()]
    upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.7
    size = st.size * (choice.scale_cap if upper else choice.scale_x)
    leading = st.line_height * st.size  # el interlineado original se conserva
    first = seg.baseline if seg.baseline is not None else rect.y0 + 0.8 * st.size
    orig_last = first + (n_orig - 1) * leading

    def limit_for(box: pymupdf.Rect) -> float:
        return max(orig_last, box.y1 - 0.22 * st.size)

    # escala horizontal calibrada: la fuente sustituta ocupa el mismo ancho que la original
    hscale = 1.0
    if choice.source != "embedded":
        nat = layout.natural_width(seg.html, choice, size)
        orig_w = sum(r[2] - r[0] for r in seg.line_rects)
        if nat > 0 and orig_w > 0:
            hscale = max(0.55, min(1.0, orig_w / nat))

    container = _container_for(rect, containers)
    bound = _bounds(rect, page.rect, container)
    bg = ink.background(rect) if ink is not None else None
    tall = _grow_down(rect, bound, obstacles, st.size, ink, bg)
    single = len(seg.line_rects) <= 1
    side = _grow_sideways(rect, seg, bound, obstacles, st.size, ink, bg) if single else rect
    sides = [side]
    if single:
        if st.align == "center":
            g = max(0.0, min(rect.x0 - side.x0, side.x1 - rect.x1))
            sides = [pymupdf.Rect(rect.x0 - g, rect.y0, rect.x1 + g, rect.y1), side]
        elif st.align == "right":  # crecer hacia la izquierda; si no hay sitio, hacia la derecha
            sides = [pymupdf.Rect(side.x0, rect.y0, rect.x1, rect.y1), pymupdf.Rect(rect.x0, rect.y0, side.x1, rect.y1)]
        else:  # izquierda/justificado: crecer hacia la derecha; si no hay sitio, hacia la izquierda
            sides = [pymupdf.Rect(rect.x0, rect.y0, side.x1, rect.y1), pymupdf.Rect(side.x0, rect.y0, rect.x1, rect.y1)]
        side = sides[0]
    wide = _grow_down(side, bound, obstacles, st.size, ink, bg) if single else tall
    words = layout.words_of(layout.parse(seg.translation or ""))
    floor = max(min_scale, min(1.0, min_size / max(size, 0.1)))

    # sangrías del original (texto que rodea un ícono o una imagen): la línea i usa la sangría de la
    # línea i original; solo en texto alineado a la izquierda o justificado
    indents = None
    if st.align in ("left", "justify") and len(seg.line_rects) > 1:
        lefts = [r[0] - rect.x0 for r in seg.line_rects]
        if max(lefts) > 0.5 * st.size:
            indents = [v if v > 0.5 * st.size else 0.0 for v in lefts]
            indents.append(min(indents))  # las líneas extra de la traducción usan la sangría mínima

    def attempt(box: pymupdf.Rect, s: float, condense: float):
        fb = first - 0.75 * size * (1 - s)  # al reducir se mantiene la parte superior de la primera línea
        ind = [i + (rect.x0 - box.x0) for i in indents] if indents else None
        res = layout.try_layout(words, choice, size * s, hscale * condense, leading * s, box.width, fb,
                                limit_for(box), ind)
        return res, fb

    # 1) caja original condensando levemente  2) crecer hacia abajo en espacio libre
    # 3) crecer a los lados (títulos de una línea)  4) reducir tamaño hasta el mínimo legible
    plan = [(rect, 1.0, c) for c in (1.0, 0.96, 0.92)]
    # una sola línea (títulos, encabezados): mejor crecer a los lados que partirla en dos
    growth = sides + [tall, wide] if single else [tall]
    for box in growth:
        if box != rect and all(box != b for b, _, _ in plan):
            plan += [(box, 1.0, c) for c in (1.0, 0.96, 0.92)]
    s = 0.97
    while s >= floor - 1e-6:
        plan.append((wide, s, 0.92))
        s -= 0.03
    chosen = None
    for box, sc, cond in plan:
        res, fb = attempt(box, sc, cond)
        if res.fits:
            chosen = (box, res, fb, sc)
            break
    ok = chosen is not None
    if not ok:
        # último recurso: nunca cortar texto; se reduce lo necesario y la página va a revisión
        sc = floor
        while sc > 0.3:
            sc -= 0.04
            res, fb = attempt(wide, sc, 0.92)
            if res.fits:
                break
        chosen = (wide, res, fb, sc)
        if not dry:
            seg.issues.append(f"la traducción no cabe en el espacio original (reducida al {sc:.0%})")
    box, res, fb, sc = chosen
    if ok and sc < 0.999 and not dry:
        seg.issues.append(f"texto reducido al {sc:.0%} para que quepa")
    if not dry:
        layout.render(page, res, choice, box.x0, fb, _align_for(st.align, rect, box), st.color)
    used_w = max((ln.width for ln in res.lines), default=0) * res.hscale
    eff = _align_for(st.align, rect, box)
    if eff == "center":
        x0 = box.x0 + (box.width - used_w) / 2
    elif eff == "right":
        x0 = box.x0 + box.width - used_w
    else:
        x0 = box.x0
    last = fb + (len(res.lines) - 1) * res.leading
    occupied = pymupdf.Rect(x0, fb - 0.8 * res.size, x0 + used_w, last + 0.25 * res.size)
    return sc, ok, occupied


def rebuild_page(page: pymupdf.Page, info: PageInfo, fonts: FontResolver, min_scale: float = 0.75,
                 min_size: float = 5.5, shorten=None) -> None:
    """Reconstruye una página completa (preparar + abreviar lo que no cabe + dibujar)."""
    job = prepare_page(page, info, fonts, min_scale, min_size)
    if job is None:
        return
    if shorten is not None:
        tight = job.tight()
        if tight:
            shorten(*tight)
    job.render()


def _shrink(r: pymupdf.Rect, d: float = 1.0) -> pymupdf.Rect:
    return pymupdf.Rect(r.x0 + d, r.y0 + d, r.x1 - d, r.y1 - d)


class PageJob:
    """Página ya preparada (texto original borrado) lista para calcular y dibujar las traducciones."""

    def __init__(self, run, targets, info, min_size: float = 5.5):
        self._run, self.targets, self.info, self.min_size = run, targets, info, min_size

    def tight(self):
        """Bloques que solo caben reduciendo mucho: (segmentos, {clave: máx. caracteres})."""
        res = {k: v for k, v in self._run(dry=True).items() if v[0] < 0.85 or not v[1]}
        if not res:
            return None
        segs = [s for s in self.targets if s.key in res]
        limits = {s.key: max(4, int(len(layout.plain_text(s.translation or "")) * max(0.7, res[s.key][0] ** 1.5)))
                  for s in segs}
        return segs, limits

    def render(self):
        """Dibuja. Que la traducción ocupe más o menos que el original no es un error (el español es más
        largo); solo se pide revisión si el texto quedó ilegible o se superpone con otro bloque."""
        results = self._run(dry=False)
        for s in self.targets:
            scale, _ok, _used = results[s.key]
            s.fit_scale = round(scale, 3)
            if s.style.size * scale < self.min_size - 0.05:
                self.info.flag(f"Texto muy pequeño tras ajustarlo ({s.key}, {s.style.size * scale:.1f} pt)")
        boxes = [(s.key, _shrink(results[s.key][2]), pymupdf.Rect(s.bbox)) for s in self.targets
                 if not s.rotation and s.block_type != "curved"]
        for i, (ka, a, oa) in enumerate(boxes):
            for kb, b, ob in boxes[i + 1:]:
                inter = a & b
                if inter.is_empty:
                    continue
                before = oa & ob  # las cajas originales ya se tocaban (p. ej. títulos muy juntos)
                grown = abs(inter) - (0 if before.is_empty else abs(before))
                if grown > 0.15 * min(abs(a), abs(b)):
                    self.info.flag(f"Dos bloques de texto se superponen ({ka}, {kb})")


def _redaction_rects(page: pymupdf.Page, lines: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
    """Rectángulos a redactar para borrar el texto de `lines` sin tocar los glifos que se conservan
    (íconos, símbolos, números) cuya caja toca esas líneas: la redacción elimina todo glifo cuya caja
    se solape con el rectángulo, así que en esas líneas se borra carácter a carácter con un trozo de su
    caja que no toque los glifos conservados."""
    raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    chars = [pymupdf.Rect(c["bbox"]) for b in raw["blocks"] if b.get("type") == 0 for l in b["lines"]
             for sp in l["spans"] for c in sp["chars"] if not c["c"].isspace()]
    def inside(r: pymupdf.Rect) -> bool:
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        return any(l.x0 - 0.5 <= cx <= l.x1 + 0.5 and l.y0 - 0.5 <= cy <= l.y1 + 0.5 for l in lines)
    target_chars, kept = [], []
    for r in chars:
        if inside(r):
            target_chars.append(r)
        else:
            # MuPDF usa una caja algo mayor que la de rawdict (caja de la fuente): margen de seguridad
            m = 0.08 * r.height
            kept.append(pymupdf.Rect(r.x0 - m, r.y0 - m, r.x1 + m, r.y1 + m))
    out: list[pymupdf.Rect] = []
    for line in lines:
        clash = [k for k in kept if k.intersects(line) and abs(k & line) > 0]
        if not clash:
            out.append(line)
            continue
        for c in target_chars:
            cx, cy = (c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2
            if not (line.x0 - 0.5 <= cx <= line.x1 + 0.5 and line.y0 - 0.5 <= cy <= line.y1 + 0.5):
                continue
            hits = [k for k in clash if abs(k & c) > 0]
            if not hits:
                out.append(c)
                continue
            # el mayor trozo de la caja del carácter libre de glifos conservados
            cands = [pymupdf.Rect(c.x0, c.y0, c.x1, min(k.y0 for k in hits) - 0.1),
                     pymupdf.Rect(c.x0, max(k.y1 for k in hits) + 0.1, c.x1, c.y1),
                     pymupdf.Rect(c.x0, c.y0, min(k.x0 for k in hits) - 0.1, c.y1),
                     pymupdf.Rect(max(k.x1 for k in hits) + 0.1, c.y0, c.x1, c.y1)]
            cands = [r for r in cands if r.width > 0.2 and r.height > 0.2]
            out.append(max(cands, key=lambda r: abs(r)) if cands else c)
    return out


def _raw_chars(page: pymupdf.Page) -> list[dict]:
    raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    out = []
    for b in raw["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            for sp in l["spans"]:
                for c in sp["chars"]:
                    if not c["c"].isspace():
                        out.append({"c": c["c"], "bbox": pymupdf.Rect(c["bbox"]), "origin": tuple(c["origin"]),
                                    "dir": tuple(l["dir"]), "size": sp["size"], "font": sp["font"],
                                    "color": sp["color"], "flags": sp["flags"]})
    return out


def _kept_chars_at_risk(page: pymupdf.Page, lines: list[pymupdf.Rect], rects: list[pymupdf.Rect]) -> list[dict]:
    """Glifos que se conservan pero cuya caja de fuente toca una zona a borrar (p. ej. el «1» gigante de
    una portadilla que envuelve a «CHAPTER»): la redacción de MuPDF también los eliminaría."""
    def inside(r):
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        return any(l.x0 - 0.5 <= cx <= l.x1 + 0.5 and l.y0 - 0.5 <= cy <= l.y1 + 0.5 for l in lines)
    return [c for c in _raw_chars(page) if not inside(c["bbox"])
            and any(abs(c["bbox"] & r) > 0 for r in rects)]


def _restore_kept_chars(page: pymupdf.Page, chars: list[dict], fonts: FontResolver) -> None:
    """Vuelve a dibujar, con su misma fuente embebida, los glifos conservados que la redacción eliminó."""
    present = [(c["c"], c["origin"]) for c in _raw_chars(page)]

    def survived(ch):
        return any(c == ch["c"] and abs(o[0] - ch["origin"][0]) < 0.6 and abs(o[1] - ch["origin"][1]) < 0.6
                   for c, o in present)

    for ch in chars:
        if survived(ch):
            continue
        font = fonts.original_font(ch["font"], ch["c"])
        if font is None:
            from app.pipeline.analyze import _is_bold, _is_italic, _is_mono, _is_serif
            from app.pipeline.types import Style

            name = ch["font"].split("+", 1)[-1]
            st = Style(font=name, size=ch["size"], color="#000000", bold=_is_bold(name, ch["flags"]),
                       italic=_is_italic(name, ch["flags"]), serif=_is_serif(name, ch["flags"]),
                       mono=_is_mono(name, ch["flags"]))
            font = fonts.choose(st, ch["c"]).face(st.bold, st.italic)
        ux, uy = ch["dir"]
        tw = pymupdf.TextWriter(page.rect)
        tw.append(ch["origin"], ch["c"], font=font, fontsize=ch["size"])
        morph = None
        if abs(uy) > 1e-3 or ux < 0:
            morph = (pymupdf.Point(ch["origin"]), pymupdf.Matrix(ux, -uy, uy, ux, 0, 0))
        tw.write_text(page, color=layout._rgb(f"#{ch['color'] & 0xFFFFFF:06x}"), morph=morph)


def prepare_page(page: pymupdf.Page, info: PageInfo, fonts: FontResolver, min_scale: float = 0.75,
                 min_size: float = 5.5) -> PageJob | None:
    targets = [s for s in info.segments if s.action == "translate" and s.translation]
    if not targets:
        return None
    ink = InkMap(page)  # render original, antes de borrar el texto
    ocr_targets = [s for s in targets if s.block_type == "ocr"]
    if ocr_targets:
        # texto dentro de imágenes: se borra de la propia imagen (inpainting), no con redacción
        from app.pipeline.ocr import erase_text_in_images

        erase_text_in_images(page, [pymupdf.Rect(r) for s in ocr_targets for r in s.line_rects])
    target_lines = [pymupdf.Rect(r) for s in targets if s.block_type != "ocr" for r in s.line_rects]
    rects = _redaction_rects(page, target_lines)
    at_risk = _kept_chars_at_risk(page, target_lines, rects)
    for r in rects:
        page.add_redact_annot(r, cross_out=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    if at_risk:
        _restore_kept_chars(page, at_risk, fonts)

    containers, shapes = _drawings(page)
    # el texto que se conserva (números, símbolos, texto en curva) también es un obstáculo
    kept_text = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks") if not pymupdf.Rect(b[:4]).is_empty]
    image_rects = [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()]
    def run(dry: bool) -> dict[str, tuple[float, bool]]:
        # zona ocupada por cada bloque: la original y, una vez colocado, la realmente usada
        occupied = {s.key: pymupdf.Rect(s.bbox) for s in info.segments}
        out = {}
        for s in targets:
            own = pymupdf.Rect(s.bbox)
            obstacles = [r for k, r in occupied.items() if k != s.key]
            # imágenes y gráficos que contienen el texto son fondos, no obstáculos
            obstacles += [r for r in image_rects + shapes if abs(own & r) < 0.5 * abs(own)]
            obstacles += [r for r in kept_text if abs(own & r) < 0.3 * abs(r)]
            scale, ok, used = place_segment(page, s, fonts, obstacles, containers, min_scale, min_size, ink, dry)
            occupied[s.key] = used | own
            out[s.key] = (scale, ok, used)
        return out

    return PageJob(run, targets, info, min_size)


def rebuild(doc: pymupdf.Document, pages: list[PageInfo], fonts: FontResolver, min_scale: float = 0.75,
            min_size: float = 5.5, on_page=None, shorten=None) -> None:
    # 1) preparar todas las páginas y detectar lo que no cabe bien
    jobs: list[PageJob] = []
    all_segs, all_limits = [], {}
    for info in pages:
        if on_page:
            on_page(info.number, "prepare")
        if info.kind == "blank":
            continue
        job = prepare_page(doc[info.number - 1], info, fonts, min_scale, min_size)
        if job is None:
            continue
        jobs.append(job)
        if shorten is not None:
            tight = job.tight()
            if tight:
                all_segs += tight[0]
                all_limits.update(tight[1])
    # 2) pedir versiones más breves de todo a la vez (en lotes paralelos)
    if shorten is not None and all_segs:
        try:
            shorten(all_segs, all_limits)
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudieron acortar traducciones: %s", e)
    # 3) dibujar
    for job in jobs:
        if on_page:
            on_page(job.info.number, "render")
        job.render()
