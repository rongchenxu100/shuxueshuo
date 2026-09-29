"""Bounded teaching rows lowered to relations with explicit source segments.

Markers label presentation, never grant premise authority. Chains are conjunctions
of adjacent relations; their endpoint is checked separately by the proof kernel.
The single-relation and legacy step-parser contracts remain unchanged.
"""

from dataclasses import dataclass, replace
from hashlib import sha256

from .expression_parser import RELATIONS, MathParseError, ParsedMath, _Parser, parse_math_expression, parse_math_relation


CONNECTORS = {**dict.fromkeys(("因为", "由于", "由"), "∵"),
              **dict.fromkeys(("所以", "因此", "故", "从而", "可得", "得到", "得", "即"), "∴")}
CLAUSE_WORDS = (*CONNECTORS, "满足", "且")


@dataclass(frozen=True)
class DerivationRelation:
    parsed: ParsedMath
    origin: dict


def _append_relation(
    result, row_start, parser, marker, left, operator, right, *, endpoint=False, language_tokens=(), expression_references=()
):
    if len(result) >= 256:
        parser.fail("proof_limit", "整段展开超过 256 个关系记录")
    spans = [left.span, operator.span, right.span]
    # Whitespace prevents accidental token concatenation. The segment table
    # maps the lowered source back to actual Unicode offsets in the raw row.
    references = [ref for ref in expression_references if tuple(ref["span"]) in spans]
    expansions = {tuple(ref["span"]): f"({ref['math']})" for ref in references}
    text = " ".join(expansions.get((a, b), parser.source[a:b]) for a, b in spans)
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
                **({"language_tokens": list(language_tokens)} if language_tokens else {}),
                **({"expression_references": references} if references else {}),
            },
        )
    )


