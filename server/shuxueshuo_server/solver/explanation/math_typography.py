"""Presentation-only fraction typesetting; never changes solver input or facts."""

import re
from copy import deepcopy

import sympy as sp

from ..math_kernel.expression_parser import MathParseError, parse_math_expression
from ..math_kernel.expression_rewrite import _legacy_tree, tree_latex

_MATH_RUN = re.compile(r"[A-Za-z0-9α-ωΑ-Ω+＋\-−－*/^=＝<>＜＞≤≥≠!√²³⁴⁵⁶⁷⁸⁹⁰·×()（） \t]+")
_REL = re.compile(r"(>=|<=|!=|[=<>≤≥≠])")
_ALIASES = str.maketrans("＋−－＝＜＞（）×·", "+--=<>()**")
_TEX_RELATION = re.compile(r"\\(geq|leq|neq|ge|le|ne)(?![A-Za-z])")
_TEX_RELATION_SYMBOLS = {
    "geq": "≥",
    "ge": "≥",
    "leq": "≤",
    "le": "≤",
    "neq": "≠",
    "ne": "≠",
}


def _latex(source):
    # Only displayed juxtaposition of parenthesized factors is accepted here.
    # Runtime parsing stays explicit; identifiers such as xy remain whole.
    text = source.translate(_ALIASES).strip()
    text = re.sub(r"\)\s*\(", ")*(", text)
    symbols = {
        n: sp.Symbol(n)
        for n in re.findall(r"[A-Za-zα-ωΑ-Ω][A-Za-z0-9_α-ωΑ-Ω]*", text)
        if n != "sqrt"
    }
    parts = _REL.split(text)
    result = []
    for i, part in enumerate(parts):
        if i % 2:
            result.append({">=": "≥", "<=": "≤", "!=": "≠"}.get(part, part))
        else:
            parsed = parse_math_expression(part, symbols)
            result.append(tree_latex(_legacy_tree(parsed.ast)))
    return "".join(result)


def fraction_prose(text):
    """Typeset slash fractions in prose or math delimiters, preserve existing TeX."""

    def run(match):
        raw = match.group()
        if "/" not in raw:
            return raw
        try:
            rendered = _latex(raw)
        except (MathParseError, ValueError, KeyError):
            # A comparison can straddle a pre-typeset TeX fragment (for
            # example plain U+V >= 2√[ followed by a TeX radicand). Format
            # complete sides independently, preserving the remaining text.
            parts = _REL.split(raw.translate(_ALIASES))
            if len(parts) > 1:
                return "".join(
                    part if i % 2 else _MATH_RUN.sub(run, part)
                    for i, part in enumerate(parts)
                )
            return raw
        return (
            raw[: len(raw) - len(raw.lstrip())]
            + r"\("
            + rendered
            + r"\)"
            + raw[len(raw.rstrip()) :]
        )

    text = re.sub(r"\\{2,}(?=[A-Za-z()])", lambda _: chr(92), str(text))
    pieces = re.split(r"(\\\(.*?\\\))", text)
    for i, piece in enumerate(pieces):
        if piece.startswith(r"\("):
            inner = piece[2:-2]
            # A TeX comparison alone does not mean slash fractions are typeset.
            # Normalize only these known aliases; preserve other TeX untouched.
            plain = _TEX_RELATION.sub(lambda m: _TEX_RELATION_SYMBOLS[m[1]], inner)
            if "/" in plain and "\\" not in plain:
                try:
                    pieces[i] = r"\(" + _latex(plain) + r"\)"
                except (MathParseError, ValueError, KeyError):
                    pieces[i] = (
                        r"\("
                        + _MATH_RUN.sub(run, plain)
                        .replace(r"\(", "")
                        .replace(r"\)", "")
                        + r"\)"
                    )
        elif "\\" not in piece and "://" not in piece:
            pieces[i] = _MATH_RUN.sub(run, piece)
    return "".join(pieces)


_TEXT_FIELDS = {
    "title",
    "navTitle",
    "goal",
    "text",
    "expression",
    "value",
    "condition",
    "mapped",
    "conclusion",
    "equality",
    "solved",
    "verification",
    "fixedCondition",
    "first",
    "second",
    "result",
    "original",
    "note",
    "label",
    "reading",
    "route",
    "caption",
    "answerText",
}
_TEXT_ARRAYS = {
    "derive",
    "box",
    "relations",
    "equalityRelations",
    "mappedParts",
    "items",
}


def typeset_lesson_data(data):
    """Format display fields, leaving IDs, roles, source references and assets intact."""
    result = deepcopy(data)

    def walk(value, display=False):
        if isinstance(value, str):
            return fraction_prose(value) if display else value
        if isinstance(value, list):
            return [walk(v, display) for v in value]
        if isinstance(value, dict):
            return {
                k: walk(v, k in _TEXT_FIELDS or k in _TEXT_ARRAYS)
                for k, v in value.items()
            }
        return value

    return walk(result)
