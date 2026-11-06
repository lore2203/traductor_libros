"""Genera instancias estáticas (por peso) de fuentes variables libres (OFL) en backend/fonts/.

Uso: python scripts/build_fonts.py <carpeta_con_fuentes_variables>
Fuentes: https://github.com/google/fonts (ofl/rokkitt, ofl/robotocondensed, apache/robotoslab)
"""
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parent.parent / "fonts"
FAMILIES = {"Rokkitt": "Rokkitt", "RobotoCondensed": "RobotoCondensed", "RobotoSlab": "RobotoSlab"}
WEIGHTS = [200, 300, 400, 500, 600, 700, 800, 900]

OUT.mkdir(exist_ok=True)
for fam in FAMILIES:
    for italic in (False, True):
        src = SRC / f"{fam}{'-Italic' if italic else ''}[wght].ttf"
        if not src.exists():
            continue
        for w in WEIGHTS:
            font = instantiateVariableFont(TTFont(src), {"wght": w}, updateFontNames=False)
            dst = OUT / f"{fam}-{w}{'-Italic' if italic else ''}.ttf"
            font.save(dst)
            print("ok", dst.name, dst.stat().st_size // 1024, "KB")
