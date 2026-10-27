"""Mathematical card wording, versioned with the execution fingerprint."""

from fractions import Fraction

import sympy as sp

from .math_values import latex


def condition_label(kind):
    return {
        "radicand_nonnegative": "被开方数",
        "denominator_nonzero": "分母",
        "zero_power_base_nonzero": "零次幂的底数",
    }[kind]


def parameter_view(values):
    """Present the checked square-root condition and its supplied quantifier.

    This projection does not solve for the parameter or infer a new condition.
    Its structural checks keep a mismatched seed from explaining another tree.
    """
    description, rows = values["description"], values["constraints"]
    if (description.get("task") != "match_domain" or len(rows) != 1
            or description["expression_ast"][:2] != ["call", "sqrt"]):
        raise ValueError("domain.parameter_single_radicand_required")
    row = rows[0]
    condition = row["condition"]
    if (row["kind"] != "radicand_nonnegative" or row["ast_path"] != [2]
            or row["source_ref"] != description["source_ref"]
            or row["expression_ast"] != description["expression_ast"][2]
            or not isinstance(condition, sp.GreaterThan) or condition.rhs != 0):
        raise ValueError("domain.parameter_condition_source_mismatch")
    expression, relation = description["expression_latex"], latex(condition)
    if values["phase"] == "parameter_conditions":
        return {
            "domain_explanation": rf"原式为 ${expression}$。平方根有意义要求被开方数非负，因此须有 ${relation}$。",
            "domain_lines": [{"label": "原式", "math": expression},
                             {"label": "有意义的条件", "math": relation}],
        }
    if (values["phase"] != "parameter_universal"
            or description.get("prescribed_domain_ast") != ["real"]
            or values["domain"] != sp.S.Reals or values["quantifier"] != "∀"
            or values["relation"] != condition or values["universal_statement"] != condition
            or str(values["x"]) != description["variable"]):
        raise ValueError("domain.parameter_universal_mismatch")
    variable = latex(values["x"])
    domain = r"D_{" + description["function_name"] + r"}=\mathbb{R}"
    universal = rf"\forall {variable}\in\mathbb{{R}},\quad {relation}"
    return {
        "domain_explanation": (
            rf"定义域恰为全体实数，意味着每一个实数 ${variable}$ 都使原式有意义。"
            rf"因此 ${domain}$ 等价于 ${universal}$。接下来对这个恒成立条件求参数范围。"
        ),
        "domain_lines": [{"label": "已知定义域", "math": domain},
                         {"label": "等价的全称条件", "math": universal}],
    }


def _has_positive_power(ast):
    """Read admitted original syntax for wording only; never derive restrictions."""
    if not isinstance(ast, list):
        return False
    if ast[0] == "^" and ast[2][0] == "number" and Fraction(ast[2][1]) > 0:
        return True
    return any(_has_positive_power(child) for child in ast[1:] if isinstance(child, list))


