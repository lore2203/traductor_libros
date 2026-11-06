import numpy as np
import pymupdf

from app.pipeline import layout
from app.pipeline.fonts import FontChoice
from app.pipeline.ocr import erase_text_in_images


def _fonts():
    return FontChoice({("normal", "normal"): pymupdf.Font("helv"), ("bold", "normal"): pymupdf.Font("hebo")}, "builtin")


def test_parse_tags_and_breaks():
    pieces = layout.parse('Hola <b>mundo</b><br><span style="color:#ff0000">rojo</span> &amp; fin')
    assert pieces[1].bold and pieces[1].text == "mundo"
    assert pieces[2] is None
    assert pieces[3].color == "#ff0000"
    assert pieces[4].text == " & fin"


def test_forced_breaks_and_wrapping():
    fonts = _fonts()
    words = layout.words_of(layout.parse("uno dos<br>tres " + "palabra " * 20))
    res = layout.try_layout(words, fonts, 10, 1.0, 12, 100, 50, 1000)
    assert res.fits
    assert [w.pieces[0].text for w in res.lines[0].words] == ["uno", "dos"]
    assert res.lines[0].forced
    assert all(l.width <= res.max_w + 0.5 for l in res.lines)


def test_does_not_fit_when_too_many_lines():
    fonts = _fonts()
    words = layout.words_of(layout.parse("palabra " * 50))
    res = layout.try_layout(words, fonts, 10, 1.0, 12, 100, 50, 60)
    assert not res.fits


def test_hscale_allows_more_text_per_line():
    fonts = _fonts()
    text = "palabra " * 10
    a = layout.try_layout(layout.words_of(layout.parse(text)), fonts, 10, 1.0, 12, 120, 50, 1000)
    b = layout.try_layout(layout.words_of(layout.parse(text)), fonts, 10, 0.7, 12, 120, 50, 1000)
    assert len(b.lines) < len(a.lines)


def test_render_writes_all_text():
    doc = pymupdf.open()
    page = doc.new_page()
    fonts = _fonts()
    words = layout.words_of(layout.parse("Texto <b>completo</b> con eñe y acentos: canción"))
    res = layout.try_layout(words, fonts, 11, 0.9, 13, 300, 100, 500)
    layout.render(page, res, fonts, 50, 100, "justify", "#333333")
    text = page.get_text()
    assert "completo" in text and "canción" in text and "eñe" in text


def test_inpainting_removes_text_from_image():
    # imagen azul con texto blanco: tras el borrado, la zona del texto debe quedar azul
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    src = pymupdf.open()
    sp = src.new_page(width=300, height=200)
    sp.draw_rect(sp.rect, fill=(0.1, 0.3, 0.7), color=None)
    sp.insert_text((40, 110), "TITLE", fontsize=40, color=(1, 1, 1), fontname="hebo")
    pix = sp.get_pixmap(dpi=144)
    page.insert_image(page.rect, pixmap=pix)
    n = erase_text_in_images(page, [pymupdf.Rect(38, 78, 170, 116)])
    assert n == 1
    out = page.get_pixmap(dpi=72)
    arr = np.frombuffer(out.samples, dtype=np.uint8).reshape(out.height, out.width, out.n)
    zone = arr[80:115, 40:165, :3].astype(int)
    white = ((zone > 200).all(axis=2)).mean()
    assert white < 0.02, white
