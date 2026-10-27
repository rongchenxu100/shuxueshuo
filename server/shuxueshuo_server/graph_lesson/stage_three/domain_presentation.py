"""Mathematical card wording, versioned with the execution fingerprint."""

from fractions import Fraction

import sympy as sp

from ..stage_two.recognition import load_nodes
from .math_values import latex


def condition_label(kind):
    return {
        "radicand_nonnegative": "被开方数",
        "denominator_nonzero": "分母",
        "zero_power_base_nonzero": "零次幂的底数",
    }[kind]


def _halfline(description):
    return description.get("parameter_family") == "halfline_root_ratio"


def _parameter_root(description):
    ast = description["expression_ast"]
    reciprocal = ast[0] == "/"
    root = ast[1] if _halfline(description) else ast[2] if reciprocal else ast
    if (description.get("task") != "match_domain" or root[:2] != ["call", "sqrt"]
            or description.get("has_division", False) is not reciprocal
            or (_halfline(description) and (not reciprocal or ast[2][:2] != ["call", "sqrt"]))):
        raise ValueError("domain.parameter_single_radicand_required")
    return root, reciprocal


def parameter_condition_rows(description, rows):
    """Bind every original root/denominator restriction before its reduction."""
    root, reciprocal = _parameter_root(description)
    halfline = _halfline(description)
    if len(rows) != (3 if halfline else 2 if reciprocal else 1):
        raise ValueError("domain.parameter_single_radicand_required")
    row = rows[0]
    condition = row["condition"]
    if (row["kind"] != "radicand_nonnegative"
            or row["ast_path"] != ([1, 2] if halfline else [2, 2] if reciprocal else [2])
            or row["source_ref"] != description["source_ref"]
            or row["expression_ast"] != root[2]
            or not isinstance(condition, sp.GreaterThan) or condition.rhs != 0):
        raise ValueError("domain.parameter_condition_source_mismatch")
    if reciprocal:
        denominator_root = description["expression_ast"][2]
        radial = rows[1] if halfline else row
        if halfline and (radial["kind"] != "radicand_nonnegative" or radial["ast_path"] != [2, 2]
                         or radial["source_ref"] != description["source_ref"]
                         or radial["expression_ast"] != denominator_root[2]
                         or not isinstance(radial["condition"], sp.GreaterThan) or radial["condition"].rhs != 0):
            raise ValueError("domain.parameter_condition_source_mismatch")
        denominator = rows[-1]
        if (denominator["kind"] != "denominator_nonzero" or denominator["ast_path"] != [2]
                or denominator["source_ref"] != description["source_ref"]
                or denominator["expression_ast"] != denominator_root
                or denominator["condition"] != sp.Ne(sp.sqrt(radial["condition"].lhs, evaluate=False), 0, evaluate=False)):
            raise ValueError("domain.parameter_condition_source_mismatch")
    return reciprocal, condition


def parameter_domain(values):
    """Read the prescribed domain, and bind the checked denominator certificate."""
    from .function_domain import input_set

    description = values["description"]
    expected = input_set({**description, "input_domain_ast": description["prescribed_domain_ast"]})
    if values.get("domain") != expected:
        raise ValueError("domain.parameter_return_domain_mismatch" if values["phase"] == "parameter_return"
                         else "domain.parameter_universal_mismatch")
    if _halfline(description):
        proof = values.get("domain_equivalence")
        if (not isinstance(proof, dict) or proof.get("passed") is not True
                or proof.get("outside_excluded") is not True
                or proof.get("prescribed_domain") != expected
                or proof.get("denominator_domain") != expected
                or values.get("denominator_domain") != expected
                or proof.get("source_refs") != [description["source_ref"]]
                or proof.get("condition_ids") != ["c1", "c2", "c3"]
                or proof.get("denominator_condition_ids") != ["c2", "c3"]
                or proof.get("denominator_ast_path") != [2]
                or proof.get("radicand_ast_path") != [2, 2]
                or proof.get("outside_domain") != sp.Complement(sp.S.Reals, expected)):
            raise ValueError("domain.parameter_denominator_certificate_mismatch")
    elif expected != sp.S.Reals:
        raise ValueError("domain.parameter_return_domain_mismatch")
    return expected


