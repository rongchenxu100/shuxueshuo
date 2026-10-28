"""Locate D1 evidence in the current goal's visible, original problem text."""

import re

import sympy as sp

from ...problem_understanding.notation_parser import NotationError, parse
from .proposition_surface import negated_propositions, proposition_parts
from .surface_math import (
    PolynomialReader,
    equivalent,
    formula_spans,
    normalize_surface,
    split_relation,
)


def _domain_formula_body_matches(body, expected):
    """Compare original arithmetic trees, never simplified domain equivalents.

    This bounded display adapter accepts only the elementary TeX needed by
    this first domain route. Unknown markup omits the D1 quote conservatively.
    """
    if max(len(body), len(expected)) > 4096:
        return False

    def read(index=0, depth=0, grouped=False):
        if depth > 24:
            raise ValueError("display nesting limit")
        output = []
        while index < len(body):
            char = body[index]
            if char == "}":
                if not grouped:
                    raise ValueError("unmatched group")
                return "".join(output), index + 1
            if char == "{":
                inner, index = read(index + 1, depth + 1, True)
                # Canonical notation writes fixed integer exponents without
                # TeX braces; keep the following juxtaposed factor outside it.
                output.append(inner.strip() + " " if "".join(output).rstrip().endswith("^") and re.fullmatch(r"\s*\d+\s*", inner)
                              else "(" + inner + ")")
                continue
            if char != "\\":
                # Extracted original text may use canonical ASCII sqrt(...)
                # instead of TeX. Keep that function token intact before the
                # single-letter juxtaposition adapter below.
                if re.match(r"sqrt\s*\(", body[index:]) and (
                    index == 0 or not body[index - 1].isalnum()
                ):
                    output.append("sqrt")
                    index += 4
                    continue
                mapped = {"−": "-", "（": "(", "）": ")"}.get(char, char)
                # School TeX juxtaposes single-letter variables: kx or k x → k*x.
                # Ignore spacing only when checking that boundary; removing all
                # whitespace could merge distinct numeric/exponent tokens.
                # Command expansions append multi-letter names like sqrt( in one
                # piece, so this only fires for bare letters written one by one.
                if mapped.isalpha() and "".join(output).rstrip()[-1:].isalpha():
                    output.append("*")
                output.append(mapped)
                index += 1
                continue
            command = re.match(r"\\([A-Za-z]+|[,;! ])", body[index:])
            if not command:
                raise ValueError("unknown display command")
            word = command.group(1)
            index += command.end()
            if word in ("left", "right", ",", ";", "!", " ", "quad", "qquad"):
                continue
            if word in ("cdot", "times"):
                output.append("*")
                continue
            if word not in ("sqrt", "frac", "dfrac", "tfrac"):
                raise ValueError("unsupported display command")
            operands = []
            for _ in range(1 if word == "sqrt" else 2):
                while index < len(body) and body[index].isspace():
                    index += 1
                if index >= len(body) or body[index] != "{":
                    raise ValueError("display operand must be grouped")
                inner, index = read(index + 1, depth + 1, True)
                operands.append(inner)
            output.append("sqrt(" + operands[0] + ")" if word == "sqrt" else
                          "((" + operands[0] + ")/(" + operands[1] + "))")
        if grouped:
            raise ValueError("unfinished group")
        return "".join(output), index

    def original_structure(tree):
        # TeX a\frac{b}{c} and a*b/c differ only in product grouping.
        # Keep every divisor as an intact expression: never cancel factors
        # or turn a/(b/c) into a*c/b (which would lose the c != 0 condition).
        if tree[0] in ("*", "/"):
            numerators, divisors = [], []

            def collect(item):
                if item[0] == "*":
                    collect(item[1])
                    collect(item[2])
                elif item[0] == "/":
                    collect(item[1])
                    divisors.append(original_structure(item[2]))
                else:
                    numerators.append(original_structure(item))

            collect(tree)
            return ["original_product", numerators, divisors]
        return [original_structure(item) if isinstance(item, list) else item for item in tree]

    try:
        normalized, _ = read()
        return original_structure(parse(normalized)) == original_structure(parse(expected))
    except (NotationError, ValueError, RecursionError):
        return False


