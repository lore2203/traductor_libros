"""Selección de fuentes para el texto traducido.

1. Se reutiliza la fuente embebida original si contiene TODOS los glifos de la traducción (á, ñ, ¿...).
   En libros maquetados con InDesign las fuentes suelen ser subconjuntos de pocos glifos y no sirven.
2. Si no, se usa una fuente libre (OFL) de aspecto equivalente y con el mismo peso:
   - slab serif (Soho, Serifa, Rockwell, Lilita...)  -> Rokkitt 200-900
   - sans condensada (…Cond, …Cn, Compressed sans)   -> Roboto Condensed 200-900
   - sans normal                                     -> Noto Sans (pymupdf-fonts)
   - serif                                           -> Noto Serif si está instalada, si no la serif integrada
   Las fuentes estáticas están en backend/fonts (scripts/build_fonts.py).

Cada párrafo usa una familia CSS con dos caras: 'normal' = fuente base del párrafo y
'bold' = fuente de los fragmentos más pesados (<b>), cada una con su peso real.
"""
from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.pipeline.analyze import font_weight
from app.pipeline.types import Style

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]*>")
DEFAULT_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"

SLAB_HINTS = ("soho", "serifa", "rockwell", "slab", "lilita", "memphis", "clarendon", "archer", "museoslab",
              "egyptienne", "rokkitt", "arvo")
SANS_HINTS = ("sans", "helvet", "arial", "frutiger", "futura", "avenir", "din", "gotham", "myriad", "univers",
              "gill", "proxima", "roboto", "lato", "verdana", "calibri", "franklin", "akzidenz", "trade", "segoe")
COND_HINTS = ("cond", "cn", "compressed", "narrow", "comp", "xcn")
PYMUPDF_SANS = {(False, False): "notos", (True, False): "notosbo", (False, True): "notosit", (True, True): "notosbi"}
NOTO_SERIF = {(False, False): "NotoSerif-Regular.ttf", (True, False): "NotoSerif-Bold.ttf",
              (False, True): "NotoSerif-Italic.ttf", (True, True): "NotoSerif-BoldItalic.ttf"}
WEIGHTS = (200, 300, 400, 500, 600, 700, 800, 900)
# fuentes libres incluidas con el mismo diseño que la original (nombre normalizado -> archivo)
SAME_DESIGN = {"lilitaone": "LilitaOne-Regular.ttf"}


def outline_coverage(buf: bytes) -> set[int]:
    """Códigos Unicode con contorno real. Los subconjuntos TrueType de InDesign conservan el mapa de
    caracteres completo pero vacían los glifos que no se usaron (la "L" existe en el mapa y no se ve)."""
    import io

    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    tt = TTFont(io.BytesIO(buf), lazy=True)
    cmap = tt.getBestCmap() or {}
    covered: set[int] = set()
    if "glyf" in tt:
        glyf = tt["glyf"]
        for code, name in cmap.items():
            try:
                if glyf[name].numberOfContours != 0:
                    covered.add(code)
            except Exception:  # noqa: BLE001
                pass
    else:
        gs = tt.getGlyphSet()
        for code, name in cmap.items():
            try:
                pen = BoundsPen(gs)
                gs[name].draw(pen)
                if pen.bounds:
                    covered.add(code)
            except Exception:  # noqa: BLE001
                pass
    return covered


def classify_font(name: str, serif_flag: bool, mono_flag: bool) -> str:
    n = name.lower().replace("-", "").replace(" ", "")
    if mono_flag or "mono" in n or "courier" in n:
        return "mono"
    if any(h in n for h in SLAB_HINTS):
        return "slab"
    if any(h in n for h in SANS_HINTS):
        return "sanscond" if any(h in n for h in COND_HINTS) else "sans"
    return "serif" if serif_flag else "sans"


BUILTIN = {  # fuentes Base14 integradas (cobertura latina) como último recurso
    "serif": {("normal", "normal"): "tiro", ("bold", "normal"): "tibo", ("normal", "italic"): "tiit",
              ("bold", "italic"): "tibi"},
    "sans": {("normal", "normal"): "helv", ("bold", "normal"): "hebo", ("normal", "italic"): "heit",
             ("bold", "italic"): "hebi"},
    "mono": {("normal", "normal"): "cour", ("bold", "normal"): "cobo", ("normal", "italic"): "coit",
             ("bold", "italic"): "cobi"},
}


