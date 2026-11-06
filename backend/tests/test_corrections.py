"""Regresiones de la ronda de correcciones (segmentación, sangrías, fuentes, avisos y texto curvo)."""
import math
from pathlib import Path

import pymupdf

from app.pipeline import layout
from app.pipeline.analyze import analyze
from app.pipeline.curved import place_curved
from app.pipeline.fonts import FontChoice, outline_coverage
from app.pipeline.rebuild import _redaction_rects
from app.pipeline.translate import check_translation

FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"


def _segments(page_builder):
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=500)
    page_builder(page)
    return analyze(doc)[0].segments


def _translatable(segs):
    return [s for s in segs if s.action == "translate"]


def test_big_icon_does_not_split_paragraph():
    def build(page):
        page.insert_text((20, 120), "+", fontsize=30)  # ícono grande junto a la segunda línea
        for i, t in enumerate(["The positive signs have an extroverted",
                               "and upbeat quality. They need activity",
                               "and people time with friends."]):
            page.insert_text((50, 100 + i * 14), t, fontsize=11)
    segs = _translatable(_segments(build))
    assert len(segs) == 1 and len(segs[0].line_rects) == 3
    assert any(s.text == "+" and s.action == "keep" for s in _segments(build))


def test_ellipsis_in_prose_is_not_an_index_leader():
    def build(page):
        page.insert_text((20, 100), "Mercury in Sagittarius, and so on.... Together,", fontsize=11)
        page.insert_text((20, 114), "they create a unique birth chart.", fontsize=11)
    segs = _translatable(_segments(build))
    assert len(segs) == 1
    assert "so on.... Together" in segs[0].text


def test_toc_rows_still_split_numbers():
    def build(page):
        for i, (t, n) in enumerate([("What Is Astrology?", "12"), ("In the Beginning", "14"),
                                    ("Astrology Today", "16")]):
            page.insert_text((20, 100 + i * 20), t, fontsize=12)
            page.insert_text((300, 100 + i * 20), n, fontsize=12)
    segs = _segments(build)
    assert [s.text for s in segs if s.action == "translate"] == ["What Is Astrology?", "In the Beginning",
                                                                  "Astrology Today"]
    assert [s.text for s in segs if s.action == "keep"] == ["12", "14", "16"]


def test_layout_respects_per_line_indent():
    fonts = FontChoice({("normal", "normal"): pymupdf.Font("helv")}, "builtin")
    words = layout.words_of(layout.parse("palabra " * 30))
    res = layout.try_layout(words, fonts, 10, 1.0, 12, 200, 50, 1000, indents=[40, 40, 0])
    assert res.fits
    assert res.lines[0].width <= 160 + 0.5 and res.lines[1].width <= 160 + 0.5
    assert res.indent(0) == 40 and res.indent(5) == 0
    doc = pymupdf.open()
    page = doc.new_page()
    layout.render(page, res, fonts, 100, 50, "left", "#000000")
    first = min((w for w in page.get_text("words") if w[1] < 55), key=lambda w: w[0])
    assert abs(first[0] - 140) < 1.5  # la primera línea empieza tras la sangría


def test_redaction_keeps_overlapping_icon():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((20, 128), "+", fontsize=30)  # como en la pág. 28: el ícono toca la línea de encima
    page.insert_text((20, 100), "Heading text here", fontsize=11)
    line = pymupdf.Rect(20, 92, 120, 101)
    for r in _redaction_rects(page, [line]):
        page.add_redact_annot(r)
    page.apply_redactions(images=0, graphics=0, text=0)
    text = page.get_text()
    assert "+" in text and "Heading" not in text


def test_outline_coverage_detects_empty_glyphs():
    from fontTools.ttLib import TTFont
    import io

    buf = (FONTS_DIR / "LilitaOne-Regular.ttf").read_bytes()
    assert ord("Í") in outline_coverage(buf)
    tt = TTFont(io.BytesIO(buf))
    glyf = tt["glyf"]
    name = tt.getBestCmap()[ord("L")]
    glyf[name].numberOfContours = 0  # como en los subconjuntos de InDesign: está en el mapa pero vacío
    glyf[name].coordinates = []
    glyf[name].endPtsOfContours = []
    glyf[name].flags = []
    out = io.BytesIO()
    tt.save(out)
    cov = outline_coverage(out.getvalue())
    assert ord("L") not in cov and ord("A") in cov


