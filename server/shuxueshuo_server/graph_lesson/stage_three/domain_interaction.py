"""Four domain teaching projections from immutable, checked Stage3 seeds."""

import random
from copy import deepcopy

import sympy as sp

from .capabilities.cases import _relation_set, exact_set_equal
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
            kind = "被开方数" if row["kind"] == "radicand_nonnegative" else "分母"
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
            options.append({"value": "o2", "label": "没有根号或分母带来的限制"})
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
                    ("被开方数" if row["kind"] == "radicand_nonnegative" else "分母")
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
            feedback={"terms": "根号允许被开方数为 0；分母必须排除 0。"},
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