def _scope_ranges(candidate, target_ref):
    """Use child labels as boundaries, never search a sibling's body.

    Missing, repeated, or out-of-order labels are ambiguous. In that case no
    text is guessed to belong to the target. Ancestor introductions remain
    visible, which allows a shared function definition to precede each child.
    """
    text = candidate.get("original_text", "")
    parts = target_ref.split("/")
    if not isinstance(text, str) or parts[:2] != ["", "root"]:
        raise ValueError("invalid target")
    indices, i = [], 2
    while i + 1 < len(parts) and parts[i] == "children":
        indices.append(int(parts[i + 1]))
        i += 2
    if parts[i:i + 1] != ["goals"] or i + 2 != len(parts):
        raise ValueError("invalid target")
    node, begin, end, ranges = candidate["root"], 0, len(text), []
    for depth in range(len(indices) + 1):
        children = node.get("children", [])
        if not children:
            if depth != len(indices):
                raise ValueError("missing scope")
            ranges.append((begin, end))
            break
        matches = []
        for child in children:
            label = child.get("label", "")
            number = re.fullmatch(r"[（(]?\s*(\d+)\s*[）).、]?", label)
            if number:
                n = re.escape(number.group(1))
                pattern = rf"[（(]\s*{n}\s*[）)]"
            elif label:
                pattern = re.escape(label)
            else:
                raise ValueError("missing child label")
            found = list(re.finditer(pattern, text[begin:end]))
            # Bare function calls such as f(1) or f₁（1） are not headings.
            # A full-width heading may directly follow a formula, including
            # its final number. Half-width brackets remain conservative.
            # Repeated genuine labels must still remain ambiguous.
            headings = []
            for match in found:
                prefix = text[begin:begin + match.start()]
                if prefix.count("$") % 2:
                    continue
                prefix = prefix.rstrip(" \t\r")
                previous = prefix[-1:]
                if match.group().startswith("（") and match.group().endswith("）"):
                    follows_math = re.search(
                        r"[A-Za-z_\u0370-\u03ff][A-Za-z_\u0370-\u03ff\d⁰¹²³⁴⁵⁶⁷⁸⁹₀-₉'′]*\Z",
                        prefix,
                    ) is not None
                else:
                    follows_math = previous and (
                        (previous.isascii() and previous.isalnum())
                        or previous.isdigit()
                        or "\u0370" <= previous <= "\u03ff"
                        or previous in "_+-*/^=<>|∞ℝ∈≤≥∀∃'()[]{}（）［］｛｝"
                    )
                if follows_math:
                    continue
                headings.append(match)
            found = headings
            if len(found) != 1:
                raise ValueError("ambiguous child label")
            matches.append((begin + found[0].start(), begin + found[0].end()))
        if matches != sorted(matches) or len(set(matches)) != len(matches):
            raise ValueError("unordered child labels")
        ranges.append((begin, matches[0][0]))
        if depth == len(indices):
            break
        index = indices[depth]
        node = children[index]
        begin = matches[index][1]
        end = matches[index + 1][0] if index + 1 < len(matches) else end
    if not 0 <= int(parts[-1]) < len(node.get("goals", [])):
        raise ValueError("missing goal")
    return [(start, stop) for start, stop in ranges if start < stop]


def _known_features(features, target_ref):
    grouped = {}
    for item in features:
        if item.get("target_ref") == target_ref:
            key = item.get("feature_id")
            if key in grouped:
                raise ValueError("duplicate target feature")
            grouped[key] = item
    return {key: item for key, item in grouped.items() if item.get("status") == "known"}


