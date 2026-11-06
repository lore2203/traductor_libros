from app.pipeline.protect import Protector
from app.pipeline.translate import DictCache, FakeTranslator, check_translation, sanitize_html, translate_segments
from app.pipeline.types import Segment, Style


def seg(key, text):
    return Segment(key=key, page_no=1, bbox=(0, 0, 100, 20), line_rects=[(0, 0, 100, 20)], style=Style(),
                   text=text, html=text)


class DroppingTranslator(FakeTranslator):
    """Omite un id y altera un marcador en el primer intento."""

    def __init__(self):
        super().__init__(0)
        self.first = True

    def translate_batch(self, items, context):
        res = super().translate_batch(items, context)
        if self.first:
            self.first = False
            res.pop(items[0]["id"])
            if len(items) > 1:
                res[items[1]["id"]]["translation"] = "texto sin marcador"
        return res


def test_missing_ids_and_broken_placeholders_are_retried():
    segs = [seg("p001_s001", "Hello world"), seg("p001_s002", "Edited by Kim Farley")]
    tr = DroppingTranslator()
    stats = translate_segments(segs, tr, DictCache(), Protector({"Kim Farley": "NAME"}))
    assert stats.failed == 0
    assert all(s.translation for s in segs)
    assert "Kim Farley" in segs[1].translation
    assert tr.calls >= 2


def test_cache_avoids_second_call():
    cache = DictCache()
    segs = [seg("p001_s001", "Hello world")]
    translate_segments(segs, FakeTranslator(), cache, Protector())
    tr2 = FakeTranslator()
    segs2 = [seg("p001_s001", "Hello world")]
    stats = translate_segments(segs2, tr2, cache, Protector())
    assert tr2.calls == 0 and stats.cached == 1


def test_check_translation_flags_numbers_and_untranslated():
    assert "los números no coinciden con el original" in check_translation("In 1990 there were 12", "En 1991 había 12")
    assert "posible texto sin traducir" in check_translation("The sun is very bright", "The sun is very bright")
    assert check_translation("The sun 12", "El sol 12") == []


def test_sanitize_html_escapes_unknown_tags():
    assert sanitize_html("<b>hola</b> <script>x</script>") == "<b>hola</b> &lt;script&gt;x&lt;/script&gt;"
    assert sanitize_html("<b>abierto") == "<b>abierto</b>"
