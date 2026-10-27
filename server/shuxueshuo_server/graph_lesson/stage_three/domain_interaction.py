"""Four domain teaching projections from immutable, checked Stage3 seeds."""

import random
from copy import deepcopy

import sympy as sp

from .capabilities.cases import _relation_set, exact_set_equal
from .domain_borrow import compile_borrow_plane
from .domain_presentation import (
    _halfline,
    condition_label,
    parameter_domain,
    parameter_view,
)
from .domain_visuals import endpoint_checks, number_lines
from .math_values import latex
from .trajectory import decode_value
from .verification import _set_mismatch


def _math(value):
    return "$" + latex(value) + "$"


def _different_sets(correct, candidates):
    seen, result = [correct], []
    for candidate in candidates:
        if any(exact_set_equal(candidate, previous) for previous in seen):
            continue
        witness = _set_mismatch(correct, candidate)
        if witness is None:
            continue
        seen.append(candidate)
        result.append((candidate, witness))
    return result


def _set_options(correct, candidates, prefix="o"):
    others = _different_sets(correct, candidates)
    return (
        [{"value": prefix + "1", "label": _math(correct)}]
        + [
            {"value": prefix + str(i + 2), "label": _math(v)}
            for i, (v, _) in enumerate(others[:3])
        ],
        [{"kind": "distinct_set", "witness": str(w)} for _, w in others[:3]],
    )


