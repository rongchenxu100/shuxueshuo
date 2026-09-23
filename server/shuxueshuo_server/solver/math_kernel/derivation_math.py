"""Bounded teaching rows lowered to relations with explicit source segments.

Markers label presentation, never grant premise authority. Chains are conjunctions
of adjacent relations; their endpoint is checked separately by the proof kernel.
The single-relation and legacy step-parser contracts remain unchanged.
"""

from dataclasses import dataclass, replace
from hashlib import sha256

from .expression_parser import RELATIONS, ParsedMath, _Parser, parse_math_relation


@dataclass(frozen=True)
class DerivationRelation:
    parsed: ParsedMath
    origin: dict


def _append_relation(
    result, row_start, parser, marker, left, operator, right, *, endpoint=False
):
    if len(result) - row_start >= 8 or len(result) >= 32:
        parser.fail("proof_limit", "每行最多 8 个关系，整段最多 32 个关系")
    spans = [left.span, operator.span, right.span]
    # Whitespace prevents accidental token concatenation. The segment table
    # maps the lowered source back to actual Unicode offsets in the raw row.
    text = " ".join(parser.source[a:b] for a, b in spans)
    derived_path = f"/derived_relations/{len(result)}/math"
    parsed = replace(
        parse_math_relation(text, parser.symbols),
        # Certificate spans address this lowered document, not the raw row.
        # The origin map below is the explicit bridge to original offsets.
        source_path=derived_path,
        step=parser.step,
    )
    result.append(
        DerivationRelation(
            parsed,
            {
                "source": parser.source,
                "source_sha256": sha256(parser.source.encode()).hexdigest(),
                "source_path": parser.source_path,
                "derived_source_path": derived_path,
                "step": parser.step,
                "marker": marker,
                "segments": [list(span) for span in spans],
                "chain_endpoint": endpoint,
            },
        )
    )


def parse_derivation(steps, symbols):
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= 12:
        raise ValueError("steps 需要 1–12 行数学推导")
    result = []
    for i, row in enumerate(steps):
        if not isinstance(row, dict) or set(row) != {"math"}:
            raise ValueError("每行只能包含 math")
        source = row["math"]
        path = f"/parameters/steps/{i}/math"
        # Teaching-clause separators are lexical aliases only. Replacement is
        # exactly one code point, so every token keeps its original offset;
        # restore the raw source before extracting any mathematical segments.
        lexical_source = (
            source.translate(str.maketrans({";": ",", "；": ","}))
            if isinstance(source, str)
            else source
        )
        parser = _Parser(lexical_source, symbols, step=i, source_path=path)
        parser.source = source
        marker = None
        row_start = len(result)

        while True:
            if parser.peek().text in {"∵", "∴"}:
                marker = parser.take().text
            left = parser.expr()
            first = left
            operators = []
            if parser.peek().text not in RELATIONS:
                parser.fail(
                    "invalid_condition",
                    "需要等式或比较关系；使用显式 *、sqrt(...)、>=、<=",
                )
            while parser.peek().text in RELATIONS:
                operator = parser.take()
                right = parser.expr()
                parser.check(left)
                parser.check(right)
                _append_relation(
                    result, row_start, parser, marker, left, operator, right
                )
                operators.append(operator)
                left = right
            # Only unambiguous monotone chains receive an endpoint assertion.
            non_eq = [op for op in operators if op.text != "="]
            if len(operators) > 1 and len({op.text for op in non_eq}) <= 1:
                selected = non_eq[0] if non_eq else operators[0]
                if selected.text != "!=":
                    _append_relation(
                        result,
                        row_start,
                        parser,
                        marker,
                        first,
                        selected,
                        right,
                        endpoint=True,
                    )
            # A marker starts a new clause after a complete relation, even
            # without punctuation. Consume it at the top of the next loop;
            # no inserted characters or guessed expression boundaries.
            if parser.peek().text in {"∵", "∴"}:
                continue
            if parser.peek().text != ",":
                break
            parser.take(",")
        if parser.peek().text != "EOF":
            parser.fail(
                "invalid_syntax",
                "只支持关系、关系链、逗号/分号和 ∵/∴；使用显式 *、sqrt(...)",
            )
    return tuple(result)