@dataclass
class FontChoice:
    faces: dict  # (weight, style) -> pymupdf.Font ; weight normal|bold, style normal|italic
    source: str  # embedded | free | builtin
    # factor de tamaño para igualar la altura de x / de mayúsculas de la fuente original
    scale_x: float = 1.0
    scale_cap: float = 1.0

    def face(self, bold: bool, italic: bool) -> pymupdf.Font:
        w, s = ("bold" if bold else "normal"), ("italic" if italic else "normal")
        for key in ((w, s), (w, "normal"), ("normal", s), ("normal", "normal")):
            if key in self.faces:
                return self.faces[key]
        return next(iter(self.faces.values()))


class FontResolver:
    def __init__(self, doc: pymupdf.Document, work_dir: Path, fonts_dirs: str = ""):
        self.doc = doc
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.archive = pymupdf.Archive(str(self.work_dir))
        dirs = [Path(d) for d in (fonts_dirs or "").split(os.pathsep) if d]
        self.dirs = [d for d in dirs + [DEFAULT_FONTS_DIR, Path("/usr/share/fonts/truetype/noto")] if d.is_dir()]
        self._embedded: dict[str, tuple[str, pymupdf.Font]] | None = None
        self._files: dict[str, str | None] = {}
        self._fonts: dict[str, pymupdf.Font] = {}
        self._metrics: dict[str, tuple[float, float] | None] = {}

    # ------------------------------------------------------------------ utilidades de archivos
    def _copy(self, filename: str) -> str | None:
        """Copia una fuente de los directorios configurados al archivo de trabajo (Archive)."""
        if filename in self._files:
            return self._files[filename]
        result = None
        for d in self.dirs:
            p = d / filename
            if p.is_file():
                target = self.work_dir / filename
                if not target.exists():
                    target.write_bytes(p.read_bytes())
                result = filename
                break
        self._files[filename] = result
        return result

    def _pymupdf_font(self, code: str) -> str | None:
        key = f"{code}.otf"
        if key not in self._files:
            try:
                target = self.work_dir / key
                if not target.exists():
                    target.write_bytes(pymupdf.Font(code).buffer)
                self._files[key] = key
            except Exception as e:  # noqa: BLE001
                log.debug("pymupdf-fonts no disponible: %s", e)
                self._files[key] = None
        return self._files[key]

    # ------------------------------------------------------------------ fuentes embebidas
    def _load_embedded(self) -> dict[str, tuple[str, pymupdf.Font]]:
        if self._embedded is not None:
            return self._embedded
        found: dict[str, tuple[str, pymupdf.Font, set[int]]] = {}
        seen: set[int] = set()
        for page in self.doc:
            for xref, ext, _ftype, basefont, *_ in page.get_fonts(full=True):
                if xref in seen or xref == 0:
                    continue
                seen.add(xref)
                name = basefont.split("+", 1)[1] if "+" in basefont[:8] else basefont
                if name in found or ext not in ("ttf", "otf"):
                    continue
                try:
                    _, fext, _, buf = self.doc.extract_font(xref)
                    if not buf:
                        continue
                    font = pymupdf.Font(fontbuffer=buf)
                    if font.glyph_count < 100:  # subconjunto: no sirve para texto nuevo
                        continue
                    try:
                        covered = outline_coverage(buf)
                    except Exception:  # noqa: BLE001
                        covered = set()  # no se puede verificar: no se reutiliza
                    fname = f"emb_{xref}.{fext}"
                    (self.work_dir / fname).write_bytes(buf)
                    found[name] = (fname, font, covered)
                except Exception as e:  # noqa: BLE001
                    log.debug("No se pudo cargar la fuente %s: %s", name, e)
        self._embedded = found
        return found

    def original_font(self, basefont: str, ch: str) -> pymupdf.Font | None:
        """Fuente embebida original (aunque sea un subconjunto) si tiene el glifo con contorno: sirve para
        volver a dibujar exactamente un glifo conservado (números, símbolos)."""
        name = basefont.split("+", 1)[-1]
        key = "orig:" + name
        if key not in self._fonts:
            font, covered = None, set()
            try:
                for page in self.doc:
                    for xref, ext, _t, bf, *_ in page.get_fonts(full=True):
                        if xref and bf.split("+", 1)[-1] == name:
                            buf = self.doc.extract_font(xref)[3]
                            if buf:
                                font = pymupdf.Font(fontbuffer=buf)
                                try:
                                    covered = outline_coverage(buf)
                                except Exception:  # noqa: BLE001
                                    covered = {c for c in range(32, 0x2FFF) if font.has_glyph(c)}
                            raise StopIteration
            except StopIteration:
                pass
            except Exception as e:  # noqa: BLE001
                log.debug("No se pudo cargar la fuente original %s: %s", name, e)
            self._fonts[key] = (font, covered)
        font, covered = self._fonts[key]
        return font if font is not None and ord(ch) in covered else None

    # ------------------------------------------------------------------ fuentes libres equivalentes
    def free_face(self, font_name: str, bold: bool, italic: bool, serif: bool, mono: bool) -> str | None:
        """Archivo de fuente libre equivalente para una fuente original concreta."""
        norm = re.sub(r"[^a-z]", "", font_name.lower())
        for key, fname in SAME_DESIGN.items():
            if norm.startswith(key) and not italic:
                got = self._copy(fname)
                if got:
                    return got
        kind = classify_font(font_name, serif, mono)
        weight = font_weight(font_name, bold)
        w = min(WEIGHTS, key=lambda x: abs(x - weight))
        it = "-Italic" if italic else ""
        if kind == "slab":
            if italic:  # Roboto Slab no tiene cursiva
                return self._copy(f"Rokkitt-{min(900, w + 100)}-Italic.ttf")
            return self._copy(f"RobotoSlab-{w}.ttf")
        if kind == "sanscond":
            return self._copy(f"RobotoCondensed-{w}{it}.ttf")
        if kind == "serif":
            return self._copy(NOTO_SERIF[(weight >= 600, italic)])
        if kind == "mono":
            return None
        return self._pymupdf_font(PYMUPDF_SANS[(weight >= 600, italic)])

    # ------------------------------------------------------------------ métricas (altura de x / mayúsculas)
    def _orig_metrics(self, name: str) -> tuple[float, float] | None:
        """Altura de x y de mayúsculas (en em) de la fuente original embebida."""
        if name in self._metrics:
            return self._metrics[name]
        result = None
        try:
            for page in self.doc:
                for xref, ext, _t, basefont, *_ in page.get_fonts(full=True):
                    if (basefont.split("+", 1)[1] if "+" in basefont[:8] else basefont) == name and xref:
                        buf = self.doc.extract_font(xref)[3]
                        result = font_metrics(buf, ext) if buf else None
                        raise StopIteration
        except StopIteration:
            pass
        except Exception as e:  # noqa: BLE001
            log.debug("Sin métricas para %s: %s", name, e)
        self._metrics[name] = result
        return result

    def _file_metrics(self, filename: str) -> tuple[float, float] | None:
        key = "file:" + filename
        if key not in self._metrics:
            try:
                path = self.work_dir / filename
                self._metrics[key] = font_metrics(path.read_bytes(), path.suffix.lstrip("."))
            except Exception as e:  # noqa: BLE001
                log.debug("Sin métricas para %s: %s", filename, e)
                self._metrics[key] = None
        return self._metrics[key]

    # ------------------------------------------------------------------ API
    def _load(self, ref: str, builtin: bool = False) -> pymupdf.Font:
        if ref not in self._fonts:
            self._fonts[ref] = pymupdf.Font(ref) if builtin else pymupdf.Font(fontfile=str(self.work_dir / ref))
        return self._fonts[ref]

    def _family(self, faces: dict[tuple[str, str], str], source: str) -> FontChoice:
        return FontChoice({k: self._load(f) for k, f in faces.items()}, source)

    def choose(self, style: Style, translation_html: str) -> FontChoice:
        chars = set(html.unescape(TAG_RE.sub("", translation_html))) - {" ", "\n", "\t", " "}
        base_style = "italic" if style.italic else "normal"
        variants = style.variants or {}

        # 1) fuentes embebidas completas (p. ej. Roboto Slab, Lilita One, Helvetica)
        emb = self._load_embedded()
        main = emb.get(style.font)
        if main and all(ord(c) in main[2] or c.isspace() for c in chars):
            faces = {("normal", base_style): main[0]}
            ok = True
            for v, fontname in variants.items():
                e = emb.get(fontname)
                if not e or not all(ord(c) in e[2] or c.isspace() for c in chars):
                    ok = False
                    break
                faces[("bold" if "bold" in v else "normal", "italic" if "italic" in v else base_style)] = e[0]
            if ok:
                return self._family(faces, "embedded")

        # 2) fuentes libres con el mismo aspecto y peso
        main_file = self.free_face(style.font, style.bold, style.italic, style.serif, style.mono)
        if main_file:
            faces = {("normal", base_style): main_file}
            base_w = font_weight(style.font, style.bold)
            for v, fontname in variants.items():
                f = self.free_face(fontname, True, "italic" in v or style.italic, style.serif, style.mono)
                if f:
                    faces[("bold" if "bold" in v else "normal", "italic" if "italic" in v else base_style)] = f
            if ("bold", base_style) not in faces:
                heavier = self.free_face(_with_weight(style.font, min(900, base_w + 300)), True, style.italic,
                                         style.serif, style.mono)
                if heavier:
                    faces[("bold", base_style)] = heavier
            if ("normal", "italic") not in faces and base_style == "normal":
                ital = self.free_face(style.font, style.bold, True, style.serif, style.mono)
                if ital:
                    faces[("normal", "italic")] = ital
            choice = self._family(faces, "free")
            om, fm = self._orig_metrics(style.font), self._file_metrics(main_file)
            if om and fm:
                clamp = lambda v: max(0.8, min(1.35, v))
                if om[0] and fm[0]:
                    choice.scale_x = clamp(om[0] / fm[0])
                if om[1] and fm[1]:
                    choice.scale_cap = clamp(om[1] / fm[1])
            return choice

        # 3) fuentes integradas de MuPDF
        kind = classify_font(style.font, style.serif, style.mono)
        table = BUILTIN.get(kind, BUILTIN["sans"] if kind != "slab" else BUILTIN["serif"])
        faces = {k: self._load(v, builtin=True) for k, v in table.items()}
        if style.bold:
            faces[("normal", "normal")] = faces[("bold", "normal")]
        return FontChoice(faces, "builtin")