def compile_domain(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed["values"])
    if values["phase"] in (
        "parameter_conditions", "parameter_universal", "parameter_borrow", "parameter_return",
    ):
        return compile_parameter(values, interaction_id)
    rows, description, phase = (
        values["constraints"],
        values["description"],
        values["phase"],
    )
    variable = sp.Symbol(description["variable"], real=True)
    part = {
        "id": interaction_id + "#1",
        "title": seed["display_unit"],
        "question": "",
        "feedback": {"answer": "请按原式位置及有意义条件检查。"},
        "submit_label": "确认判断",
    }
    diagnostics = []
    if phase == "locations":
        options, regions = [], []
        for index, row in enumerate(rows, 1):
            value = "o" + str(index)
            region = {
                k: deepcopy(row[k])
                for k in ("source_ref", "ast_path", "condition_id", "basis_refs")
            }
            kind = condition_label(row["kind"])
            region.update(label=kind, option_value=value)
            regions.append(region)
            options.append(
                {"value": value, "label": f"{kind}：" + _math(row["condition"].lhs)}
            )
        # A pedagogical alternative about an always allowed zero numerator is
        # structurally distinct from every required region; never infer it from
        # a prewritten list of problem IDs or constants.
        decoy = "o" + str(len(options) + 1)
        options.append({"value": decoy, "label": "只需排除函数值为 0 的输入"})
        if not rows:
            options.append({"value": "o2", "label": "原式没有额外的输入限制"})
            required = ["o2"]
        else:
            required = [r["option_value"] for r in regions]
        part.update(
            title="找到限制位置",
            question="哪些位置需要检查有意义的条件？可多选。",
            interaction={"type": "multi", "options": options},
            expected_answer={"required": required, "allowed": required},
            source_regions={
                "expression": description["expression_latex"],
                "expression_ast": description["expression_ast"],
                "bound_symbols": {"function_argument": description["variable"]},
                "regions": regions,
            },
        )
    elif phase in ("conditions", "solutions"):
        slots, terms = [], []
        for index, row in enumerate(rows, 1):
            condition = row["condition"]
            # All candidate conditions are evaluated on the same real input
            # line, so equivalent conditions are not mislabeled as distractors.
            if phase == "conditions":
                expr = condition.lhs
                variants = [
                    condition,
                    sp.Gt(expr, 0, evaluate=False),
                    sp.Ge(expr, 0, evaluate=False),
                    sp.Ne(expr, 0, evaluate=False),
                    sp.Lt(expr, 0, evaluate=False),
                ]

                # sqrt-divisor relations are normalized only for comparison.
                def condition_set(
                    rel, source_ast=row["expression_ast"], original_expr=expr
                ):
                    if source_ast[:2] == ["call", "sqrt"]:
                        radial = original_expr**2
                        domain, _ = _relation_set(
                            sp.Ge(radial, 0, evaluate=False), variable
                        )
                        if rel.rel_op == "!=" or rel.rel_op == ">":
                            return domain.intersect(
                                _relation_set(
                                    sp.Ne(radial, 0, evaluate=False), variable
                                )[0]
                            )
                        if rel.rel_op == ">=":
                            return domain
                        return sp.S.EmptySet
                    return _relation_set(rel, variable)[0]

                correct = condition_set(condition)
                kept = [(condition, correct)]
                for alt in variants[1:]:
                    meaning = condition_set(alt)
                    if any(exact_set_equal(meaning, s) for _, s in kept):
                        continue
                    kept.append((alt, meaning))
                options = [
                    {"value": f"s{index}o{i}", "label": _math(expr)}
                    for i, (expr, _) in enumerate(kept, 1)
                ]
                if len(options) < 2:
                    # Constants can make every conventional sign alternative
                    # equivalent; select among proven truth/falsehood instead.
                    options = [
                        {"value": f"s{index}o1", "label": _math(condition)},
                        {
                            "value": f"s{index}o2",
                            "label": "不需要任何有意义条件"
                            if correct != sp.S.Reals
                            else "没有任何输入使原式有意义",
                        },
                    ]
                label = (
                    condition_label(row["kind"])
                    + " "
                    + _math(condition.lhs)
                )
            else:
                correct = values["solutions"][index - 1]
                options, checks = _set_options(
                    correct,
                    [sp.S.Reals, sp.S.EmptySet, sp.S.Reals - correct],
                    f"s{index}o",
                )
                diagnostics.extend(checks)
                label = _math(condition)
            slots.append({"label": label, "options": options})
            terms.append(f"s{index}o1")
        if not slots:
            slots = [
                {
                    "label": "输入限制",
                    "options": [
                        {"value": "s1o1", "label": _math(sp.S.Reals)},
                        {"value": "s1o2", "label": _math(sp.S.EmptySet)},
                    ],
                }
            ]
            terms = ["s1o1"]
        part.update(
            title="列出条件" if phase == "conditions" else "解每个条件",
            question="每一处限制对应什么条件？"
            if phase == "conditions"
            else "每个条件分别得到什么解集？",
            interaction={"type": "checklist", "title": "逐条判断", "slots": slots},
            expected_answer={"terms": terms},
            feedback={"terms": "；".join(dict.fromkeys({
                "radicand_nonnegative": "根号允许被开方数为 0",
                "denominator_nonzero": "分母必须排除 0",
                "zero_power_base_nonzero": "零次幂的底数必须排除 0",
            }[row["kind"]] for row in rows)) + "。" if rows else "原式没有额外的输入限制。"},
        )
    else:
        correct = values["domain"]
        relational = correct.as_relational(variable)

        # Obtain the meaning of the displayed set-builder predicate independently
        # through Boolean set operations, not by trusting its label.
        def predicate_set(predicate):
            if isinstance(predicate, sp.And):
                return sp.Intersection(*(predicate_set(p) for p in predicate.args))
            if isinstance(predicate, sp.Or):
                return sp.Union(*(predicate_set(p) for p in predicate.args))
            return _relation_set(predicate, variable)[0]

        equivalent = predicate_set(relational)
        if not exact_set_equal(correct, equivalent):
            raise ValueError("domain.set_builder_not_equivalent")
        alternatives = [
            sp.Union(*values["solutions"]),
            values["input_domain"],
            sp.S.Reals,
            sp.S.EmptySet,
            sp.S.Reals - correct,
        ]
        options, checks = _set_options(correct, alternatives)
        diagnostics.extend(checks)
        equivalent_id = "o" + str(len(options) + 1)
        options.append(
            {
                "value": equivalent_id,
                "label": r"$\{"
                + latex(variable)
                + r"\in\mathbb{R}\mid "
                + latex(relational)
                + r"\}$",
            }
        )
        diagnostics.append(
            {"kind": "equivalent_domain_representations", "passed": True}
        )
        part.update(
            title="取交集，写定义域",
            question="哪些表示给出了同一个完整定义域？任选一种正确表示。",
            interaction={"type": "choice", "field": "answer", "options": options},
            expected_answer={"one_of": ["o1", equivalent_id]},
        )
    if phase in ("solutions", "intersection"):
        lines = number_lines(values, include_result=phase == "intersection")
        part["condition_number_lines"] = (
            lines[:-1] if phase == "intersection" else lines
        )
        if phase == "intersection":
            part["completion_number_line"] = lines[-1]
            part["endpoint_checks"] = endpoint_checks(
                values["endpoint_checks"], description["variable"]
            )
    randomizer = random.Random(interaction_id)
    if "options" in part["interaction"]:
        randomizer.shuffle(part["interaction"]["options"])
    for slot in part["interaction"].get("slots", []):
        randomizer.shuffle(slot["options"])
    return {"parts": [part], "diagnostics": diagnostics}


