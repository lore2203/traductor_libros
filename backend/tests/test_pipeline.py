"""Prueba end-to-end con PDF sintético y traductor falso que alarga el texto (simula el español)."""
import pymupdf

from app.pipeline.analyze import analyze
from app.pipeline.runner import PipelineOptions, run_pipeline
from app.pipeline.translate import DictCache, FakeTranslator

from .conftest import OUT


def test_analyze_classifies_pages(sample_pdf):
    pages = analyze(pymupdf.open(sample_pdf))
    assert pages[0].kind in ("digital", "mixed") and pages[0].segments  # portada: texto sobre imagen
    assert pages[1].kind == "blank"
    toc = pages[2]
    keep = [s.text for s in toc.segments if s.action == "keep"]
    assert "12" in keep and "180" in keep  # números de página del índice se conservan
    assert any(s.text == "Sun signs" and s.action == "translate" for s in toc.segments)
    p4 = pages[3]
    assert any(s.text == "41" and s.action == "keep" for s in p4.segments)
    # dos columnas => dos párrafos distintos, no mezclados
    bodies = [s for s in p4.segments if s.block_type in ("body", "caption") and len(s.text) > 200]
    assert len(bodies) == 2


def test_full_pipeline_preserves_layout(sample_pdf):
    out = OUT / "pipeline"
    opts = PipelineOptions(detect_names=False)
    res = run_pipeline(sample_pdf, out, FakeTranslator(0.3), DictCache(),
                       {"Kim Farley": "NAME", "Carole Taylor": "NAME", "Jane Ewart": "NAME"}, {}, opts)
    r = res.report
    v = r["validaciones"]
    assert v["mismo_numero_de_paginas"] and v["mismas_dimensiones"]
    assert v["paginas_vacias_conservadas"] and v["imagenes_conservadas"]
    assert v["graficos_vectoriales_conservados"] and v["terminos_protegidos_intactos"]
    assert v["sin_marcadores_residuales"] and v["traduccion_completa"]
    assert res.output_pdf.name.endswith("(ES).pdf")

    out_doc = pymupdf.open(res.output_pdf)
    orig = pymupdf.open(sample_pdf)
    assert len(out_doc) == len(orig)
    text = " ".join(pg.get_text() for pg in out_doc)
    assert "978-0-7440-2366-4" in text.replace("\n", "")
    assert "Kim Farley" in text and "Carole Taylor" in text
    assert " ES" in text  # se insertó la "traducción"
    assert out_doc[1].get_text().strip() == ""  # vacía sigue vacía
    # todo el contenido traducido está presente (nunca se corta texto)
    for p in res.pages:
        for s in p.segments:
            if s.action == "translate":
                words = [w for w in s.text.split() if w.isalpha()][:3]
                page_text = out_doc[p.number - 1].get_text().replace("\n", " ")
                for w in words:
                    assert w in page_text, (s.key, w)