def test_number_check_accepts_spelled_decades_and_numbers():
    assert check_translation("revolution captures the 1960s.", "cautiva los años sesenta.") == []
    assert check_translation("The 1960s", "Los años 60") == []
    assert check_translation("divided into 12 houses", "dividida en doce casas") == []
    assert check_translation("In 1990 there were 12 signs", "En 1980 había 12 signos") == [
        "los números no coinciden con el original"]


def test_intentionally_kept_text_is_not_flagged():
    for t in ("Howard Sasportas, The Twelve Houses",
              "Through the Looking Glass: A Search for the Self in the Mirror of Relationships",
              "cardinal 28, 29, 31", "IC (Imum Coeli) 23, 138-39, 169, 171,"):
        assert check_translation(t, t) == [], t
    assert check_translation("The planets are important in your chart",
                             "The planets are important in your chart") == ["posible texto sin traducir"]


def test_curved_text_is_chained_translated_and_redrawn_on_its_path():
    doc = pymupdf.open()
    page = doc.new_page()
    font = pymupdf.Font("helv")
    cx, cy, rad = 300, 400, 120
    for i, ch in enumerate("SAGITTARIUS"):  # rótulo en arco, letra a letra
        ang = math.radians(-120 + i * 6)
        x, y = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
        t = ang + math.pi / 2
        tw = pymupdf.TextWriter(page.rect)
        tw.append((x, y), ch, font=font, fontsize=9)
        tw.write_text(page, morph=(pymupdf.Point(x, y),
                                   pymupdf.Matrix(math.cos(t), -math.sin(t), math.sin(t), math.cos(t), 0, 0)))
    info = analyze(doc)[0]
    curved = [s for s in info.segments if s.block_type == "curved"]
    assert [s.text for s in curved] == ["SAGITTARIUS"]
    seg = curved[0]
    seg.translation = "SAGITARIO"

    class Fonts:
        def choose(self, style, text):
            return FontChoice({("normal", "normal"): font}, "builtin")

    for r in _redaction_rects(page, [pymupdf.Rect(r) for r in seg.line_rects]):
        page.add_redact_annot(r)
    page.apply_redactions(images=0, graphics=0, text=0)
    scale, ok, _ = place_curved(page, seg, Fonts(), 0.75)
    assert ok
    raw = page.get_text("rawdict")
    lines = [l for b in raw["blocks"] for l in b.get("lines", [])]
    text = "".join(c["c"] for l in lines for s in l["spans"] for c in s["chars"])
    assert "SAGITARIO" in text and "SAGITTARIUS" not in text
    # cada letra sigue la tangente del arco (no queda horizontal)
    dys = [l["dir"][1] for l in lines]
    assert max(dys) - min(dys) > 0.3


def test_big_kept_number_survives_erasing_text_inside_its_box(tmp_path):
    """Portadilla de capítulo: el «1» gigante envuelve a «CHAPTER»; al borrar «CHAPTER» el «1» debe seguir."""
    from app.pipeline.fonts import FontResolver
    from app.pipeline.rebuild import _kept_chars_at_risk, _restore_kept_chars

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((300, 400), "1", fontsize=190)
    page.insert_text((300, 250), "CHAPTER", fontsize=17)
    line = pymupdf.Rect(300, 238, 380, 252)
    rects = _redaction_rects(page, [line])
    risk = _kept_chars_at_risk(page, [line], rects)
    assert [c["c"] for c in risk] == ["1"]
    for r in rects:
        page.add_redact_annot(r)
    page.apply_redactions(images=0, graphics=0, text=0)
    _restore_kept_chars(page, risk, FontResolver(doc, tmp_path))
    text = page.get_text()
    assert "1" in text and "CHAPTER" not in text
