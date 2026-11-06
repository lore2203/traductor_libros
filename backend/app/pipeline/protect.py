"""Protección de contenido: reemplaza términos que no deben traducirse por marcadores y los restaura.

Ejemplo: "Edited by Kim Farley, ISBN 978-0-7440-2366-4" ->
         "Edited by __NAME_001__, ISBN __ISBN_001__"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PLACEHOLDER_RE = re.compile(r"__\s*([A-Z]+)\s*_\s*(\d{3})\s*__")

# El orden importa: los patrones más específicos primero.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("URL", re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+[^\s<>()\"'.,;:!?]", re.I)),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("ISBN", re.compile(r"\b(?:97[89][\s-]?)?\d{1,5}[\s-]\d{1,7}[\s-]\d{1,7}[\s-][\dX]\b|\b97[89]\d{10}\b")),
    # símbolos astrológicos, planetarios y científicos
    ("SYMBOL", re.compile("[☀-⛿✀-➿\U0001F700-\U0001F77F⊕⊗∞°$€£¥]+")),
    ("CODE", re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{2,}(?:-[A-Z0-9]+)+\b")),
]


@dataclass
class ProtectedText:
    text: str
    placeholders: dict[str, str] = field(default_factory=dict)


class Protector:
    def __init__(self, terms: dict[str, str] | None = None):
        """terms: término -> categoría (NAME, BRAND, ...). Los términos manuales se aplican primero,
        de mayor a menor longitud para no partir nombres compuestos."""
        self.terms = dict(terms or {})

    def add(self, term: str, category: str = "NAME") -> None:
        term = term.strip()
        if len(term) >= 2:
            self.terms.setdefault(term, category)

    def _term_regex(self) -> re.Pattern | None:
        if not self.terms:
            return None
        alts = sorted(self.terms, key=len, reverse=True)
        return re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in alts) + r")(?![\w])")

    def protect(self, text: str) -> ProtectedText:
        placeholders: dict[str, str] = {}
        counters: dict[str, int] = {}
        reverse: dict[str, str] = {}

        def make(category: str, value: str) -> str:
            if value in reverse:
                return reverse[value]
            counters[category] = counters.get(category, 0) + 1
            ph = f"__{category}_{counters[category]:03d}__"
            placeholders[ph] = value
            reverse[value] = ph
            return ph

        # no tocar etiquetas html inline
        parts = re.split(r"(<[^>]+>)", text)
        term_re = self._term_regex()
        out = []
        for part in parts:
            if part.startswith("<") and part.endswith(">"):
                out.append(part)
                continue
            if term_re is not None:
                part = term_re.sub(lambda m: make(self.terms[m.group(1)], m.group(1)), part)
            for cat, pat in PATTERNS:
                part = pat.sub(lambda m, c=cat: make(c, m.group(0)), part)
            out.append(part)
        return ProtectedText("".join(out), placeholders)


def restore(text: str, placeholders: dict[str, str]) -> tuple[str, list[str]]:
    """Restaura marcadores. Devuelve (texto, problemas). Cada marcador debe aparecer exactamente las
    mismas veces que en el original (normalmente una)."""
    problems: list[str] = []
    found: dict[str, int] = {}

    def repl(m: re.Match) -> str:
        ph = f"__{m.group(1)}_{m.group(2)}__"
        if ph not in placeholders:
            problems.append(f"marcador desconocido {ph}")
            return m.group(0)
        found[ph] = found.get(ph, 0) + 1
        return placeholders[ph]

    restored = PLACEHOLDER_RE.sub(repl, text)
    for ph in placeholders:
        if ph not in found:
            problems.append(f"falta el término protegido «{placeholders[ph]}»")
    return restored, problems


def count_placeholders(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in PLACEHOLDER_RE.finditer(text):
        ph = f"__{m.group(1)}_{m.group(2)}__"
        counts[ph] = counts.get(ph, 0) + 1
    return counts