def _register_definition(formula, reader):
    try:
        lhs, op, rhs = split_relation(formula)
    except ValueError:
        return False
    if op != "=":
        return False
    lhs = re.sub(r"\s+", "", lhs)
    function = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)\(([A-Za-z])\)", lhs)
    if function and function.group(1) not in reader.names:
        name, formal = function.groups()
        if name in reader.ambiguous_names:
            return True
        if name in reader.functions or name in reader.aliases:
            # Redefinitions are deliberately not resolved by last-write wins.
            reader.functions.pop(name, None)
            reader.aliases.pop(name, None)
            reader.ambiguous_names.add(name)
            return True
        body = PolynomialReader(
            reader.names | {formal},
            {key: value for key, value in reader.aliases.items() if key != formal},
            {key: value for key, value in reader.functions.items() if key != formal},
        ).parse(rhs)
        reader.functions[name] = (formal, body)
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", lhs) and lhs not in reader.names:
        if lhs in reader.ambiguous_names:
            return True
        if lhs in reader.aliases or lhs in reader.functions:
            reader.aliases.pop(lhs, None)
            reader.functions.pop(lhs, None)
            reader.ambiguous_names.add(lhs)
            return True
        reader.aliases[lhs] = reader.parse(rhs)
        return True
    return False


def _relation_matches(formula, reader, relation):
    lhs, op, rhs = split_relation(formula)
    left = reader.parse(lhs) - reader.parse(rhs)
    target = reader.parse(relation["lhs"]) - reader.parse(relation["rhs"])
    if op == relation["operator"]:
        return equivalent(left, target)
    reversed_op = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}
    return reversed_op.get(op) == relation["operator"] and equivalent(left, -target)


def _endpoint(value, reader):
    if value in ("-∞", "-oo"):
        return -sp.oo
    if value in ("∞", "+∞", "oo"):
        return sp.oo
    return reader.parse(value)


def _domain_matches(formula, variable, reader, domain):
    value = re.sub(r"\s+", "", formula).lstrip("∀∃")
    variable = re.escape(variable)
    membership = re.fullmatch(rf"{variable}∈(.+)", value)
    low, high, closed_left, closed_right = None, None, False, False
    if membership:
        value = membership.group(1)
        if value == "ℝ":
            low, high = -sp.oo, sp.oo
        else:
            interval = re.fullmatch(r"([\[(])([^,]+),([^,]+)([\])])", value)
            if interval:
                left, a, b, right = interval.groups()
                low, high = _endpoint(a, reader), _endpoint(b, reader)
                closed_left, closed_right = left == "[", right == "]"
            else:
                builder = re.fullmatch(rf"\{{{variable}\|(.+)\}}", value)
                if not builder:
                    return False
                value = builder.group(1)
    if low is None:
        chain = re.fullmatch(rf"(.+?)(<=|<|≤){variable}(<=|<|≤)(.+)", value)
        upper = re.fullmatch(rf"{variable}(<=|<|≤)(.+)", value)
        lower = re.fullmatch(rf"{variable}(>=|>|≥)(.+)", value)
        if chain:
            a, op_a, op_b, b = chain.groups()
            low, high = _endpoint(a, reader), _endpoint(b, reader)
            closed_left, closed_right = op_a != "<", op_b != "<"
        elif upper:
            low, high = -sp.oo, _endpoint(upper.group(2), reader)
            closed_right = upper.group(1) != "<"
        elif lower:
            low, high = _endpoint(lower.group(2), reader), sp.oo
            closed_left = lower.group(1) != ">"
        else:
            return False
    expected_low = _endpoint(domain["lower"], reader)
    expected_high = _endpoint(domain["upper"], reader)

    def same(a, b):
        return a == b if a in (sp.oo, -sp.oo) or b in (sp.oo, -sp.oo) else equivalent(a, b)

    return (same(low, expected_low) and same(high, expected_high)
            and closed_left == domain["left_closed"] and closed_right == domain["right_closed"])