def parse_derivation(steps, symbols, *, closure_target=None, original_expression=None):
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= 12:
        raise ValueError("steps 需要 1–12 行数学推导")
    result = []
    # Only the owning Method supplies this binding. Ordinary parser callers
    # cannot infer an expression from the prose or register a symbol named 原式.
    original = None
    for i, row in enumerate(steps):
        if not isinstance(row, dict) or set(row) != {"math"}:
            raise ValueError("每行只能包含 math")
        source = row["math"]
        if (original is None and original_expression is not None
                and isinstance(source, str) and "原式" in source):
            original = parse_math_expression(original_expression, symbols)
        path = f"/parameters/steps/{i}/math"
        # Teaching-clause separators are lexical aliases only. Replacement is
        # exactly one code point, so every token keeps its original offset;
        # restore the raw source before extracting any mathematical segments.
        lexical_source = (
            source.translate(str.maketrans({";": ",", "；": ","}))
            if isinstance(source, str)
            else source
        )
        try:
            words = (*CLAUSE_WORDS, "最小值为", "最大值为", "原条件", "取等") if closure_target else CLAUSE_WORDS
            parser = _Parser(lexical_source, symbols, step=i, source_path=path,
                             clause_words=(*words, "原式") if original is not None else words)
        except MathParseError as exc:
            exc.source = source
            raise
        parser.source = source
        marker = None
        row_start = len(result)
        conjunction = None
        expression_references = []

        def operand():
            if original is None or parser.peek().text != "原式":
                return parser.expr()
            token = parser.take()
            expression_references.append({"kind": "method_input_expression", "text": "原式",
                                          "span": list(token.span), "math": original.source})
            # A reference is a complete operand of a relation, not arbitrary
            # Chinese text removal. Lowering below re-parses the expanded math
            # with its own certificate spans and the original reference map.
            return replace(original.ast, span=token.span)

        while True:
            explicit_marker = None
            clause_role = None
            language_tokens = []
            if conjunction is not None:
                if parser.peek().text in {"∵", "∴", *CLAUSE_WORDS}:
                    parser.fail("invalid_conjunction", "且后须为同一作用的完整数学关系")
                language_tokens.append({"text": conjunction.text,
                                        "span": list(conjunction.span), "role": marker})
                conjunction = None
            if parser.peek().text in {"∵", "∴"}:
                marker = parser.take().text
                explicit_marker = marker
                clause_role = marker
            if parser.peek().text in CONNECTORS:
                word = parser.take()
                role = CONNECTORS[word.text]
                if explicit_marker is not None and explicit_marker != role:
                    parser.fail("conflicting_derivation_role", "中文衔接语与 ∵/∴ 的作用冲突", word.span)
                marker = role
                clause_role = role
                language_tokens.append({"text": word.text, "span": list(word.span), "role": role})
            satisfies = False
            if parser.peek().text == "满足":
                word = parser.take()
                if clause_role == "∵":
                    parser.fail("conflicting_derivation_role", "“满足”在此表示待验证结论，不能转换为新假设", word.span)
                marker = "∴"
                satisfies = True
                language_tokens.append({"text": word.text, "span": list(word.span), "role": "∴"})
            if closure_target and parser.peek().text in {"最小值为", "最大值为", "原条件"}:
                word = parser.take()
                if marker == "∵":
                    parser.fail("conflicting_derivation_role", "闭合结论不能作为新假设", word.span)
                marker = "∴"
                references = []
                if word.text == "原条件":
                    if not satisfies:
                        parser.fail("invalid_derivation_statement", "请写满足原条件或明确数学关系", word.span)
                    references = [(c["math"], {"kind": "original_condition", **c})
                                  for c in closure_target["source_conditions"]]
                else:
                    expected = "find_minimum" if word.text == "最小值为" else "find_maximum"
                    if closure_target["goal_kind"] != expected:
                        parser.fail("target_bound_mismatch", "最值方向与当前目标不一致", word.span)
                    value = parser.expr()
                    parser.check(value)
                    text = parser.source[slice(*value.span)]
                    references = [(f"({closure_target['target_math']})=({text})",
                                   {"kind": "extremum_value", "value_span": list(value.span),
                                    "target_math": closure_target["target_math"],
                                    "goal_kind": expected})]
                for text, reference in references:
                    if len(result) >= 256:
                        parser.fail("proof_limit", "整段展开超过 256 个关系记录")
                    derived_path = f"/derived_relations/{len(result)}/math"
                    parsed = replace(parse_math_relation(text, symbols), source_path=derived_path, step=i)
                    result.append(DerivationRelation(parsed, {
                        "source": source, "source_sha256": sha256(source.encode()).hexdigest(),
                        "source_path": path, "derived_source_path": derived_path,
                        "step": i, "marker": marker, "chain_endpoint": False,
                        "statement_reference": reference,
                        "language_tokens": [*language_tokens,
                                            {"text": word.text, "span": list(word.span), "role": marker}],
                    }))
            else:
                left = operand()
                first = left
                operators = []
                if parser.peek().text not in RELATIONS:
                    parser.fail(
                        "invalid_condition",
                        "需要等式或比较关系；使用显式 *、sqrt(...)、>=、<=",
                    )
                while parser.peek().text in RELATIONS:
                    operator = parser.take()
                    right = operand()
                    parser.check(left)
                    parser.check(right)
                    _append_relation(
                        result, row_start, parser, marker, left, operator, right, language_tokens=language_tokens,
                        expression_references=expression_references,
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
                            language_tokens=language_tokens,
                            expression_references=expression_references,
                        )
                if closure_target and parser.peek().text == "取等":
                    word = parser.take()
                    if len(operators) != 1 or operators[0].text not in {"<=", ">="}:
                        parser.fail("invalid_equality_reference", "取等须紧接一个非严格不等式", word.span)
                    inequality = result[-1].parsed.source
                    reference_tokens = [{"text": word.text, "span": list(word.span), "role": "equality_reference"}]
                    if parser.peek().text == ",":
                        separator = parser.take()
                        conclusion = parser.take("∴")
                        reference_tokens.extend([
                            {"text": parser.source[slice(*separator.span)], "span": list(separator.span), "role": "equality_reference"},
                            {"text": conclusion.text, "span": list(conclusion.span), "role": "∴"},
                        ])
                    else:
                        parser.take(":")
                    eq_left = parser.expr()
                    if parser.peek().text != "=":
                        parser.fail("invalid_equality_reference", "取等后须为完整等式")
                    eq_op = parser.take()
                    eq_right = parser.expr()
                    parser.check(eq_left)
                    parser.check(eq_right)
                    _append_relation(result, row_start, parser, "∴", eq_left, eq_op, eq_right,
                                     language_tokens=reference_tokens)
                    result[-1].origin["equality_reference"] = {"inequality": inequality}
                    marker = "∴"
            # A marker starts a new clause after a complete relation, even
            # without punctuation. Consume it at the top of the next loop;
            # no inserted characters or guessed expression boundaries.
            if parser.peek().text in {"∵", "∴", *CONNECTORS}:
                continue
            if parser.peek().text == "且":
                conjunction = parser.take()
                continue
            if parser.peek().text != ",":
                break
            parser.take(",")
        if parser.peek().text != "EOF":
            parser.fail(
                "invalid_syntax",
                "只支持关系、关系链、逗号/分号和 ∵/∴；使用显式 *、sqrt(...)",
            )
    from .proof_algebra import from_node
    from .proof_kernel import fact_key

    independent = {fact_key(from_node(r.parsed.ast)) for r in result if not r.origin["chain_endpoint"]}
    if len(independent) > 32:
        parser.fail("proof_limit", "整段最多 32 个独立数学关系")
    return tuple(result)
