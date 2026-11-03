"""Questions about separation and certified ranges, using only this card's seed."""

import sympy as sp


def register(api):
    """Explicit compiler dependency; no math-driver or persistent-state access."""
    def division_facts(values, context):
        divisor, variable, domain = values["divisor"], context["x"], context["domain"]
        bounds = api.range_at(divisor, variable, domain)
        positive = api.cmp(bounds["inf"], 0) > 0 or (
            api.cmp(bounds["inf"], 0) == 0 and not bounds["inf_attained"])
        negative = api.cmp(bounds["sup"], 0) < 0 or (
            api.cmp(bounds["sup"], 0) == 0 and not bounds["sup_attained"])
        if not (positive or negative):
            raise api.NotInteractive("divisor_sign_unknown")
        return {"reverse": negative, "display": {"divisor": divisor, "domain": domain, "x": variable,
                                                 "moved": values.get("moved"), "parameter": context.get("parameter")}}

    def division_answer(facts):
        reverse = facts["reverse"]
        return [{"label": "不等号方向", "answer": api.Candidate(
            f"direction:{reverse}", "反向" if reverse else "保持不变", reverse)}]

    sign_labels = {"positive": "恒正", "negative": "恒负", "unknown": "可能为零或变号，不能直接除"}

    def sign_answer(facts):
        sign = "negative" if facts["reverse"] else "positive"
        return [{"label": f"除数 {api.math(facts['display']['divisor'])} 的符号",
                 "answer": api.Candidate(f"sign:{sign}", sign_labels[sign], sign)}]

    def other_signs(facts, item):
        return [api.Candidate(f"sign:{sign}", label, sign) for sign, label in sign_labels.items()
                if sign != item["answer"].value]

    def direction_error(facts, item):
        reverse = not item["answer"].value
        return [api.Candidate(f"direction:{reverse}", "反向" if reverse else "保持不变", reverse)]

    def move_facts(values, context):
        return {"reverse": False, "display": {"before": values["before"][0]}}

    def range_facts(values, context):
        bound = values.get("range", {})
        answer = bound.get("set")
        if answer is None:
            answer = next((value for value in reversed(values["after"]) if isinstance(value, sp.Set)), None)
        if not isinstance(answer, sp.Set) or answer.free_symbols:
            raise api.NotInteractive("numeric_range_missing")
        function = values.get("function")
        if function is None and values.get("before") and isinstance(values["before"][0], sp.Expr):
            function = values["before"][0]
        variable = values.get("x", context["x"])
        name = values.get('range_label') or api.named_function(values, function, variable)
        return {"answer": answer, "function": function, "parameter": context.get("parameter"),
                "x": variable, "domain": values.get("domain", context["domain"]),
                "case_domain": values.get("case", {}).get("domain", sp.S.Reals),
                "display": {"function": name or (function if function is not None else "该函数"),
                            "subject": f"${name}$ " if name else "本步的函数",
                            "range_title": values.get('range_title', '确定函数值的范围'),
                            "range_identity": values.get('range_identity', ''), "x": variable,
                            "domain": values.get("domain", context["domain"])}}

    def answer_set(facts):
        return [{"answer": api.set_candidate("range", facts["answer"])}]

    def range_errors(facts, item):
        answer = item["answer"].value
        values = [*api.flip_endpoint(facts, item)]
        values.append(api.set_candidate("range", sp.Complement(sp.S.Reals, answer)))
        pieces = list(answer.args) if isinstance(answer, sp.Union) else [answer]
        for piece in pieces:
            if isinstance(piece, sp.Interval):
                for end in (piece.start, piece.end):
                    if api.finite(end):
                        values.append(api.set_candidate("range", sp.FiniteSet(end)))
                if api.finite(piece.start) and api.finite(piece.end):
                    values.append(api.set_candidate("range", sp.Interval(piece.start, sp.oo,
                                                                              left_open=piece.left_open)))
            elif isinstance(piece, sp.FiniteSet):
                values.extend(api.set_candidate("range", sp.Interval(v, sp.oo)) for v in piece)
        return values

    def validate_range(facts, values, context, item, candidates):
        # These are FUNCTION VALUES, not parameter values: never intersect them
        # with the known parameter set (e.g. a >= 0 does not mean f(x) >= 0).
        return api.set_check(item["answer"], candidates, sp.S.Reals)

    def range_graph(facts, values, context):
        if facts["function"] is None:
            raise api.GraphUnavailable("function_missing")
        function, variable, domain = facts['function'], facts['x'], facts['domain']
        if function.free_symbols <= {variable} and function.is_polynomial(variable) and sp.degree(function, variable) == 2:
            name = values.get('range_label') or api.named_function(values, function, variable)
            formula = f'{name}={api.latex(function)}' if name else f'y={api.latex(function)}'
            return api.drawing.interval_function_graph(
                function, variable, domain,
                title=f'y={api.drawing.plain(function)} 在 {api.drawing.plain(domain)} 上的图像',
                caption=f'${formula}$，${api.latex(variable)}\\in{api.latex(domain)}$。'
                        '深色曲线表示本题范围，浅色仅作参考；实心点可取，空心端点不取')
        return api.function_stem({**facts, "known": sp.Intersection(facts["known"], facts["case_domain"])},
                                   values, context)

    def range_options(facts, values, context, candidates):
        return api.drawing.number_lines([candidate.value for candidate, _ in candidates], sp.Symbol("y"),
                                         title="函数值的范围"), None

    def endpoint_facts(values, context):
        candidates = values["range"]["candidates"]
        points = tuple(dict.fromkeys(row["point"] for row in candidates))
        if not points:
            raise api.NotInteractive("endpoint_candidates_missing")
        return {"points": points, "candidates": candidates, "bound": values["range"]["bound"],
                "parameter": context.get("parameter"), "case_domain": values.get("case", {}).get("domain", sp.S.Reals),
                "x": values["x"], "domain": values["domain"],
                "display": {"function": api.named_function(values, values["function"], values["x"])
                            or values["function"], "domain": values["domain"],
                            "bound_name": api.BOUND_NAMES[values["range"]["bound"]]}}

    def endpoint_label(facts, points):
        return "、".join(f"${api.latex(facts['x'])}={api.latex(point)}$" for point in points)

    def endpoint_answer(facts):
        return [{"label": "比较候选位置（开放端点取极限）", "answer": api.Candidate(
            "ends:" + str(facts["points"]), endpoint_label(facts, facts["points"]), facts["points"])}]

    def endpoint_errors(facts, item):
        points = facts["points"]
        candidates = [(point,) for point in points] if len(points) > 1 else []
        return [api.Candidate("ends:" + str(other), endpoint_label(facts, other), other)
                for other in candidates if other != points]

    def endpoint_check(facts, values, context, item, candidates):
        # Omitting a candidate is wrong only when it changes the extremum or
        # its attainment. Equal-valued/redundant endpoints are not distractors.
        region = sp.Intersection(facts["known"], facts["case_domain"])
        points = api.representatives(values, context, region)

        def summary(selected, parameter_value):
            best, attained = None, False
            for row in facts["candidates"]:
                if row["point"] not in selected:
                    continue
                value = row["value"]
                if facts["parameter"] is not None:
                    value = value.subs(facts["parameter"], parameter_value)
                comparison = api.cmp(value, best) if best is not None else None
                better = comparison is None or (comparison < 0 if facts["bound"] == "inf" else comparison > 0)
                if better:
                    best, attained = value, bool(row["attained"])
                elif comparison == 0:
                    attained = attained or bool(row["attained"])
            if best is None:
                raise api.NotInteractive("endpoint_candidates_missing")
            return best, attained

        def differs(candidate, point):
            full, other = summary(facts["points"], point), summary(candidate.value, point)
            return api.cmp(full[0], other[0]) != 0 or full[1] != other[1]

        kept, records = [], []
        for candidate in candidates:
            witness = next((point for point in points if api.attempt(differs, candidate, point) is True), None)
            if witness is None:
                records.append((candidate, "unproven", None))
                continue
            kept.append(candidate)
            records.append((candidate, "witness", api.latex(witness)))
        return kept, records, []

    def completion(seeds):
        values, context = api.decode_value(seeds[0]["values"]), api.decode_value(seeds[0]["context"])
        function = values.get("function")
        if function is None:
            raise api.GraphUnavailable("function_missing")
        return range_graph({"function": function, "x": values.get("x", context["x"]),
                            "domain": values.get("domain", context["domain"]),
                            "case_domain": values.get("case", {}).get("domain", sp.S.Reals),
                            "parameter": context.get("parameter"), "known": api.known_set(seeds[0])},
                           values, context)

    # --- The hook ax+b/x+c: its turn, where the interval sits, then the range ---------

    def hook_facts(values, context):
        function, variable, domain, turn = values.get("function"), values["x"], values["domain"], values.get("turn")
        if function is None or not turn:
            raise api.NotInteractive("hook_turn_missing")
        try:
            drawn = api.drawing.family(function, variable)
        except api.GraphUnavailable as exc:
            raise api.NotInteractive("hook_family_unknown") from exc
        if drawn["kind"] != "reciprocal_sum":
            raise api.NotInteractive("hook_family_unknown")
        point = turn["point"]
        positive = api.cmp(point, 0) > 0
        half = sp.Interval.open(0, sp.oo) if positive else sp.Interval.open(-sp.oo, 0)
        side = ("left" if api.cmp(domain.sup, point) <= 0
                else "right" if api.cmp(domain.inf, point) >= 0 else "both")
        name = api.named_function(values, function, variable)
        label = name or api.latex(function)
        expanded = api.latex(sp.expand(function))
        formula = f"{name}={expanded}" if name else expanded
        relation = f"{api.latex(variable)}{'>' if positive else '<'}0"
        balance = api.latex(sp.Eq(drawn["a"] * variable, drawn["b"] / variable, evaluate=False))
        return {"drawn": drawn, "x": variable, "domain": domain, "half": half, "point": point,
                "value": turn["value"], "minimum": turn["minimum"], "side": side, "label": label,
                "formula": formula, "relation": relation,
                "display": {"label": label, "formula": formula, "relation": relation, "balance": balance,
                            "x": variable, "domain": domain, "turn_x": point}}

    def turn_candidate(facts, point, minimum):
        value = sp.simplify(facts["drawn"]["function"].subs(facts["x"], point))
        kind = "最低点" if minimum else "最高点"
        return api.Candidate(f"turn:{minimum}:{sp.srepr(point)}:{sp.srepr(value)}",
                             rf"{kind} $\left({api.latex(point)},\,{api.latex(value)}\right)$", (point, value))

    def turn_answer(facts):
        return [{"label": "拐点", "answer": turn_candidate(facts, facts["point"], facts["minimum"])}]

    def turn_errors(facts, item):
        """The other branch's turn, a sign slip in the value, b/a without the square root, the other kind."""
        point, minimum, drawn = facts["point"], facts["minimum"], facts["drawn"]
        sign = 1 if api.cmp(point, 0) > 0 else -1
        produced = [turn_candidate(facts, -point, not minimum)]
        wrong = api.Candidate(f"turn:{minimum}:{sp.srepr(point)}:{sp.srepr(-facts['value'])}",
                              rf"{'最低点' if minimum else '最高点'} "
                              rf"$\left({api.latex(point)},\,{api.latex(-facts['value'])}\right)$")
        produced.append(wrong)
        unrooted = sign * sp.Abs(drawn["b"] / drawn["a"])
        if api.cmp(unrooted, point) != 0:
            produced.append(turn_candidate(facts, unrooted, minimum))
        produced.append(api.Candidate(f"turn:{not minimum}:{sp.srepr(point)}:{sp.srepr(facts['value'])}",
                                      rf"{'最高点' if minimum else '最低点'} "
                                      rf"$\left({api.latex(point)},\,{api.latex(facts['value'])}\right)$"))
        seen, unique = {item["answer"].key}, []
        for candidate in produced:
            if candidate.key not in seen:
                seen.add(candidate.key)
                unique.append(candidate)
        return unique

    side_names = {"left": "左侧", "right": "右侧", "both": "两侧都有"}

    def side_answer(facts):
        return [{"label": rf"区间 ${api.latex(facts['domain'])}$ 在拐点 ${api.latex(facts['x'])}"
                          rf"={api.latex(facts['point'])}$ 的",
                 "answer": api.Candidate("side:" + facts["side"], side_names[facts["side"]], facts["side"])}]

    def other_sides(facts, item):
        return [api.Candidate("side:" + side, name, side) for side, name in side_names.items()
                if side != item["answer"].value]

    def hook_range_answer(facts):
        return [{"label": f"${facts['display']['label']}$ 在区间上的值域",
                 "answer": api.set_candidate("range", facts["answer"])}]

    def hook_picture(facts, *, interval, marks, title, description, caption=None):
        """The whole branch with a symmetric window around the turn, so the hook shape is visible."""
        drawn, variable, point = facts["drawn"], facts["x"], facts["point"]
        anchors = [point / 3, point, 3 * point, *(end for end, _ in marks)]
        xs = [float(value) for value in anchors]
        ys = [float(value) for value in (api.drawing.value_at(drawn, item, variable) for item in anchors)
              if value is not None]
        bounds = api.drawing.window(xs, ys)
        priority = [*(end for end, _ in marks), *api.drawing.grid(bounds[0], bounds[1])]
        return api.drawing.function_graph(
            drawn, variable, interval, bounds=bounds, x_ticks=api.drawing.ticks(priority, bounds[0], bounds[1]),
            marks=marks, title=title, description=description, caption=caption)

    def hook_shape(facts, values, context):
        variable = facts["x"]
        graph = hook_picture(
            facts, interval=facts["half"], marks=[],
            title=f"y={api.drawing.plain(sp.expand(facts['drawn']['function']))}（{variable}∈{api.drawing.plain(facts['half'])}）的图像",
            description="对勾函数的一支：曲线先朝一个方向走到拐点，再折回",
            caption=f"${facts['formula']}$，${facts['relation']}$")
        return graph

    def hook_interval(facts, values, context, *, caption=None):
        variable, point, value = facts["x"], facts["point"], facts["value"]
        ends = [(end, attained) for end, attained in api.drawing.domain_points(facts["domain"])
                if api.drawing.value_at(facts["drawn"], end, variable) is not None]
        marks = [*ends, *([(point, True)] if all(api.cmp(end, point) != 0 for end, _ in ends) else [])]
        graph = hook_picture(
            facts, interval=facts["domain"], marks=marks,
            title=f"对勾函数 y={api.drawing.plain(sp.expand(facts['drawn']['function']))} 在 {api.drawing.plain(facts['domain'])} 上的一段",
            description=(f"拐点 ({api.drawing.short_label(point)}, {api.drawing.short_label(value)})；"
                         + api.drawing.endpoint_story(facts["drawn"], variable, facts["domain"])),
            caption=caption)
        for entry in graph["params"]["points"]:
            if abs(entry["x"] - float(point)) < 1e-12:
                entry["label"] = f"({api.drawing.short_label(point)}, {api.drawing.short_label(value)})"
                entry["place"] = "below-right" if facts["minimum"] else "above-right"
        return graph

    def hook_completion(seeds):
        values, context = api.decode_value(seeds[0]["values"]), api.decode_value(seeds[0]["context"])
        facts = hook_facts(values, context)
        bound = values["range"]["set"]
        return hook_interval(facts, values, context,
                             caption=f"区间上的一段：${facts['label']} \\in {api.latex(bound)}$")

    def hook_range_facts(values, context):
        facts = range_facts(values, context)
        facts["display"].update(hook_facts(values, context)["display"])
        return facts

    return {"answers": {
        "hook_turn": {"kind": "fixed", "checklist": False, "facts": hook_facts, "answer": turn_answer,
                      "generators": {"turn_alternatives": turn_errors}},
        "hook_side": {"kind": "fixed", "facts": hook_facts, "answer": side_answer,
                      "generators": {"other_hook_sides": other_sides}},
        "hook_range": {"kind": "validated", "checklist": True, "requires_known": True, "facts": hook_range_facts,
                       "answer": hook_range_answer, "validate": validate_range,
                       "generators": {"range_alternatives": range_errors}},
        "division_direction": {"kind": "fixed", "facts": division_facts, "answer": division_answer,
                               "generators": {"reverse_division": direction_error}},
        "divisor_sign": {"kind": "fixed", "facts": division_facts, "answer": sign_answer,
                         "generators": {"other_divisor_signs": other_signs}},
        "movement_direction": {"kind": "fixed", "facts": move_facts, "answer": division_answer,
                               "generators": {"reverse_division": direction_error}},
        "certified_range": {"kind": "validated", "requires_known": True, "facts": range_facts,
                            "answer": answer_set, "validate": validate_range,
                            "generators": {"range_alternatives": range_errors}},
        "endpoint_candidates": {"kind": "validated", "checklist": True, "requires_known": True,
                                "facts": endpoint_facts, "answer": endpoint_answer,
                                "validate": endpoint_check, "generators": {"omit_endpoint": endpoint_errors}},
    }, "stem_graphs": {"range_function": ({"certified_range"}, range_graph),
                       "hook_shape": ({"hook_turn"}, hook_shape),
                       "hook_interval": ({"hook_side", "hook_range"}, hook_interval)},
        "option_graphs": {"range_sets": ({"certified_range"}, range_options)},
        "completion_graphs": {"range_evidence_function": completion, "hook_completion": hook_completion}}