def _reciprocal_parameter_conditions(values, interaction_id):
    """Ask for the two original rules separately, before their strict reduction."""
    rows, description = values["constraints"], values["description"]
    slots = []
    randomizer = random.Random(interaction_id)
    for index, row in enumerate(rows, 1):
        condition = row["condition"]
        if row["kind"] == "radicand_nonnegative":
            variants = [condition, sp.Gt(condition.lhs, 0, evaluate=False), sp.Ne(condition.lhs, 0, evaluate=False)]
            feedback = "这里只填写平方根本身的要求：被开方数可以为 0，但不能为负。分母限制须另行保留。"
        else:
            variants = [condition, sp.Ge(condition.lhs, 0, evaluate=False), sp.Eq(condition.lhs, 0, evaluate=False)]
            feedback = "分母不能为 0；只要求非负会遗漏分母为 0 的情形。"
        options = [{"value": f"s{index}o{i}", "label": _math(value),
                    **({"feedback": feedback} if i != 1 else {})}
                   for i, value in enumerate(variants, 1)]
        randomizer.shuffle(options)
        slots.append({"label": condition_label(row["kind"]) + " " + _math(row["condition"].lhs),
                      "options": options})
    return {
        "parts": [{
            "id": interaction_id + "#1", "title": "列出根号与分母的条件",
            "question": f"原式为 ${description['expression_latex']}$。按根号与分母的基本要求，分别填写各条原始条件。",
            "submit_label": "确认判断", "interaction": {"type": "checklist", "title": "分别保留原式限制", "slots": slots},
            "expected_answer": {"terms": [f"s{index}o1" for index in range(1, len(rows) + 1)]},
            "feedback": {"answer": "根号要求被开方数非负，分母还须非零，各条条件都要保留。"},
        }],
        "diagnostics": [{"kind": "checked_original_domain_rules", "conditions": [row["condition_id"] for row in rows]}],
    }


def _reciprocal_parameter_reduction(values, interaction_id):
    # Compare the rules on a generic real radicand. A particular polynomial
    # can make >= and > equivalent, which must never create a false distractor.
    u = sp.Dummy("radicand", real=True)
    constructors = [sp.Gt, sp.Ge, sp.Ne]
    meanings = [_relation_set(make(u, 0, evaluate=False), u)[0] for make in constructors]
    witnesses = [_set_mismatch(meanings[0], other) for other in meanings[1:]]
    if any(witness is None for witness in witnesses):
        raise ValueError("domain.parameter_reduction_options_equivalent")
    feedback = "实数平方根先要求被开方数非负；分母再排除平方根为 0，所以被开方数必须严格大于 0。"
    options = [{"value": f"o{index}", "label": label, **({"feedback": feedback} if index != 1 else {})}
               for index, label in enumerate([r"$u>0$", r"$u\geq 0$", r"$u\ne 0$"], 1)]
    random.Random(interaction_id).shuffle(options)
    part = {
        "id": interaction_id + "#1", "title": "合并有意义的条件", "submit_label": "确认判断",
        "question": (f"把分母根号的被开方数 ${latex(values['constraints'][1 if _halfline(values['description']) else 0]['condition'].lhs)}$ 记作 $u$。"
                     r"对实数 $u$，把 $u\geq 0$ 与 $\sqrt{u}\ne 0$ 合在一起，相当于什么条件？"),
        "interaction": {"type": "choice", "field": "answer", "options": options},
        "expected_answer": {"one_of": ["o1"]}, "feedback": {"answer": feedback},
    }
    return part, [{"kind": "strict_radicand_rule_distinct", "witness": str(point)} for point in witnesses]