def parameter_view(values):
    """Project original restrictions and a checked equivalent universal problem."""
    description = values["description"]
    _parameter_root(description)
    halfline = _halfline(description)
    phase = values["phase"]
    if phase != "parameter_conditions":
        domain_value = parameter_domain(values)
        domain = r"D_{" + description["function_name"] + "}=" + latex(domain_value)
    if phase == "parameter_return":
        if not isinstance(values.get("candidate_set"), sp.Set):
            raise ValueError("domain.parameter_return_set_required")
        method_label = load_nodes()[values["borrowed_method"]]["label"]
        parameter, answer = latex(values["parameter"]), latex(values["candidate_set"])
        return {
            "domain_explanation": (
                rf"{method_label}得到 ${parameter}\in {answer}$。"
                rf"回到原题：这些参数恰好使 ${domain}$ 成立。"
            ),
            "domain_lines": [{"label": "参数范围", "math": rf"{parameter}\in {answer}"},
                             {"label": "原题目标", "math": domain}],
        }
    rows = values["constraints"]
    reciprocal, condition = parameter_condition_rows(description, rows)
    expression, relation = description["expression_latex"], latex(condition)
    if phase == "parameter_conditions":
        if reciprocal:
            combined = r"\quad\text{且}\quad ".join(latex(row["condition"]) for row in rows)
            explanation = (
                "分子根号与分母根号都要求各自被开方数非负，分母还必须非零；三条限制须同时保留。"
                if halfline else
                rf"根号要求 ${relation}$，分母还要求 ${latex(rows[1]['condition'])}$；两条限制须同时保留。"
            )
            return {"domain_explanation": rf"原式为 ${expression}$。" + explanation,
                    "domain_lines": [{"label": "原式", "math": expression},
                                     {"label": "同时满足的原始条件", "math": combined}]}
        return {
            "domain_explanation": rf"原式为 ${expression}$。平方根有意义要求被开方数非负，因此须有 ${relation}$。",
            "domain_lines": [{"label": "原式", "math": expression},
                             {"label": "有意义的条件", "math": relation}],
        }
    strict = reciprocal and not halfline
    reduced = sp.Gt(condition.lhs, 0, evaluate=False) if strict else condition
    if (phase not in ("parameter_universal", "parameter_borrow") or values["quantifier"] != "∀"
            or values["relation"] != reduced or values["universal_statement"] != reduced
            or values.get("strict") is not strict or str(values["x"]) != description["variable"]):
        raise ValueError("domain.parameter_universal_mismatch")
    if halfline:
        proof, radial = values["domain_equivalence"], rows[1]["condition"].lhs
        if (proof.get("inside_condition") != reduced
                or proof.get("denominator_condition") != sp.Gt(radial, 0, evaluate=False)
                or proof.get("outside_condition") != sp.Le(radial, 0, evaluate=False)):
            raise ValueError("domain.parameter_denominator_certificate_mismatch")
    relation, variable = latex(reduced), latex(values["x"])
    universal = rf"\forall {variable}\in{latex(domain_value)},\quad {relation}"
    if phase == "parameter_borrow":
        borrowed = values.get("borrowed_method")
        nodes = load_nodes()
        if not isinstance(borrowed, str) or borrowed not in nodes:
            raise ValueError("domain.parameter_borrow_method_required")
        method_label = nodes[borrowed]["label"]
        return {
            "domain_explanation": (rf"当前子问题是 ${universal}$。"
                                   rf"在题给范围内求恒成立的参数，可借用{method_label}。"),
            "domain_lines": [{"label": "恒成立子问题", "math": universal},
                             {"label": "借用方法", "math": rf"\text{{{method_label}}}"}],
        }
    if halfline:
        denominator = latex(values["domain_equivalence"]["denominator_condition"])
        outside = latex(values["domain_equivalence"]["outside_domain"])
        explanation = (
            rf"分母的两条限制合为 ${denominator}$，其解集恰好是 ${latex(domain_value)}$。"
            rf"在 ${outside}$ 内，分母根号无意义或分母为零，原式自动被排除。"
            rf"因此只需保证域内每一个输入都使分子根号有意义，即 ${universal}$；无需要求域外的分子非负。"
        )
    else:
        explanation = (
            (rf"根号要求 ${latex(condition)}$，分母要求 ${latex(rows[1]['condition'])}$，合起来是 ${relation}$。"
             if reciprocal else "")
            + rf"定义域恰为全体实数，意味着每一个实数 ${variable}$ 都使原式有意义。"
            + rf"因此 ${domain}$ 等价于恒成立问题 ${universal}$。"
        )
    return {"domain_explanation": explanation,
            "domain_lines": [{"label": "已知定义域", "math": domain},
                             {"label": "等价的恒成立问题", "math": universal}]}


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