def presentation(values):
    rows, description = values["constraints"], values["description"]
    phase = values["phase"]
    expression = description["expression_latex"]
    if phase == "locations":
        lines = [
            {"label": condition_label(row["kind"]), "math": latex(row["condition"].lhs)}
            for row in rows
        ] or [{"label": "限制", "math": r"\mathbb{R}"}]
        steps = [rf"原式为 $\displaystyle {expression}$。"]
        for row in rows:
            piece = latex(row["condition"].lhs)
            if row["kind"] == "radicand_nonnegative":
                steps.append(rf"根号要求被开方数有意义，故须检查 ${piece}$。")
            elif row["kind"] == "zero_power_base_nonzero":
                steps.append(rf"零次幂要求底数不为零，故须检查 ${piece}$。")
            else:
                steps.append(rf"分母不能为零，故须检查 ${piece}$。")
        if _has_positive_power(description["expression_ast"]):
            steps.append("正整数次幂本身不增加输入限制，底式中的限制仍须保留。")
        if not rows:
            steps.append("原式没有额外的输入限制。")
        else:
            steps.append("以上位置的限制都要保留。")
    elif phase == "conditions":
        lines = [
            {
                "label": condition_label(row["kind"]),
                "math": latex(row["condition"]),
            }
            for row in rows
        ] or [{"label": "条件", "math": r"\mathbb{R}"}]
        steps = [rf"原式为 $\displaystyle {expression}$。"]
        for row in rows:
            name = condition_label(row["kind"])
            piece = latex(row["condition"].lhs)
            condition = latex(row["condition"])
            if row["kind"] == "radicand_nonnegative":
                steps.append(rf"{name} ${piece}$ 须非负，即 ${condition}$。")
            else:
                steps.append(rf"{name} ${piece}$ 须非零，即 ${condition}$。")
        if not rows:
            steps.append(r"没有额外限制，输入可取全体实数 $\mathbb{R}$。")
        else:
            steps.append("以上条件须同时成立。")
    elif phase == "solutions":
        lines = [
            {
                "label": "解集",
                "math": latex(row["condition"])
                + r"\quad\Longrightarrow\quad "
                + latex(solution),
            }
            for row, solution in zip(rows, values["solutions"])
        ] or [{"label": "解集", "math": r"\mathbb{R}"}]
        steps = []
        for row, solution in zip(rows, values["solutions"]):
            steps.append(
                rf"由 ${latex(row['condition'])}$ 得 ${latex(solution)}$。"
            )
        if not rows:
            steps.append(r"没有额外条件，解集为 $\mathbb{R}$。")
    else:
        # Highlight keeps the short final set so narrow screens are not forced
        # into a one-line horizontal scroll of the whole intersection chain.
        lines = [{"label": "定义域", "math": latex(values["domain"])}]
        sets = [*values["solutions"], values["input_domain"]]
        chain = (
            r"\left("
            + r"\right)\cap\left(".join(latex(s) for s in sets)
            + r"\right)"
        )
        steps = [
            rf"各条件解集与题给范围求交：$\displaystyle {chain}$。",
            rf"得定义域 ${latex(values['domain'])}$。",
        ]
    return {
        "domain_lines": lines,
        "domain_explanation": "\n".join(steps),
    }


def append_verified_intersection(state, feasible_set, evidence, endpoint_index):
    """Publish the fourth card only after the whole original domain is proved."""
    from copy import deepcopy

    from .execution_contracts import read
    from .presentation import make_fragment, record_seed
    from .presentation_templates import render_highlight, render_template
    from .trajectory import decode_value

    if (
        state.get("verification", {}).get("status") != "verified"
        or evidence.get("status") != "passed"
    ):
        raise ValueError("domain.independent_verification_required")
    values = decode_value(state["result"])["domain_evidence"]
    if values["domain"] != feasible_set:
        raise ValueError("domain.verified_intersection_changed")
    values.update(
        before=[],
        after=[feasible_set],
        phase="intersection",
        endpoint_checks=deepcopy(evidence["points"]),
    )
    sources = [
        f"/steps/{index}/calls/{call_index}"
        for index, step in enumerate(state["trajectory"]["steps"])
        for call_index, call in enumerate(step["calls"])
        if call.get("postconditions")
    ]
    sources.append(f"/finalization/{endpoint_index}")
    specification = read("presentation-registry")["templates"]["domain_intersection"]
    _, _, explanation = render_template(specification, values)
    fragment = make_fragment(
        state,
        unit_id="domain_intersection",
        method_ref=state["method"] + "#verify",
        template="domain_intersection",
        after=[feasible_set],
        source_refs=sources,
        used_basis=[
            "set-intersection-union#intersection",
            "function-concept#elements",
            "interval-notation#finite",
        ],
        explanation=explanation,
        highlight=render_highlight(specification, values),
    )
    state["fragments"].append(fragment)
    state["trajectory"]["math_steps"].append(
        {
            "step_id": fragment["step_id"],
            "math_step_sha256": fragment["math_step_sha256"],
            "source_refs": sources,
            "file": f"math-steps/{state['route_id']}/{fragment['step_id']}.json",
        }
    )
    record_seed(state, fragment, template="domain_intersection", values=values)
    return state
