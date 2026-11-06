"""CLI de desarrollo: traduce un PDF sin frontend ni API.

Uso:
  python -m app.cli translate libro.pdf --out salida/ [--pages 1-12,41] [--fake] [--protect "Kim Farley"]
  python -m app.cli analyze libro.pdf [--pages 1-5]     # muestra segmentos detectados sin traducir
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from app.config import get_settings


def parse_pages(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.update(range(int(a), int(b) + 1))
        elif part.strip():
            pages.add(int(part))
    return pages


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


def cmd_analyze(args) -> None:
    import pymupdf

    from app.pipeline.analyze import analyze

    doc = pymupdf.open(args.pdf)
    only = parse_pages(args.pages)
    for info in analyze(doc):
        if only and info.number not in only:
            continue
        print(f"\n=== Página {info.number} [{info.kind}] imgs={info.image_count} vect={info.drawing_count} "
              f"{info.review_reasons}")
        for s in info.segments:
            print(f"  {s.key} {s.action:9} {s.block_type:8} {s.style.size:5.1f}pt {s.style.align:7} "
                  f"{s.style.font[:22]:22} | {s.html[:100]}")


def cmd_translate(args) -> None:
    from app.db.cache import SqlCache
    from app.db.session import SessionLocal
    from app.pipeline.runner import PipelineOptions, run_pipeline
    from app.pipeline.translate import DeepSeekTranslator, FakeTranslator

    st = get_settings()
    migrate()
    translator = FakeTranslator() if args.fake else DeepSeekTranslator(st.deepseek_api_key, st.deepseek_model,
                                                                       st.deepseek_base_url,
                                                                       thinking=st.deepseek_thinking)
    session = SessionLocal()
    t0 = time.time()
    last = {"stage": None}

    def progress(stage, done, total, page):
        if stage != last["stage"]:
            print(f"\n[{stage}]", end="", flush=True)
            last["stage"] = stage
        print(f"\r[{stage}] {done}/{total}" + (f" (página {page})" if page else "") + " " * 10, end="", flush=True)

    opts = PipelineOptions(min_font_scale=st.min_font_scale, min_font_size_pt=st.min_font_size_pt,
                           concurrency=st.translation_concurrency, batch_chars=st.translation_batch_chars,
                           batch_items=st.translation_batch_max_segments, fonts_dirs=st.fonts_dirs,
                           only_pages=parse_pages(args.pages), detect_names=not args.fake,
                           visual_check=not args.no_visual)
    terms = {t: "NAME" for t in args.protect or []}
    result = run_pipeline(Path(args.pdf), Path(args.out), translator, SqlCache(session), terms, {}, opts, progress)
    session.close()
    r = result.report
    print(f"\n\nListo en {time.time() - t0:.0f}s -> {result.output_pdf}")
    print(f"Reporte: {result.report_path}")
    print("Validaciones:", {k: ("OK" if v else "FALLA") for k, v in r["validaciones"].items()})
    print("Estadísticas:", r["estadisticas"])
    print(f"Páginas para revisión: {len(r['paginas_para_revision'])}")
    for p in r["paginas_para_revision"][:30]:
        print(f"  pág. {p['pagina']}: {'; '.join(p['motivos'])[:200]}")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("pdf")
    a.add_argument("--pages")
    t = sub.add_parser("translate")
    t.add_argument("pdf")
    t.add_argument("--out", default="data/outputs/cli")
    t.add_argument("--pages", help="solo traducir estas páginas, p. ej. 1-10,41")
    t.add_argument("--fake", action="store_true", help="traductor falso sin API (pruebas de maquetación)")
    t.add_argument("--protect", action="append", help="término protegido adicional")
    t.add_argument("--no-visual", action="store_true", help="omitir comparación visual (más rápido)")
    args = ap.parse_args(argv)
    {"analyze": cmd_analyze, "translate": cmd_translate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