def font_metrics(buf: bytes, ext: str) -> tuple[float, float] | None:
    """(altura de x, altura de mayúsculas) en em, midiendo glifos reales (CFF) o la tabla OS/2."""
    import io

    from fontTools.pens.boundsPen import BoundsPen

    def from_glyphs(glyphset, scale):
        def top(names):
            for g in names:
                if g in glyphset:
                    pen = BoundsPen(glyphset)
                    glyphset[g].draw(pen)
                    if pen.bounds:
                        return pen.bounds[3] * scale
            return 0.0
        return top("xzvwuyn"), top("HIETLFZ")

    if ext == "cff":
        from fontTools.cffLib import CFFFontSet

        cff = CFFFontSet()
        cff.decompile(io.BytesIO(buf), None)
        top = cff[cff.fontNames[0]]
        xh, cap = from_glyphs(top.CharStrings, top.FontMatrix[0])
        return (xh, cap) if (xh or cap) else None
    from fontTools.ttLib import TTFont

    tt = TTFont(io.BytesIO(buf))
    upm = tt["head"].unitsPerEm
    os2 = tt["OS/2"] if "OS/2" in tt else None
    xh = getattr(os2, "sxHeight", 0) / upm if os2 else 0
    cap = getattr(os2, "sCapHeight", 0) / upm if os2 else 0
    if not xh or not cap:
        gx, gc = from_glyphs(tt.getGlyphSet(), 1 / upm)
        xh, cap = xh or gx, cap or gc
    return (xh, cap) if (xh or cap) else None


def _with_weight(name: str, weight: int) -> str:
    """Nombre sintético con un peso dado, conservando familia y anchura (para elegir la cara bold)."""
    word = {200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold",
            800: "ExtraBold", 900: "Black"}[min(WEIGHTS, key=lambda x: abs(x - weight))]
    stripped = re.sub(r"(?i)(extra|ultra|semi|demi)?(light|regular|book|medium|bold|heavy|black|thin)", "", name)
    return f"{stripped}-{word}"