def _negated_match(text, region, variable, values, reader):
    parts = proposition_parts(text, region)
    if not parts or not variable or not all(key in values for key in ("quantifier", "domain", "relation")):
        return None
    quantifier, real, domain_span, relation_span = parts
    if values["quantifier"] != {"∀": "∃", "∃": "∀"}[quantifier]:
        return None
    domain = text[slice(*domain_span)]
    if real:
        if domain.strip() != variable:
            return None
        domain = f"{variable}∈ℝ"
    if not _domain_matches(domain, variable, reader, values["domain"]):
        return None
    lhs, operator, rhs = split_relation(text[slice(*relation_span)])
    complement = {"<": ">=", "<=": ">", ">": "<=", ">=": "<"}.get(operator)
    if not complement or not _relation_matches(f"{lhs}{complement}{rhs}", reader, values["relation"]):
        return None
    return domain_span, relation_span, {
        "kind": "quantifier_negation", "source_quantifier": quantifier,
        "source_operator": operator, "target_quantifier": values["quantifier"],
        "target_operator": values["relation"]["operator"],
    }


def build_d1(candidate: dict, target_ref: str, features: list[dict], knowledge: dict):
    """Return conservative original-text fragments, independent of type choice."""
    diagnostics, fragments = [], []
    try:
        ranges = _scope_ranges(candidate, target_ref)
        known = _known_features(features, target_ref)
    except (KeyError, IndexError, TypeError, ValueError):
        return {"fragments": [], "diagnostics": [{"code": "d1.scope_or_features_ambiguous", "target_ref": target_ref}]}
    text = candidate["original_text"]
    values = {key: item["value"] for key, item in known.items()}
    names = set(values.get("bound_vars", [])) | set(values.get("free_vars", []))
    reader = PolynomialReader(names)
    bound = values.get("bound_vars", [])
    variable = bound[0] if len(bound) == 1 else None

    def add(surface, start, end, kind, matched, transform=None):
        matched = [feature for feature in matched if feature in known]
        if not matched:
            return
        rules = []
        for item in knowledge.get("items", []):
            if kind not in item.get("fragment_kinds", []):
                continue
            required = item.get("feature_ids", [])
            if not all(feature in known for feature in required):
                continue
            matched_any = item.get("matched_any")
            if matched_any is None and item.get("ref") == "quantifiers#roles":
                matched_any = ["bound_vars", "goal"]
            if matched_any and not set(matched_any).intersection(matched):
                continue
            if not set(required).intersection(matched) and kind != "relation":
                continue
            if kind == "relation" and "relation" not in matched:
                continue
            rules.append(item)
        original_start, original_end = surface.original_span(start, end)
        evidence = set(matched)
        for item in rules:
            evidence.update(item.get("feature_ids", []))
        fragments.append({
            "target_ref": target_ref,
            "start": original_start, "end": original_end,
            "text": text[original_start:original_end], "fragment_kind": kind,
            "matched_feature_ids": sorted(set(matched)),
            "knowledge_rule_ids": sorted({item["rule_id"] for item in rules}),
            "knowledge_refs": sorted({item["ref"] for item in rules}),
            "source_refs": sorted({ref for feature in evidence for ref in known[feature].get("source_refs", [])}),
            **({"reading_transform": transform} if transform else {}),
        })

    domain = values.get("function_domain", {})
    if (values.get("goal", {}).get("kind") == "compare_functions"
            and values.get("function_comparison", {}).get("structure_supported")):
        # The repeated f/g names belong to separate options. Read the common
        # comparison requirement, not eight definitions in a fake shared scope.
        for begin, end in ranges:
            surface = normalize_surface(text, begin, end)
            header = re.split(r"(?:^|\n)\s*[A-Z][.．、]", surface.text, maxsplit=1)[0]
            pattern = r"(?:是否(?:为|表示)?|不表示|不是|不为|并非|表示|为)?(?:不相同|不同|同一个|同一|相同)(?:的)?函数"
            for match in re.finditer(pattern, header):
                add(surface, match.start(), match.end(), "goal", ["goal", "function_comparison"])
        for index, item in enumerate(fragments, 1):
            item["id"] = f"{target_ref}:d1:{index}"
        if not fragments:
            diagnostics.append({"code": "d1.function_comparison_requirement_not_located", "target_ref": target_ref})
        return {"fragments": fragments, "diagnostics": diagnostics}
    if values.get("goal", {}).get("kind") in ("find_domain", "match_domain") and domain.get("structure_supported"):
        # Require one matching function/argument identity, then bind its exact
        # arithmetic tree; cancellation or an unrelated RHS cannot pass.
        name, argument = re.escape(domain["function_name"]), re.escape(domain["variable"])
        # Extraction may name the explicitly given y=... correspondence f(x).
        # The full original RHS must still match, and multiple definitions fail.
        head = re.compile(rf"^\s*(?:{name}\s*(?:\\left\s*)?\(\s*{argument}\s*(?:\\right\s*)?\)|y)\s*=")
        definitions = []
        for begin, end in ranges:
            for formula in re.finditer(r"\$([^$\n]+)\$", text[begin:end]):
                matched = head.match(formula.group(1))
                if matched and formula.group(1)[matched.end():].strip():
                    definitions.append((begin + formula.start(1), begin + formula.end(1),
                                        formula.group(1)[matched.end():]))
        if len(definitions) == 1 and _domain_formula_body_matches(definitions[0][2], domain["expression"]):
            first, last, _ = definitions[0]
            surface = normalize_surface(text, first, last)
            if surface.text:
                add(surface, 0, len(surface.text), "expression", ["function_domain"])
        else:
            diagnostics.append({"code": "d1.function_definition_not_uniquely_located", "target_ref": target_ref})

    for begin, end in ranges:
        surface = normalize_surface(text, begin, end)
        normalized = surface.text
        negations = negated_propositions(normalized)

        def inside_negation(start, stop, negations=negations):
            return any(start < region.end and region.start < stop for region in negations)

        # Definitions and negated propositions share the same source order;
        # a later definition must not retroactively resolve an earlier formula.
        entries = [(start, stop, None) for start, stop in formula_spans(normalized)]
        entries += [(region.start, region.end, region) for region in negations]
        for start, stop, region in sorted(entries, key=lambda entry: entry[0]):
            if region is not None:
                try:
                    match = _negated_match(normalized, region, variable, values, reader)
                except (KeyError, TypeError, ValueError, RecursionError, OverflowError):
                    match = None
                if match:
                    domain_span, relation_span, transform = match
                    add(surface, region.start, region.end, "quantifier", ["quantifier", "bound_vars"], transform)
                    add(surface, *domain_span, "domain", ["domain", "bound_vars"])
                    add(surface, *relation_span, "relation", ["relation"], transform)
                else:
                    diagnostics.append({"code": "d1.negation_not_mapped", "target_ref": target_ref,
                                        "start": surface.offsets[region.start][0]})
                continue
            formula = normalized[start:stop]
            if "¤" in formula:
                diagnostics.append({"code": "d1.unsupported_surface_command", "start": surface.offsets[start][0]})
                continue
            try:
                if inside_negation(start, stop):
                    continue
                if _register_definition(formula, reader):
                    continue
                if variable and "domain" in values and _domain_matches(formula, variable, reader, values["domain"]):
                    offset = 1 if formula.startswith(("∀", "∃")) else 0
                    add(surface, start + offset, stop, "domain", ["domain", "bound_vars"])
                if (not formula.startswith(("∀", "∃")) and "relation" in values
                        and _relation_matches(formula, reader, values["relation"])):
                    add(surface, start, stop, "relation", ["relation"])
            except (KeyError, TypeError, ValueError, RecursionError, OverflowError):
                # Domain chains, standalone names and unsupported syntax are
                # normal here; they never become guessed relationship options.
                continue

        quantifier = values.get("quantifier")
        words = {"∀": ("任意", "所有", "恒成立", "∀"), "∃": ("存在", "有解", "∃")}.get(quantifier, ())
        for word in words:
            for match in re.finditer(re.escape(word), normalized):
                if inside_negation(match.start(), match.end()):
                    continue
                stop = match.end()
                matched = ["quantifier"]
                if word in ("∀", "∃") and variable:
                    following = re.match(rf"\s*{re.escape(variable)}(?![A-Za-z0-9_])", normalized[stop:])
                    if following:
                        stop += following.end()
                        matched.append("bound_vars")
                add(surface, match.start(), stop, "quantifier", matched)

        # Real-domain prose must explicitly name the bound variable in a
        # quantifier context; the real parameter in the goal is a different fact.
        if variable and values.get("domain", {}).get("expression") == "ℝ":
            symbol = re.escape(variable)
            pattern = rf"(?:任意|所有|存在)\s*(实数\s*(?:\$\s*{symbol}\s*\$|{symbol}(?![A-Za-z0-9_])))"
            for match in re.finditer(pattern, normalized):
                add(surface, match.start(1), match.end(1), "domain", ["domain", "bound_vars"])
        goal = values.get("goal", {})
        if goal.get("kind") == "find_domain" and values.get("function_domain", {}).get("structure_supported"):
            for match in re.finditer(r"定义域", normalized):
                add(surface, match.start(), match.end(), "goal", ["goal", "function_domain"])
        if goal.get("kind") == "match_domain" and values.get("function_domain", {}).get("structure_supported"):
            for match in re.finditer(r"定义域", normalized):
                add(surface, match.start(), match.end(), "goal", ["goal", "function_domain"])
            symbol = goal.get("symbol")
            if isinstance(symbol, str):
                target = rf"(?:\$\s*{re.escape(symbol)}\s*\$|{re.escape(symbol)}(?![A-Za-z0-9_]))"
                for match in re.finditer(
                    rf"(?:求\s*)?(?:(?:实数|参数)\s*)?{target}\s*(?:的\s*)?取值范围",
                    normalized,
                ):
                    add(surface, match.start(), match.end(), "goal", ["goal", "function_domain"])
        if goal.get("kind") in ("find_range", "find_minimum", "find_maximum") and isinstance(goal.get("symbol"), str):
            symbol = re.escape(goal["symbol"])
            if goal["kind"] == "find_range":
                target = rf"(?:\$\s*{symbol}\s*\$|{symbol}(?![A-Za-z0-9_]))"
                pattern = rf"(?:求\s*)?(?:(?:实数|参数)\s*)?{target}\s*(?:的\s*)?取值范围"
            else:
                noun = "最小值" if goal["kind"] == "find_minimum" else "最大值"
                target = rf"(?:\$\s*{symbol}\s*\$|{symbol}(?![A-Za-z0-9_]))"
                pattern = rf"(?:求\s*)?(?:(?:实数|参数)\s*)?{target}\s*(?:的\s*)?{noun}"
            for match in re.finditer(pattern, normalized):
                if goal["kind"] == "find_range" and not match.group().startswith("求"):
                    # A stated parameter domain is a condition, not a request.
                    # Fill-in questions may omit 求, but still have a question
                    # boundary (则) or an explicit answer blank.
                    prefix, suffix = normalized[:match.start()], normalized[match.end():]
                    if not (re.search(r"(?:则|那么)\s*$", prefix)
                            or re.match(r"\s*(?:为|是)\s*(?:[_＿]+|[（(]\s*[）)])", suffix)):
                        continue
                # With no required “求”, a suffix of ba or a+a can look like
                # the requested symbol. Do not turn that suffix into a goal.
                previous = normalized[:match.start()].rstrip()[-1:]
                if (
                    not match.group().startswith(("求", "实数", "参数"))
                    and previous
                    and (
                        (previous.isascii() and previous.isalnum())
                        or previous.isdigit()
                        or "\u0370" <= previous <= "\u03ff"
                        or previous in "_$+-*/^=<>|∞ℝ∈≤≥∀∃'()[]{}¤"
                    )
                ):
                    continue
                add(surface, match.start(), match.end(), "goal", ["goal"])

    fragments.sort(key=lambda item: (item["start"], item["end"], item["fragment_kind"]))
    unique = {}
    for item in fragments:
        unique[(item["start"], item["end"], item["fragment_kind"])] = item
    fragments = list(unique.values())
    for index, item in enumerate(fragments, 1):
        item["id"] = f"{target_ref}:d1:{index}"
    if "relation" in known and not any(item["fragment_kind"] == "relation" for item in fragments):
        diagnostics.append({"code": "d1.relation_not_located", "target_ref": target_ref})
    return {"fragments": fragments, "diagnostics": diagnostics}
