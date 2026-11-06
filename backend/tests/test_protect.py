from app.pipeline.protect import Protector, restore


def test_protect_and_restore_roundtrip():
    p = Protector({"Kim Farley": "NAME", "DK": "BRAND"})
    src = "Project Editor Kim Farley, DK. ISBN 978-0-7440-2366-4, www.dk.com, info@dk.com ♈ ☉"
    pt = p.protect(src)
    assert "Kim Farley" not in pt.text
    assert "978-0-7440-2366-4" not in pt.text
    assert "www.dk.com" not in pt.text
    assert "info@dk.com" not in pt.text
    assert "♈" not in pt.text
    translated = pt.text.replace("Project Editor", "Editora de proyecto")
    restored, problems = restore(translated, pt.placeholders)
    assert problems == []
    assert restored == src.replace("Project Editor", "Editora de proyecto")


def test_restore_detects_missing_placeholder():
    p = Protector({"Carole Taylor": "NAME"})
    pt = p.protect("Written by Carole Taylor")
    _, problems = restore("Escrito por alguien", pt.placeholders)
    assert problems and "Carole Taylor" in problems[0]


def test_restore_tolerates_spacing():
    p = Protector({"Carole Taylor": "NAME"})
    pt = p.protect("Written by Carole Taylor")
    restored, problems = restore("Escrito por __ NAME_001 __", pt.placeholders)
    assert problems == [] and restored == "Escrito por Carole Taylor"


def test_html_tags_untouched():
    p = Protector({"b": "NAME"})
    pt = p.protect("<b>bold</b> text")
    assert pt.text.startswith("<b>") and pt.text.endswith("text")


def test_longest_term_first():
    p = Protector({"Kim": "NAME", "Kim Farley": "NAME"})
    pt = p.protect("Kim Farley and Kim")
    assert list(pt.placeholders.values()) == ["Kim Farley", "Kim"]