def compile_parameter(values, interaction_id):
    """M6 narrative cards: extract, transform, borrow method, then return."""
    view = parameter_view(values)  # Validate the source binding and certified reduction.
    description = values["description"]
    part = {"id": interaction_id + "#1", "submit_label": "确认判断"}
    if values["phase"] == "parameter_conditions":
        if description.get("has_division"):
            return _reciprocal_parameter_conditions(values, interaction_id)
        # Compare the square-root rule on a generic real radicand, rather than
        # solving the still-unknown parameter range to invent distractors.
        condition = values["constraints"][0]["condition"]
        radicand = sp.Dummy("radicand", real=True)
        constructors = [sp.Ge, sp.Gt, sp.Ne]
        meanings = [_relation_set(make(radicand, 0, evaluate=False), radicand)[0]
                    for make in constructors]
        witnesses = [_set_mismatch(meanings[0], meaning) for meaning in meanings[1:]]
        if any(witness is None for witness in witnesses):
            raise ValueError("domain.parameter_condition_options_equivalent")
        feedback = "平方根允许被开方数为 0，但不允许为负，应保留非负条件。"
        options = [{"value": f"o{index}", "label": _math(make(condition.lhs, 0, evaluate=False)),
                    **({"feedback": feedback} if index != 1 else {})}
                   for index, make in enumerate(constructors, 1)]
        part.update(
            title="列出根式有意义的条件",
            question=f"原式为 ${description['expression_latex']}$。根号对被开方数要求什么条件？",
        )
        diagnostics = [{"kind": "radicand_rule_distinct", "witness": str(point)} for point in witnesses]
    elif values["phase"] == "parameter_universal":
        variable, relation = latex(values["x"]), latex(values["universal_statement"])
        domain_value = parameter_domain(values)
        domain_label = latex(domain_value)
        if _halfline(description):
            feedback = "分母已把域外输入排除；要使定义域恰为题给范围，域内每一个输入都必须使分子根号有意义。"
            options = [
                {"value": "o1", "label": rf"每一个 ${variable}\in {domain_label}$ 都应使分子根号有意义"},
                {"value": "o2", "label": rf"只需找到一个 ${variable}\in {domain_label}$ 使分子根号有意义", "feedback": feedback},
            ]
            question = (
                rf"分母的条件合为 ${latex(values['domain_equivalence']['denominator_condition'])}$，恰好允许 ${domain_label}$，"
                "域外原式已因分母根号无意义或分母为零而被排除。"
                rf"要使定义域恰为 ${domain_label}$，对域内输入应怎样检查分子的条件 ${relation}$？"
            )
        else:
            feedback = "定义域恰为全体实数，要求条件对每一个实数输入恒成立；只找到某个合法输入还不够。"
            options = [
                {"value": "o1", "label": f"每一个实数 ${variable}$ 都应使原式有意义"},
                {"value": "o2", "label": f"只需找到一个实数 ${variable}$ 使原式有意义", "feedback": feedback},
            ]
            question = (rf"原式有意义的条件为 ${relation}$。题目要求定义域恰为 $\mathbb{{R}}$，"
                        "按照定义域的含义，应检查哪些实数输入？")
        part.update(title="转化为恒成立问题", question=question)
        diagnostics = [{"kind": "checked_domain_equality_quantifier", "quantifier": values["quantifier"]}]
    elif values["phase"] == "parameter_borrow":
        return compile_borrow_plane(values, interaction_id)
    else:
        parameter = latex(values["parameter"])
        answer = latex(values["candidate_set"])
        domain = r"D_{" + description["function_name"] + "}=" + latex(parameter_domain(values))
        feedback = "子方法求出的是参数范围；它要保证原题的定义域恰为题给范围，而不是另求一个输入集合。"
        options = [
            {"value": "o1", "label": rf"使 ${domain}$ 成立的参数 ${parameter}$ 的取值范围"},
            {"value": "o2", "label": rf"自变量的定义域，不再管参数 ${parameter}$", "feedback": feedback},
            {"value": "o3", "label": "原式在某个真子集上有意义即可", "feedback": feedback},
        ]
        part.update(
            title="回到定义域求参",
            question=(f"借用的方法已得到 ${parameter}\\in {answer}$。"
                      "这个结果在原题中保证什么？"),
            effects={"log": "回到定义域求参：参数范围保证定义域恰为题给范围。",
                     "nodes": ["method-domain-parameter"]},
        )
        diagnostics = [{"kind": "checked_domain_parameter_return", "answer": answer}]
    # Keep the certified projection on the card for read-back and replay.
    assert view["domain_explanation"]
    random.Random(interaction_id).shuffle(options)
    part.update(interaction={"type": "choice", "field": "answer", "options": options},
                expected_answer={"one_of": ["o1"]}, feedback={"answer": feedback})
    if values["phase"] == "parameter_universal" and description.get("has_division"):
        reduction, checked = _reciprocal_parameter_reduction(values, interaction_id)
        part["id"] = interaction_id + "#2"
        return {"parts": [reduction, part], "diagnostics": [*checked, *diagnostics]}
    return {"parts": [part], "diagnostics": diagnostics}
