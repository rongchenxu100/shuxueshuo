"""Evidence-bound algebra interactions for quadratic routes.

This module registers pure sources with the interaction compiler.  Relations
are distinguished by concrete substitutions in the frozen domain; set answers
by exact symmetric difference; finite value tuples by exact comparison.  The
opening pictures are explicitly schematic quadratic positions, not invented
parameter values of the student's function.
"""

from itertools import product

import sympy as sp


def register(api):
    Candidate, NotInteractive = api.Candidate, api.NotInteractive

    def opening_condition(context, *, strict_coefficient=True, existential_branch=False):
        """Read the necessary opening restriction from this frozen relation.

        The delta/solution seed does not carry an earlier opening card.  Its
        original relation and direction residual are frozen, however, so the
        quadratic coefficient can be selected here without consulting a later
        step or solving a new parameter inequality.
        """
        if "domain" not in context or "quantifier" not in context:
            raise NotInteractive("opening_scope_unknown")
        existential = context["quantifier"] == "∃"
        if context["domain"] != sp.S.Reals or (context["quantifier"] != "∀" and not (
                existential and existential_branch)):
            return None
        relation, variable = context.get("relation"), context.get("x")
        expression = context.get("expression")
        if (not isinstance(relation, sp.Rel) or relation.rel_op not in api.MIRROR
                or not isinstance(variable, sp.Symbol) or expression is None):
            raise NotInteractive("opening_evidence_missing")
        residual = relation.lhs - relation.rhs if relation.rel_op in (">", ">=") else relation.rhs - relation.lhs
        if sp.simplify(residual-expression) != 0 or not expression.is_polynomial(variable):
            raise NotInteractive("opening_evidence_unverified")
        polynomial = sp.Poly(expression, variable)
        if polynomial.degree() != 2:
            return None
        coefficient = polynomial.nth(2)
        parameter = context.get("parameter")
        if coefficient.free_symbols - {parameter}:
            raise NotInteractive("opening_evidence_unverified")
        if existential:
            # The delta question is conditional on downward opening. Upward
            # opening already satisfies existence for any discriminant.
            return sp.Lt(coefficient, 0, evaluate=False)
        # A solution card may also belong to a route retaining a degenerate
        # case.  Nonnegative is necessary there; the discriminant card requires
        # a genuinely quadratic expression and therefore strict positivity.
        return (sp.Gt if strict_coefficient else sp.Ge)(coefficient, 0, evaluate=False)

    def opening_holds(facts, point):
        condition = facts.get("opening_condition")
        if condition is None:
            return True
        parameter = facts.get("parameter")
        evaluated = condition.subs(parameter, point) if parameter is not None else condition
        return sp.simplify(evaluated) is sp.true

    def relation_facts(values, context, *, source="after"):
        relation = next((item for item in values[source] if isinstance(item, sp.Rel)), None)
        if relation is None:
            raise NotInteractive("relation_evidence_missing")
        return {"relation": relation, "x": context.get("x"), "parameter": context.get("parameter"),
                "domain": context.get("domain", sp.S.Reals), "case": values.get("case", {}),
                "display": {"relation": relation, "before": "、".join(api.math(v) for v in values["before"]),
                            "delta": relation.lhs - relation.rhs}}

    def relation_answer(facts):
        relation = facts["relation"]
        return [{"answer": Candidate("relation:" + sp.srepr(relation), api.math(relation), relation)}]

    def changed_relations(facts, item):
        relation = item["answer"].value
        operators = [api.MIRROR[relation.rel_op], api.FLIP_STRICTNESS[relation.rel_op]] \
            if relation.rel_op in api.MIRROR else ["!=", ">", "<"]
        return [Candidate("relation:" + operator,
                          api.math(sp.Rel(relation.lhs, relation.rhs, operator, evaluate=False)),
                          sp.Rel(relation.lhs, relation.rhs, operator, evaluate=False)) for operator in operators]

    def moved_constants(facts, item):
        relation = item["answer"].value
        symbols = sorted(relation.free_symbols, key=str)
        constant = sp.expand(relation.lhs - relation.rhs).subs(dict.fromkeys(symbols, 0))
        changes = [2 * constant] if constant != 0 else [sp.S.One]
        return [Candidate("constant:" + sp.srepr(change),
                          api.math(sp.Rel(relation.lhs - change, relation.rhs, relation.rel_op, evaluate=False)),
                          sp.Rel(relation.lhs - change, relation.rhs, relation.rel_op, evaluate=False))
                for change in changes]

    def boundary_neighbors(relation, parameter, variable, x):
        """Parameter values one unit either side of where a linear relation switches truth at ``x``."""
        if not isinstance(relation, sp.Rel):
            return []
        difference = relation.lhs - relation.rhs
        if variable is not None and x is not None:
            difference = difference.subs(variable, x)
        difference = sp.cancel(difference)
        if not difference.is_polynomial(parameter) or difference.free_symbols - {parameter}:
            return []
        polynomial = sp.Poly(difference, parameter)
        if polynomial.degree() != 1:
            return []
        root = -polynomial.nth(0) / polynomial.nth(1)
        return [root - 1, root + 1] if root.is_finite else []

    def relation_check(facts, values, context, item, candidates):
        relation = item["answer"].value
        parameter, variable = facts["parameter"], facts["x"]
        known = sp.Intersection(facts["known"], facts["case"].get("domain", sp.S.Reals))
        parameter_values = api.representatives(values, context, known) if parameter is not None else [None]
        parameter_values = [point for point in parameter_values if opening_holds(facts, point)]
        if parameter is not None and not parameter_values:
            raise NotInteractive("answer_unverified")
        variable_values = api.representatives(values, context, facts["domain"]) if variable is not None else [None]
        # A one-variable condition never needs the quantified variable, whose
        # domain may have no grid point.  Conversely, parameter-free identities
        # still require a nonempty allowed parameter region.
        needs_x = variable is not None and any(variable in candidate.value.free_symbols
                                               for candidate in [item["answer"], *candidates])
        points = []
        for p, x in product(parameter_values, variable_values if needs_x else [None]):
            substitutions = {}
            if parameter is not None:
                substitutions[parameter] = p
            if variable is not None and x is not None:
                substitutions[variable] = x
            points.append(substitutions)
        # Grid parameters can all lie on one side of every boundary (e.g. h(x) > 4 on (1, 2)),
        # so also sample just beside each relation's own parameter boundary at every x.
        # Appended last, these only separate candidates; earlier witnesses are unchanged.
        if parameter is not None:
            for x, candidate in product(variable_values if needs_x else [None], [item["answer"], *candidates]):
                for p in api.attempt(boundary_neighbors, candidate.value, parameter, variable, x) or []:
                    point = {parameter: p, **({variable: x} if variable is not None and x is not None else {})}
                    if point not in points and known.contains(p) is sp.true and opening_holds(facts, p):
                        points.append(point)

        def truth(expression, point):
            substituted = expression.subs(point)
            # Frozen derivations retain constant relations with evaluate=False.
            # Substitution does nothing to 0 <= 0 (or 1 <= 0), so explicitly
            # decide only closed real relations. Undefined samples stay unknown.
            if (isinstance(substituted, sp.Rel) and not substituted.free_symbols
                    and substituted.lhs.is_real is True and substituted.rhs.is_real is True):
                substituted = sp.Rel(substituted.lhs, substituted.rhs, substituted.rel_op)
            return True if substituted is sp.true else False if substituted is sp.false else None

        expected = [api.attempt(truth, relation, point) for point in points]
        if not any(value is not None for value in expected):
            raise NotInteractive("answer_unverified")
        kept, records, seen = [], [], []
        for candidate in candidates:
            actual = [api.attempt(truth, candidate.value, point) for point in points]
            witness = next((point for point, left, right in zip(points, expected, actual, strict=True)
                            if left is not None and right is not None and left != right), None)
            duplicate = any(all(a is None or b is None or a == b for a, b in zip(actual, other, strict=True))
                            for other in seen)
            if witness is None or duplicate:
                records.append((candidate, "unproven" if witness is None else "duplicate", None))
                continue
            kept.append(candidate)
            seen.append(actual)
            records.append((candidate, "witness", ",".join(f"{symbol}={api.latex(value)}"
                                                          for symbol, value in witness.items())))
        return kept, records, []

    def quadratic_display(values, context, *, requested_direction=None):
        """Keep the frozen normalized polynomial and comparison in student view."""
        if context.get("domain") != sp.S.Reals or context.get("quantifier") not in ("∀", "∃"):
            raise NotInteractive("opening_domain_unsupported")
        relation, variable = values.get("relation"), context.get("x")
        original = context.get("relation")
        if (not isinstance(relation, sp.Rel) or relation.rel_op not in api.MIRROR
                or not isinstance(original, sp.Rel) or original.rel_op not in api.MIRROR
                or not isinstance(variable, sp.Symbol) or context.get("expression") is None):
            raise NotInteractive("opening_evidence_missing")
        expression = relation.lhs - relation.rhs
        target_side = 1 if relation.rel_op in (">", ">=") else -1
        residual = target_side * expression
        if (relation.rhs != 0 or not expression.is_polynomial(variable)
                or sp.simplify(residual - context["expression"]) != 0
                or ("expression" in values and sp.simplify(residual - values["expression"]) != 0)):
            raise NotInteractive("opening_evidence_unverified")
        polynomial = sp.Poly(expression, variable)
        if polynomial.degree() != 2 or expression.free_symbols - {variable, context.get("parameter")}:
            raise NotInteractive("opening_evidence_unverified")
        strict = relation.rel_op in (">", "<")
        if strict != (original.rel_op in (">", "<")):
            raise NotInteractive("opening_evidence_unverified")
        if "strict" in values and (type(values["strict"]) is not bool or values["strict"] != strict):
            raise NotInteractive("opening_evidence_unverified")
        coefficient = polynomial.nth(2)
        existential = context["quantifier"] == "∃"
        direction = requested_direction or (-target_side if existential else target_side)
        if requested_direction is None and (target_side * coefficient).is_positive is True and existential:
            raise NotInteractive("existence_automatic")
        if requested_direction is None and (target_side * coefficient).is_negative is True and not existential:
            raise NotInteractive("universal_opening_impossible")
        opening = "向上" if direction > 0 else "向下"
        extreme = "最低点" if direction > 0 else "最高点"
        side = "上方" if target_side > 0 else "下方"
        sign = "大于零" if direction > 0 else "小于零"
        determined = (direction * coefficient).is_positive is True
        scope = f"二次项系数{sign}，图像开口{opening}" if determined else f"当二次项系数{sign}、图像开口{opening}时"
        requirement = "至少有一个实数解" if existential else "对所有实数成立"
        feedback = (f"开口{opening}时顶点是{extreme}。顶点须在横轴{side}；"
                    "非严格关系还允许顶点恰好落在横轴上。")
        return {"strict": strict, "existential": existential, "x": variable,
                "direction": direction, "target_side": target_side,
                "coefficient": coefficient, "opening_determined": determined,
                "display": {"relation": relation, "expression": expression,
                            "opening_question": f"{scope}，哪些图像位置能使关系{requirement}？",
                            "opening_feedback": feedback,
                            "scope_note": f"{scope}，要使整理后的关系{requirement}",
                            "delta_feedback": feedback}}

    def discriminant_facts(values, context):
        display = quadratic_display(values, context)
        data = relation_facts(values, context, source="before")
        condition = opening_condition(context, existential_branch=True)
        if condition is None:
            raise NotInteractive("opening_evidence_missing")
        data["opening_condition"] = condition
        data["display"].update({key: display["display"][key] for key in ("scope_note", "delta_feedback")})
        data["display"]["delta_opening"] = "向上" if display["direction"] > 0 else "向下"
        return data

    def degree_facts(values, context):
        coefficient = values["coefficient"]
        original = values.get("relation", context.get("relation"))
        if isinstance(original, sp.Rel) and original.rel_op in ("<", "<="):
            coefficient = -coefficient
        if values.get("degree_coefficient", coefficient) != coefficient:
            raise NotInteractive("degree_coefficient_unverified")
        relation = sp.Eq(coefficient, 0, evaluate=False)
        return {"relation": relation, "x": None, "parameter": values["parameter"], "domain": sp.S.Reals,
                "case": {}, "display": {"coefficient": coefficient, "parameter": values["parameter"]}}

    def direction_facts(values, context, direction, *, unavailable=False):
        """Discuss both openings against the same frozen polynomial and goal."""
        if type(values.get("strict")) is not bool:
            raise NotInteractive("opening_evidence_missing")
        facts = quadratic_display(values, context, requested_direction=direction)
        coefficient = facts["coefficient"]
        absent = (direction * coefficient).is_nonpositive is True
        rejected = not facts["existential"] and direction != facts["target_side"]
        if unavailable != (absent or rejected):
            raise NotInteractive("opening_direction_part_not_needed")
        opening = "向上" if direction > 0 else "向下"
        condition = sp.Rel(coefficient, 0, ">" if direction > 0 else "<", evaluate=False)
        requirement = "至少有一个实数解" if facts["existential"] else "对所有实数成立"
        if unavailable:
            if absent:
                facts["unavailable_label"] = "本题不存在这种开口"
                if not coefficient.free_symbols:
                    actual = "向上" if coefficient.is_positive else "向下"
                    feedback = f"二次项系数为 {api.math(coefficient)}，图像开口{actual}，因此不存在开口{opening}的情况。"
                else:
                    feedback = f"二次项系数为 {api.math(coefficient)}，不可能满足 {api.math(condition)}，因此不存在开口{opening}的情况。"
            else:
                facts["unavailable_label"] = "此开口不适合"
                limit = "正无穷" if direction > 0 else "负无穷"
                feedback = f"开口{opening}时，两端的函数值趋于{limit}，不能使该关系对所有实数成立。"
            facts["display"].update(
                opening_question=f"开口{opening}的情况能否满足原题要求？",
                opening_feedback=feedback)
        else:
            premise = f"当 {api.math(condition)}、" if coefficient.free_symbols else ""
            facts["display"]["opening_question"] = (
                f"{premise}图像开口{opening}时，哪些位置能使关系{requirement}？")
            if facts["existential"] and direction == facts["target_side"]:
                limit = "正无穷" if direction > 0 else "负无穷"
                side = "上方" if direction > 0 else "下方"
                facts["display"]["opening_feedback"] = (
                    f"三种位置都可以。开口{opening}时，两端的函数值趋于{limit}，总有部分图像位于横轴{side}，因此有实数解。")
        return facts

    def unavailable_answer(facts):
        return [{"answer": Candidate("opening:unavailable", facts["unavailable_label"], False)}]

    def unavailable_variant(facts, item):
        return [Candidate("opening:continue", "可继续判断图像位置", True)]

    def directional_completion(seeds, direction):
        seed, = seeds
        values, context = api.decode_value(seed["values"]), api.decode_value(seed["context"])
        return completed_positions(direction_facts(values, context, direction), values, context)

    def position(value, facts):
        if value == 0:
            label = "与横轴相切，只有一个公共点"
        elif value * facts["direction"] < 0:
            label = "穿过横轴，有两个公共点"
        else:
            label = f"完全位于横轴{'上方' if value > 0 else '下方'}，与横轴不相交"
        return Candidate(f"position:{value}", label, sp.Integer(value))

    def opening_answer(facts):
        return [{"answer": position(facts["target_side"], facts)}]

    def opening_variants(facts, item):
        return [position(0, facts), position(-facts["target_side"], facts)]

    def position_holds(facts, candidate):
        # For existence on R, opening towards the requested side makes the
        # function unbounded in that direction, regardless of vertex height.
        if facts["existential"] and facts["direction"] == facts["target_side"]:
            return sp.true
        return sp.Rel(candidate.value, 0, facts["display"]["relation"].rel_op)

    def opening_check(facts, values, context, item, candidates):
        kept, records, correct = [], [], []
        for candidate in candidates:
            # Check the frozen comparison by the extremum or unbounded tail.
            holds = position_holds(facts, candidate)
            if holds is sp.true:
                correct.append(candidate)
                proof = ("unbounded_target_direction" if facts["existential"] and
                         facts["direction"] == facts["target_side"] else
                         "exact_vertex_maximum" if facts["direction"] < 0 else "exact_vertex_minimum")
                records.append((candidate, "also_correct", proof))
            elif holds is sp.false:
                kept.append(candidate)
                records.append((candidate, "witness", f"{api.latex(facts['x'])}=0"))
            else:
                records.append((candidate, "unproven", None))
        return kept, records, correct

    def opening_graphs(facts, values, context, candidates):
        variable = context["x"]
        direction = facts["direction"]
        opening = "向下" if direction < 0 else "向上"
        graphs = []
        for candidate, correct in candidates:
            drawn = api.drawing.family(direction*variable**2 + candidate.value, variable)
            holds = position_holds(facts, candidate)
            if (holds is sp.true) is not correct:
                raise api.GraphUnavailable("representative_unverified")
            graphs.append(api.drawing.function_graph(
                drawn, variable, sp.Interval(-sp.oo, sp.oo),
                bounds=[-2, 2, -4, 2] if direction < 0 else [-2, 2, -2, 4], x_ticks=[],
                marks=[(sp.S.Zero, True)] if candidate.value == 0 else [],
                title=f"开口{opening}的二次函数位置示意", description=candidate.label))
        return graphs, f"图像仅表示开口{opening}的二次函数与横轴的相对位置。"

    def completed_positions(data, values, context):
        """Keep only the verified allowed positions as the completed conclusion.

        These are schematic positions, not a substituted parameter value or a
        newly solved range. Reuse the same frozen relation and exact vertex
        checks as the options so strictness and direction cannot drift.
        """
        item, = opening_answer(data)
        _, _, additional = opening_check(data, values, context, item, opening_variants(data, item))
        correct = [item["answer"], *additional]
        graphs, _ = opening_graphs(data, values, context, [(item, True) for item in correct])
        opening = "向上" if data["direction"] > 0 else "向下"
        for graph, item in zip(graphs, correct, strict=True):
            graph["caption"] = f"开口{opening}：{item.label}（位置示意）"
        return graphs[0] if len(graphs) == 1 else graphs

    def degenerate_facts(values, context):
        if type(values.get("holds")) is not bool:
            raise NotInteractive("degenerate_evidence_missing")
        return {"holds": values["holds"], "parameter": values["parameter"], "value": values["value"],
                "existential": context.get("quantifier") == "∃",
                "display": {"parameter": values["parameter"], "value": values["value"],
                            "relation": values["after"][0]}}

    def degenerate_label(holds, facts):
        if facts["existential"]:
            return "存在实数解，保留本情况" if holds else "没有实数解，排除本情况"
        return "对所有实数成立，保留本情况" if holds else "不能对所有实数成立，排除本情况"

    def degenerate_answer(facts):
        holds = facts["holds"]
        return [{"label": "代入后是否存在实数解？" if facts["existential"] else "代入后是否满足原题的全称条件？",
                 "answer": Candidate(f"degenerate:{holds}", degenerate_label(holds, facts), holds)}]

    def degenerate_flip(facts, item):
        holds = not item["answer"].value
        return [Candidate(f"degenerate:{holds}", degenerate_label(holds, facts), holds)]

    def square_facts(values, context):
        variable, function, vertex, bound = values["x"], values["function"], values["vertex"], values["extremum"]
        poly = sp.Poly(function, variable)
        if (poly.degree() != 2 or not api.finite(vertex) or not api.finite(bound)
                or sp.simplify(function - values["square"]) != 0
                or sp.simplify(sp.diff(function, variable).subs(variable, vertex)) != 0
                or sp.simplify(function.subs(variable, vertex) - bound) != 0
                or context["domain"].contains(vertex) is not sp.true):
            raise NotInteractive("square_evidence_unverified")
        sign = api.cmp(poly.nth(2), 0)
        name = api.named_function(values, function, variable)
        return {"function": function, "x": variable, "parameter": context.get("parameter"),
                "domain": context["domain"], "vertex": vertex, "bound": bound,
                "display": {"function": f"{name}={api.latex(function)}" if name else function,
                            "x": variable, "domain": context["domain"],
                            "extremum_name": "最小值" if sign > 0 else "最大值"}}

    def square_candidate(facts, vertex, bound):
        label = f"在 ${api.latex(facts['x'])}={api.latex(vertex)}$ 时取得{facts['display']['extremum_name']} {api.math(bound)}"
        return Candidate(f"square:{sp.srepr(vertex)}:{sp.srepr(bound)}", label, (vertex, bound))

    def square_answer(facts):
        return [{"answer": square_candidate(facts, facts["vertex"], facts["bound"])}]

    def square_variants(facts, item):
        vertex, bound = facts["vertex"], facts["bound"]
        return [square_candidate(facts, -vertex if vertex != 0 else 1, bound),
                square_candidate(facts, vertex, -bound if bound != 0 else 1),
                square_candidate(facts, bound, vertex)]

    def tuple_check(facts, values, context, item, candidates):
        kept, records = [], []
        for candidate in candidates:
            def same(other, candidate=candidate):
                return all(api.cmp(left, right) == 0
                           for left, right in zip(candidate.value, other.value, strict=True))
            comparisons = [api.attempt(same, other) for other in [item["answer"], *kept]]
            if any(value is None for value in comparisons):
                records.append((candidate, "unproven", None))
                continue
            if any(comparisons):
                records.append((candidate, "duplicate", None))
            else:
                kept.append(candidate)
                records.append((candidate, "witness", "exact_value_mismatch"))
        return kept, records, []

    def solution_facts(values, context, *, include_opening=True):
        answer = values["after"][-1]
        if not isinstance(answer, sp.Set):
            raise NotInteractive("solution_evidence_missing")
        return {"answer": answer, "parameter": context["parameter"], "case": values.get("case", {}),
                "opening_condition": opening_condition(context, strict_coefficient=False) if include_opening else None,
                "solutions": list(answer.args) if isinstance(answer, sp.Union) else [answer],
                "display": {"parameter": context["parameter"],
                            "conditions": " 且 ".join(api.math(value) for value in values["before"]),
                            "case_note": ("（还须满足当前情况 " + api.math(values["case"]["condition"]) + "）")
                            if values.get("case") else ""}}

    def merged_facts(values, context):
        facts = solution_facts(values, context, include_opening=False)
        facts["solutions"] = [row["outputs"]["solution"] for row in values["case_results"]]
        if api.exact_set_equal(sp.Union(*facts["solutions"]), facts["answer"]) is not True:
            raise NotInteractive("merge_evidence_unverified")
        facts["display"]["pieces"] = "、".join(api.math(value) for value in facts["solutions"])
        # The merge question asks for the complete union, including the
        # degenerate cases, rather than solving within an opening branch.
        facts["opening_condition"] = None
        return facts

    def complement(facts, item):
        return [api.set_candidate("set", sp.Complement(sp.S.Reals, item["answer"].value))]

    def solution_check(facts, values, context, item, candidates):
        known = sp.Intersection(facts["known"], facts.get("case", {}).get("domain", sp.S.Reals))
        condition = facts.get("opening_condition")
        if condition is None or not condition.free_symbols:
            if condition is not None and sp.simplify(condition) is not sp.true:
                raise NotInteractive("opening_has_no_representative")
            return api.set_check(item["answer"], candidates, known)

        def witness(left, right):
            difference = sp.Intersection(sp.SymmetricDifference(left, right), known)
            points = api.representatives(values, context, difference)
            return next((point for point in points if opening_holds(facts, point)), None)

        kept, records = [], []
        for candidate in candidates:
            point = api.attempt(witness, candidate.value, item["answer"].value)
            distinct = all(api.attempt(witness, candidate.value, other.value) is not None for other in kept)
            if point is None or not distinct:
                records.append((candidate, "unproven" if point is None else "duplicate", None))
                continue
            kept.append(candidate)
            records.append((candidate, "witness", api.latex(point)))
        return kept, records, []

    def separation_facts(values, context, key):
        relation, moved = values.get(key), values.get("moved")
        if not all(isinstance(item, sp.Rel) and item.rel_op in api.MIRROR for item in (relation, moved)):
            raise NotInteractive("separation_evidence_missing")
        variable, domain = context.get("x"), context.get("domain", sp.S.Reals)
        reverse = moved.rel_op != values.get("separated", moved).rel_op
        return {"relation": relation, "moved": moved, "x": variable, "parameter": context.get("parameter"),
                "domain": domain, "case": values.get("case", {}), "divisor": values.get("divisor", sp.S.One),
                "reverse": reverse,
                "display": {"relation": values["before"][0], "moved": moved, "parameter": context.get("parameter"),
                            "divisor": values.get("divisor", sp.S.One), "x": variable, "domain": domain,
                            "divisor_kind": "负数" if reverse else "正数"}}

    def candidate(relation, variant="default"):
        return Candidate("relation:" + sp.srepr(relation), api.math(relation), relation, variant)

    def rel(lhs, rhs, operator):
        return sp.Rel(lhs, rhs, operator, evaluate=False)

    def ordered_terms(expression, variable):
        terms = list(sp.Add.make_args(sp.expand(expression)))
        if variable is not None and expression.is_polynomial(variable):
            terms.sort(key=lambda term: -sp.degree(term, variable))
        return terms

    def move_sign_error(facts, item):
        relation = item["answer"].value
        return [candidate(rel(relation.lhs, -relation.rhs, relation.rel_op))] if relation.rhs != 0 else []

    def move_partial_sign(facts, item):
        relation = item["answer"].value
        terms = ordered_terms(relation.rhs, facts["x"])
        if len(terms) < 2:
            return []
        return [candidate(rel(relation.lhs, relation.rhs - 2 * terms[-1], relation.rel_op))]

    def flipped_direction(facts, item):
        relation = item["answer"].value
        return [candidate(rel(relation.lhs, relation.rhs, api.MIRROR[relation.rel_op]),
                          "negative" if facts["reverse"] else "positive")]

    def partial_division(facts, item):
        relation, moved, divisor = item["answer"].value, facts["moved"], facts["divisor"]
        terms = ordered_terms(moved.rhs, facts["x"])
        if len(terms) < 2 or divisor == 1:
            return []
        partial = sp.Add(*(sp.cancel(term / divisor) for term in terms[:-1]), terms[-1])
        return [candidate(rel(relation.lhs, partial, relation.rel_op))]

    def division_sign_error(facts, item):
        relation = item["answer"].value
        return [candidate(rel(relation.lhs, -relation.rhs, relation.rel_op))] if relation.rhs != 0 else []

    relation_source = {"kind": "validated", "requires_known": True, "answer": relation_answer,
                       "validate": relation_check,
                       "generators": {"relation_variants": changed_relations, "move_constant_wrong": moved_constants}}
    set_generators = {"flip_endpoint": api.flip_endpoint, "set_complement": complement,
                      "drop_piece": api.drop_piece}
    return {
        "answers": {
            "equivalent_relation": {**relation_source, "facts": relation_facts},
            "discriminant_condition": {**relation_source, "facts": discriminant_facts},
            "zero_coefficient": {**relation_source, "facts": degree_facts,
                                 "generators": {"relation_variants": changed_relations}},
            "moved_relation": {**relation_source, "facts": lambda values, context: separation_facts(
                values, context, "moved"), "generators": {
                    "move_sign_error": move_sign_error, "move_partial_sign": move_partial_sign,
                    "move_direction_error": flipped_direction}},
            "separated_relation": {**relation_source, "facts": lambda values, context: separation_facts(
                values, context, "separated"), "generators": {
                    "division_direction_error": flipped_direction, "partial_division": partial_division,
                    "division_sign_error": division_sign_error}},
            **{f"opening_{name}_positions": {
                "kind": "validated", "facts": lambda values, context, direction=direction: direction_facts(
                    values, context, direction), "answer": opening_answer, "validate": opening_check,
                "generators": {"opening_variants": opening_variants}}
                for name, direction in (("up", 1), ("down", -1))},
            **{f"opening_{name}_unavailable": {
                "kind": "fixed", "checklist": False,
                "facts": lambda values, context, direction=direction: direction_facts(
                    values, context, direction, unavailable=True), "answer": unavailable_answer,
                "generators": {"reverse_opening": unavailable_variant}}
                for name, direction in (("up", 1), ("down", -1))},
            "degenerate_decision": {"kind": "fixed", "facts": degenerate_facts, "answer": degenerate_answer,
                                    "generators": {"flip_degenerate": degenerate_flip}},
            "square_extremum": {"kind": "validated", "requires_known": True, "facts": square_facts,
                                "answer": square_answer, "validate": tuple_check,
                                "generators": {"square_variants": square_variants}},
            "algebra_solution": {"kind": "set", "facts": solution_facts, "answer": api.case_solution_answer,
                                 "validate": solution_check, "generators": set_generators},
            "degree_merged_set": {"kind": "set", "facts": merged_facts, "answer": api.case_solution_answer,
                                  "validate": solution_check, "generators": set_generators},
        },
        "option_graphs": {"opening_positions": ({"opening_up_positions", "opening_down_positions"}, opening_graphs),
                          "algebra_sets": ({"algebra_solution", "degree_merged_set"}, api.set_options)},
        "stem_graphs": {"square_function": ({"square_extremum"}, api.function_stem)},
        "completion_graphs": {"opening_up_positions": lambda seeds: directional_completion(seeds, 1),
                              "opening_down_positions": lambda seeds: directional_completion(seeds, -1)},
    }
