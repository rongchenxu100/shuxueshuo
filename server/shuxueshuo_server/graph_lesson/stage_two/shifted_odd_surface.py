"""Bind T6 original function identities, domains, given values and the requested object."""

import re

from ..shifted_odd_math import name, parse_sources
from .evaluation_surface import source_formulas, sum_source_matches
from .parity_extension_surface import _domain, _range, _same
from .symmetry_relation_surface import (
    _SENTENCE_END,
    _hypothesis,
    _prose,
    _quantifier_body,
)

_ANSWER_BLANK = re.compile(r"=\s*(?:(?:\\_|_)+|\\underline\{(?:\s|\\quad|\\qquad)+\})\s*$")
_TEXTBOOK_SECTION = re.compile(
    r"\A\s*类型\s*[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ一二三四五六七八九十0-9]+[：:]"
    r"[\u4e00-\u9fff＋+·、 \t]{1,60}\n(?=\s*【(?:例|变式)\s*\d+】)"
)


def source_spans(candidate, target_ref, ranges, desc):
    text = candidate["original_text"]
    if candidate["root"].get("uncertainties"):
        return None
    s = parse_sources(desc)
    definition = s["definition"]
    f = name(definition["ast"][1][1])
    raw = re.match(r"\s*\w+\((\w+)\)", definition["expression"])
    view = {"function": f, "variable": raw[1] if raw else "x"}
    labels = list(re.finditer(r"(?m)^\s*(?:\d+[.．、]|【(?:例|变式)\s*\d+】)", text))
    labels += list(_TEXTBOOK_SECTION.finditer(text))
    formulas = [p for p in source_formulas(text, ranges)
                if not any(m.start() <= p[0] < p[1] <= m.end() for m in labels)]
    rows, used, bound_parity = [], set(), set()
    prose = _prose(text)
    # An isolated textbook section title before an example is a label, not a
    # mathematical assertion. Preserve offsets and never hide formulas/clauses.
    prose = _TEXTBOOK_SECTION.sub(lambda m: " " * len(m[0]), prose)
    for start, end, _ in formulas:
        prose = prose[:start] + " " * (end - start) + prose[end:]

    def add(p, kind, refs):
        rows.append((p[0], p[1], kind, refs))
        used.add(p[:2])

    def same(p, expected):
        body = _ANSWER_BLANK.sub("", p[2]).rstrip().removesuffix("=").rstrip()
        return _same(body, expected, view)

    goal = desc["source"]
    hits = [
        p
        for p in formulas
        if (
            sum_source_matches(p[2], goal["terms"], lambda a, b: _same(a, b, view))
            if goal["kind"] == "finite_sum"
            else same(p, desc.get("requested_expression") or goal.get("expression", ""))
        )
        and (
            re.search(r"求\s*\$?\s*$", text[max(0, p[0] - 10) : p[0]])
            or re.match(r"\s*\$?\s*(?:的值|[_＿])", text[p[1] :])
            or _ANSWER_BLANK.search(p[2])
        )
    ]
    if len(hits) != 1:
        return None
    asked = hits[0]
    add(asked, "goal", [target_ref])
    for r in desc["given_entries"]:
        ast = r["ast"]
        ref = r["source_ref"]
        if ast[0] == "quantifier":
            prefix, equation = r["expression"].split(":", 1)
            bound = re.match(r"\s*∀\s*([A-Za-z]\w*)", prefix)
            hits = [
                p
                for p in formulas
                if p[1] < asked[0] and same(p, equation) and _hypothesis(text, p)
            ]
            if bound is None or len(hits) != 1:
                return None
            body = hits[0]
            scopes = [
                p
                for p in formulas
                if p[1] < body[0] and _quantifier_body(text, p) is not None
            ]
            scope = scopes[-1] if scopes else None
            from ..shifted_odd_identity import fixed_set

            if (
                scope is None
                or not _hypothesis(text, scope)
                or re.search(_SENTENCE_END, _prose(text)[scope[1] : body[0]])
                or _range(_quantifier_body(text, scope), bound[1])
                != fixed_set(s["relation_scope_ast"])
            ):
                return None
            add(scope, "condition", [ref])
            add(body, "condition", [ref])
        elif ast[0] == "function_parity":
            owner = name(ast[1][1])
            subjects = [
                p
                for p in formulas
                if p[1] < asked[0]
                and re.match(r"\s*" + re.escape(owner) + r"\(\w+\)(?:\s*=|\s*$)", p[2])
            ]
            claims = []
            for p in subjects:
                after = prose[p[1] : asked[0]]
                stop = re.search(r"[，,。；;！？!?：:\n]", after)
                clause = after[: stop.start()] if stop else after
                words = list(re.finditer(r"奇函数|偶函数", clause))
                if len(words) == 1 and words[0][0] == "奇函数":
                    word = words[0]
                    span = (p[1] + word.start(), p[1] + word.end())
                    # A later subject in the same clause owns its own property.
                    other_subject = any(
                        p[1] <= q[0] < span[0]
                        and any(
                            re.match(r"\s*" + re.escape(name(r)) + r"\(\w+\)", q[2])
                            for r in s["refs"]
                        )
                        for q in formulas
                    )
                    boundaries = list(
                        re.finditer(r"[，,。；;！？!?：:\n]", prose[: span[0]])
                    )
                    clause_start = boundaries[-1].end() if boundaries else 0
                    owners = [
                        q
                        for q in formulas
                        if clause_start <= q[0] < span[0]
                        and any(
                            re.match(r"\s*" + re.escape(name(r)) + r"\(\w+\)", q[2])
                            for r in s["refs"]
                        )
                    ]
                    if (
                        len(owners) == 1
                        and not other_subject
                        and not re.search(r"非|不", clause)
                    ):
                        claims.append((p, span))
                # Also accept the ordinary introduction “奇函数 g(x)”.
                prefix = re.search(r"奇函数\s*\$?\s*$", text[: p[0]])
                if prefix and not re.search(
                    r"非|不", text[max(0, prefix.start() - 6) : p[0]]
                ):
                    claims.append((p, (prefix.start(), prefix.start() + 3)))
            claims = [(p, span) for p, span in claims if _hypothesis(text, p)]
            if len(claims) != 1:
                return None
            subject, span = claims[0]
            bound_parity.add(span)
            add(subject, "condition", [ref])
            add((*span, text[span[0] : span[1]]), "condition", [ref])
        elif ast[0] == "=" and ast[1][:2] == ["call", "Dom"]:
            from ..shifted_odd_identity import fixed_set

            value = fixed_set(ast[2])
            hits = [
                p
                for p in formulas
                if p[1] < asked[0]
                and _hypothesis(text, p)
                and (
                    (
                        _domain(p[2]) == value
                        and re.search(
                            r"定义域|定义在|是\s*\$?\s*$",
                            text[max(0, p[0] - 12) : p[0]],
                        )
                    )
                    or _range(p[2], view["variable"]) == value
                )
            ]
            if len(hits) != 1:
                return None
            add(hits[0], "given_domain", [ref])
        elif ast[0] == "default_domain" and ast[2] == "real":
            label = name(ast[1][1])
            hits = [p for p in formulas if p[1] < asked[0] and _hypothesis(text, p) and (
                same(p, label + "∈ℝ") or same(p, label)
                and re.match(r"\s*\$?\s*(?:为|是)(?:实)?常数", text[p[1]:]))]
            if len(hits) != 1:
                return None
            add(hits[0], "condition", [ref])
        elif ast[0] == "=" and ast[2][0] == "extremum":
            label = name(ast[1][1])
            word = "最大值" if ast[2][1] == "max" else "最小值"
            hits = [
                p
                for p in formulas
                if same(p, label)
                and p[1] < asked[0]
                and re.search(word + r"(?:为|是)\s*\$?\s*$", text[: p[0]])
                and _hypothesis(text, p)
            ]
            if len(hits) != 1:
                return None
            add(hits[0], "condition", [ref])
        else:
            hits = [
                p
                for p in formulas
                if same(p, r["expression"]) and p[1] < asked[0] and _hypothesis(text, p)
            ]
            if len(hits) != 1:
                return None
            add(
                hits[0],
                "expression" if ast[0] == "function_definition" else "condition",
                [ref],
            )
    # Audit prose as well as formulas: a bare f(x) can introduce another property
    # even when the model omitted that property from the structured facts.
    printed_parity = {
        (start + m.start(), start + m.end())
        for start, end in ranges
        for m in re.finditer(r"奇函数|偶函数|非奇非偶", prose[start:end])
    }
    if printed_parity != bound_parity:
        return None
    # Function introductions and explicit declarations of a coefficient are not extra equations.
    for p in formulas:
        if p[:2] in used:
            continue
        if (re.fullmatch(r"[_＿]{2,}", p[2]) and p[0] >= asked[1]
                and re.fullmatch(r"\s*\$?\s*(?:的值)?(?:为|是)?\s*", text[asked[1]:p[0]])):
            add(p, "goal", [target_ref])
            continue
        if re.fullmatch(r"[A-Za-z]\w*", p[2].strip()) and re.match(
            r"\s*\$?\s*(?:为|是)(?:实)?常数", text[p[1] :]
        ):
            add(p, "condition", [definition["source_ref"]])
            continue
        if any(
            _same(p[2], name(ref) + "(" + view["variable"] + ")", view)
            for ref in s["refs"]
        ):
            add(p, "expression", [definition["source_ref"]])
            continue
        return None
    return sorted(rows)
