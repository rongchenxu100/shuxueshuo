"""Run stage two on a student's stage-one result and word it for the problem page.

Every mathematical judgement comes from stage two (types, D1 fragments, D2
roles) or from known stage-one feature values. This module only chooses the
quoted spans and fills sentence templates; a row whose features are not known
is left out rather than guessed.
"""

import json
import re
from functools import cache
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_two.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result

from .identity import IdentityUnavailable, build_identity
from .proposition import transformation
from .walk import walk

NODES = ROOT / "site/data/knowledge-next/nodes"
RESULT = "stage-two-result.json"
INEQUALITIES = {"<", "<=", ">", ">="}
BREAKS = re.compile(r"[，,。；;：:]")


def stage_one_result(result, problem_id):
    """The stage-two input for a student upload: no gold, so no evaluation claim."""
    value = {
        "contract": "graph-stage-one-result/v2",
        "run_id": problem_id,
        "candidate": result.get("candidate"),
        "features": result.get("features", []),
        "statuses": {
            "extraction": result.get("status"),
            "source_reviewed": result.get("source_reviewed", False),
            "features": result.get("features_ok", False),
            "human_review": "pending",
            "admission": "student_upload",
        },
    }
    if (statement := public_problem_text(result)) is not None:
        # Bind the reviewed display projection to the same immutable input as
        # the mathematics so static export never reads an unbound side file.
        value["public_statement"] = statement
    return value


def public_problem_text(result):
    """Reuse the verified public formatter, keeping source text for D1 offsets."""
    try:
        return build_identity(result)["statement"]
    except IdentityUnavailable:
        # Legacy/private mathematical inputs may have no public projection.
        return None


def attempts(directory):
    return sorted(Path(directory).glob("stage-two-*"), key=lambda p: int(p.name.rsplit("-", 1)[1]))


def run_stage_two(directory, result, *, provider, unsupported_root):
    """Each run gets a fresh ``stage-two-<n>`` directory; a retry never overwrites history."""
    directory = Path(directory)
    number = len(attempts(directory)) + 1
    return run_result(stage_one_result(result, directory.name), directory / f"stage-two-{number}",
                      provider=provider, verify=True, admission="student_upload",
                      source_image=directory / "question.png", unsupported_root=unsupported_root)


def latest(directory):
    runs = attempts(directory)
    if not runs or not (runs[-1] / RESULT).is_file():
        return None
    return json.loads((runs[-1] / RESULT).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- presentation


@cache
def _node(node_id):
    path = NODES / f"{node_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def knowledge_label(ref):
    node_id, _, entry_id = ref.partition("#")
    node = _node(node_id)
    entry = next((e for e in node.get("entries", []) if e.get("id") == entry_id), {})
    return {"ref": ref, "node": node_id, "label": node.get("label", node_id), "title": entry.get("title", "")}


def present_lesson(stage_two, features, text, problem_id="problem", *, candidate=None, display_text=None):
    """``lesson`` for GET status: one section per goal, in authored order.

    A resolved goal also carries ``walk``: its graph-walk bundle and AI replay.
    """
    if stage_two["status"] == "input_error":
        return {"status": "input_error", "goals": []}
    by_target = {}
    for row in features:
        by_target.setdefault(row["target_ref"], {})[row["feature_id"]] = row
    goals = [_goal(goal, by_target.get(goal["target_ref"], {}), text, candidate) for goal in stage_two["goals"]]
    seen = {}
    for goal in goals:
        for row in goal["d1"]["rows"]:
            if row["signature"] in seen:
                row["same_as"] = seen[row["signature"]]
            else:
                seen[row["signature"]] = row["id"]
    for goal in goals:
        goal["walk"] = walk(goal, text if display_text is None else display_text, problem_id)
    return {"status": stage_two["status"], "goals": goals}


def _goal(goal, features, text, candidate=None):
    section = {"target_ref": goal["target_ref"], "scope": goal["scope"], "label": goal["label"],
               "status": goal["status"], "primary": goal.get("primary"),
               "supported": goal.get("supported", [])}
    if goal["status"] != "resolved":
        section["d1"] = {"rows": [], "summary": ""}
        return section
    known = {key: row["value"] for key, row in features.items() if row.get("status") == "known"}
    section["d1"] = d1_rows(goal["target_ref"], goal["d1"]["fragments"], known, text, candidate=candidate)
    if known.get("goal", {}).get("kind") == "compare_functions":
        comparison = known.get("function_comparison", {})
        section["option_workspaces"] = [
            {key: option[key] for key in ("option_id", "label", "text")}
            for option in comparison.get("options", [])
        ]
        diagnostics = goal["d1"].get("diagnostics", [])
        if diagnostics:
            section["d1"]["diagnostics"] = diagnostics
    if known.get("goal", {}).get("kind") in ("find_domain", "match_domain"):
        # The domain locator proves the original arithmetic tree separately
        # from the generic polynomial reader (which can reject valid \frac).
        diagnostics = [item for item in goal["d1"].get("diagnostics", [])
                       if item["code"] in {"d1.scope_or_features_ambiguous",
                                           "d1.function_definition_not_uniquely_located"}]
        if diagnostics:
            section["d1"]["diagnostics"] = diagnostics
    source_goal = known.get("goal", {})
    if (source_goal.get("kind") in ('find_monotonic_intervals', 'prove_monotonicity_on_interval', 'select_function_graph', 'draw_function_graph', 'solve_graph_inequality', 'find_function_formula', 'select_range_domain', 'find_extrema_expression', "find_translation_range", "find_abstract_domain", "find_abstract_domain_parameter", "find_abstract_range", "find_value", "check_constant", "finite_sum")
            or source_goal.get("kind") == "find_range" and "object" in source_goal
            or known.get('piecewise_equation', {}).get('structure_supported')
            or known.get('piecewise_inequality', {}).get('structure_supported')
            or known.get('monotonicity_inequality', {}).get('structure_supported')):
        diagnostics = goal["d1"].get("diagnostics", [])
        if diagnostics:
            section["d1"]["diagnostics"] = diagnostics
    section["d2"] = d2_options(goal)
    section["knowledge"] = [knowledge_label(item["ref"]) for item in goal["knowledge"]["items"]]
    section["links"] = goal["knowledge"]["links"]
    return section


def _closing(text, open_at):
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _calls(text, name, render):
    """Rewrite name(...) calls, innermost-safe, matching the page's calls() helper."""
    out, index, needle = [], 0, f"{name}("
    while True:
        found, cursor = -1, index
        while True:
            at = text.find(needle, cursor)
            if at < 0:
                break
            # A digit before the name is a coefficient (2*sqrt(2) after * is dropped), not part of it.
            if at == 0 or not (text[at - 1].isalpha() or text[at - 1] == "_"):
                found = at
                break
            cursor = at + 1
        if found < 0:
            out.append(text[index:])
            return "".join(out)
        open_at = found + len(name)
        close = _closing(text, open_at)
        if close < 0:
            out.append(text[index:])
            return "".join(out)
        arg = text[open_at + 1:close].strip()
        out.append(text[index:found])
        out.append(render(_calls(arg, name, render)))
        index = close + 1


def _lone_fractions(text):
    """Turn a lone digit/digit into \\frac; leave any slash that sits in a longer division chain."""

    def replace(match):
        before, after = text[:match.start()], text[match.end():]
        if re.search(r"[\w.^]$", before) or re.match(r"[\w.^]", after or ""):
            return match.group(0)
        left = len(before) - 1
        while left >= 0 and before[left] in "+-":
            left -= 1
        if left >= 0 and before[left] == "/":
            return match.group(0)
        right = 0
        while right < len(after) and after[right] in "+-":
            right += 1
        if right < len(after) and after[right] == "/":
            return match.group(0)
        return rf"\frac{{{match.group(1)}}}{{{match.group(2)}}}"

    return re.sub(r"(\d+)/(\d+)", replace, text)


def _powers(text):
    """x^(1/3) → x^{1/3}, x^12 → x^{12}: TeX only raises the next token."""
    out, index = [], 0
    while (caret := text.find("^(", index)) >= 0:
        close = _closing(text, caret + 1)
        if close < 0:
            break
        out.append(text[index:caret] + "^{" + _powers(text[caret + 2:close]) + "}")
        index = close + 1
    return re.sub(r"\^(\d+(?:\.\d+)?)", r"^{\1}", "".join(out) + text[index:])


def tex(value):
    # Normalized features use SymPy strings: ** is a power. Keep * until the calls are rewritten,
    # since it is the only boundary between a*sqrt(...) and a name like asqrt.
    value = str(value).replace(" ", "").replace("**", "^")
    for a, b in (("ℝ", r"\mathbb R"), ("+∞", r"+\infty"), ("∞", r"\infty"), ("<=", r"\le "),
                 (">=", r"\ge "), ("≤", r"\le "), ("≥", r"\ge ")):
        value = value.replace(a, b)
    value = _calls(value, "Abs", lambda arg: rf"\left|{arg}\right|")
    value = _calls(value, "abs", lambda arg: rf"\left|{arg}\right|")
    value = _calls(value, "sqrt", lambda arg: rf"\sqrt{{{arg}}}")
    value = _calls(value, "√", lambda arg: rf"\sqrt{{{arg}}}")
    value = re.sub(r"√(\d+(?:\.\d+)?)", r"\\sqrt{\1}", value)
    value = re.sub(r"(?<![A-Za-z\\])pi(?![A-Za-z])", r"\\pi ", value)
    value = re.sub(r"(?<![A-Za-z\\])oo(?![A-Za-z])", r"\\infty ", value)
    value = re.sub(r"(\d)\*(?=\d)", r"\1\\times ", value)
    value = re.sub(r"([})])\*(?=\d)", r"\1\\cdot ", value).replace("*", "")
    return _lone_fractions(_powers(value))


def _math(text):
    marks = [m.start() for m in re.finditer(r"(?<!\\)\$", text)]
    return list(zip(marks[0::2], marks[1::2]))


def _spans(fragments, text):
    """The quoted source span; it never cuts through a $...$ formula.

    A span wholly inside one formula is quoted as its own formula, so two rows
    from the same formula (``$∀x<0，x^2+ax+2≥0$``) keep distinct quotes.
    """
    start = min(fragment["start"] for fragment in fragments)
    end = max(fragment["end"] for fragment in fragments)
    if not text:
        return {"start": start, "end": end, "text": fragments[0]["text"]}
    regions = _math(text)
    for left, right in regions:
        if left < start and end <= right:
            return {"start": start, "end": end, "text": f"${text[start:end].strip()}$"}
    for left, right in regions:
        if left < start <= right:
            start = left
        if left <= end - 1 < right:
            end = right + 1
    return {"start": start, "end": end, "text": text[start:end]}


def _groups(fragments, text):
    """Adjacent quantifier/domain fragments in one clause form one quoted span."""
    groups, current = [], []
    for fragment in sorted(fragments, key=lambda f: f["start"]):
        joins = (current and fragment["fragment_kind"] in ("quantifier", "domain")
                 and current[-1]["fragment_kind"] in ("quantifier", "domain")
                 and not BREAKS.search(text[current[-1]["end"]:fragment["start"]] if text else ""))
        if joins:
            current.append(fragment)
            continue
        if current:
            groups.append(current)
        current = [fragment]
    return groups + ([current] if current else [])


def _option(text, violates=None, feedback=""):
    return {"text": text, "correct": violates is None, "violates": violates, "feedback": feedback}


def _shuffle(row_id, options):
    """Stable order per row, so the correct answer is not always first."""
    keyed = sorted(options, key=lambda o: sha256((row_id + o["text"]).encode()).hexdigest())
    for index, option in enumerate(keyed):
        option["id"] = f"{row_id}:o{index}"
    return keyed


def _relation_case(known):
    bound, goal, lead = known.get("degree_in_bound"), known.get("degree_in_goal"), known.get("leading_coeff_in_bound")
    if not bound or bound.get("degree") is None:
        return None
    if bound["degree"] == 2:
        if bound.get("degree_kind") == "exact" or (lead and lead.get("may_be_zero") is False):
            return "quadratic"
        return "leading" if lead else None
    if bound["degree"] <= 1 and goal and goal.get("degree") == 2:
        return "swap"
    return None


def _quantifier_row(q, v, domain):
    real = domain.get("expression") == "ℝ"
    d = tex(domain.get("expression", ""))
    within = "" if real else f"${d}$ 里"
    if q == "∀":
        correct = f"所有实数 ${v}$ 都要满足" if real else f"${d}$ 里的每一个 ${v}$ 都要满足"
        options = [
            _option(correct),
            _option(f"{within}找到一个 ${v}$ 满足就行", "quantifier",
                    f"“任意”“恒成立”要求每一个 ${v}$ 都满足，不是找到一个就行。"),
            _option(f"只要 ${v}=0$ 时成立", "quantifier", f"不能只看一个值，每一个 ${v}$ 都要满足。") if real else
            _option(f"所有实数 ${v}$ 都要满足", "domain", f"${v}$ 只在 ${d}$ 里取值，不是全体实数。"),
        ]
        summary = f"对所有实数 ${v}$ 都成立" if real else f"对 ${d}$ 里每一个 ${v}$ 都成立"
    else:
        correct = f"能找到一个实数 ${v}$ 满足就行" if real else f"在 ${d}$ 里能找到一个 ${v}$ 满足就行"
        options = [
            _option(correct),
            _option(f"所有实数 ${v}$ 都要满足" if real else f"${d}$ 里的每一个 ${v}$ 都要满足", "quantifier",
                    f"“存在”“有解”只要求能找到一个 ${v}$，不要求每一个都满足。"),
            _option(f"只能取 ${v}=0$", "domain", f"${v}$ 可以是任意一个实数，不只是 $0$。") if real else
            _option(f"在全体实数里找到一个 ${v}$ 就行", "domain", f"${v}$ 只在 ${d}$ 里取值，不是全体实数。"),
        ]
        summary = f"至少对一个实数 ${v}$ 成立" if real else f"在 ${d}$ 里至少对一个 ${v}$ 成立"
    return options, summary


def _relation_text(relation):
    return f"${tex(relation['lhs'])}{tex(relation['operator'])}{tex(relation['rhs'])}$"


def _source_quantifier_row(transform, v, domain):
    options, summary = _quantifier_row(transform["source_quantifier"], v, domain)
    correct = options[0]["text"].replace("满足", "满足原关系")
    explanation = f"原命题要求：{correct}；“为假”说明这个命题不成立。"
    for option in options:
        reading = option["text"].replace("满足", "满足原关系")
        option["text"] = f"原命题要求：{reading}；题目说明这个命题为假"
        if option["feedback"]:
            option["feedback"] = explanation
    options.append(_option(f"原命题要求：{correct}；题目说明这个命题为真", "truth", explanation))
    return options, summary


def _relation_row(case, v, p, relation, bound_degree=None):
    noun = "不等式"
    equation = (_option(f"关于 ${p}$ 的方程", "relation", "题中是不等号，这是不等式，不是方程。")
                if relation.get("operator") in INEQUALITIES else None)
    if case == "quadratic":
        options = [_option(f"关于 ${v}$ 的一元二次{noun}，${p}$ 看作常数"),
                   _option(f"关于 ${v}$ 的一元一次{noun}", "degree_in_bound", f"${v}$ 的最高次数是 $2$。")]
        summary = f"关于 ${v}$ 的二次{noun}"
    elif case == "leading":
        options = [_option(f"关于 ${v}$ 的{noun}，二次项系数含 ${p}$，可能为 $0$"),
                   _option(f"关于 ${v}$ 的一元二次{noun}，二次项系数不为 $0$", "leading_coeff_in_bound",
                           f"二次项系数含 ${p}$，可能为 $0$，这时就不是二次{noun}了。")]
        summary = f"关于 ${v}$ 的{noun}（二次项系数可能为 $0$）"
    elif bound_degree == 0:
        # Swap with degree 0: the quantified variable cancels; calling it linear would be wrong.
        options = [_option(f"关于 ${v}$ 是常数（与 ${v}$ 无关），关于 ${p}$ 是二次式"),
                   _option(f"关于 ${v}$ 的一元二次{noun}", "degree_in_bound",
                           f"化简后式子与 ${v}$ 无关，并不是关于 ${v}$ 的二次{noun}。")]
        summary = f"与 ${v}$ 无关的{noun}"
    else:
        options = [_option(f"关于 ${v}$ 是一次式，关于 ${p}$ 是二次式"),
                   _option(f"关于 ${v}$ 的一元二次{noun}", "degree_in_bound",
                           f"把 ${p}$ 看作常数，式子关于 ${v}$ 只是一次的。")]
        summary = f"关于 ${v}$ 是一次的{noun}"
    return options + ([equation] if equation else []), summary


def _goal_row(case, v, s, kind):
    param = case != "swap"
    if kind in ("find_minimum", "find_maximum"):
        noun = "最小值" if kind == "find_minimum" else "最大值"
        opposite = "最大值" if kind == "find_minimum" else "最小值"
        summary = f"求{'参数' if param else ''} ${s}$ 的{noun}"
        options = [
            _option(summary),
            _option(f"求 ${s}$ 的{opposite}", "goal", f"题目要的是 ${s}$ 的{noun}。"),
            _option(f"求 ${v}$ 的{noun}", "goal",
                    f"题目要的是 ${s}$ 的{noun}；${v}$ 是在范围里变动的量，不用求它的{noun}。"),
        ]
        return options, summary
    options = [_option(f"求参数 ${s}$ 能取哪些值" if param else f"求 ${s}$ 能取哪些值"),
               _option(f"解出 ${v}$ 的取值范围" if param else f"求 ${v}$ 的取值范围", "goal",
                       f"题目要的是 ${s}$ 的范围；${v}$ 是在范围里变动的量，不用求它。")]
    return options, f"求{'参数' if param else ''} ${s}$ 的取值范围"


def d1_rows(target, fragments, known, text, *, candidate=None):
    """Rows of the reading checklist; see docs/student-problem-search-design.md 3.7."""
    if known.get('piecewise_modeling', {}).get('structure_supported'):
        return _piecewise_modeling_d1_rows(target, fragments, known, text)
    if known.get('piecewise_inequality', {}).get('structure_supported'):
        return _piecewise_inequality_d1_rows(target, fragments, known, text)
    if known.get('monotonicity_inequality', {}).get('structure_supported'):
        return _monotonicity_inequality_d1_rows(target, fragments, known, text)
    if known.get('piecewise_equation', {}).get('structure_supported'):
        return _piecewise_equation_d1_rows(target, fragments, known, text)
    if known.get('function_extremum', {}).get('structure_supported'):
        return _extremum_d1_rows(target, fragments, known, text)
    if known.get('function_monotonicity', {}).get('structure_supported'):
        return _monotonicity_d1_rows(target, fragments, known, text)
    if known.get('function_graph', {}).get('structure_supported'):
        return _graph_d1_rows(target, fragments, known, text)
    if known.get('function_formula', {}).get('structure_supported'):
        return _formula_d1_rows(target, fragments, known, text)
    if known.get('translation_range', {}).get('structure_supported'):
        return _range_d1_rows(target, fragments, {**known, 'function_range': known['translation_range']}, text)
    if known.get('function_range', {}).get('structure_supported'):
        return _range_d1_rows(target, fragments, known, text)
    if known.get('function_evaluation', {}).get('structure_supported'):
        return _evaluation_d1_rows(target, fragments, known, text)
    if known.get("goal", {}).get("kind") == "compare_functions":
        return _comparison_d1_rows(target, fragments, known, text)
    if known.get("goal", {}).get("kind") == "find_domain":
        return _domain_d1_rows(target, fragments, known, text, candidate=candidate)
    if known.get("goal", {}).get("kind") == "match_domain":
        return _match_domain_d1_rows(target, fragments, known, text, candidate=candidate)
    if known.get("goal", {}).get("kind") in ("find_abstract_domain", "find_abstract_domain_parameter", "find_abstract_range"):
        return _abstract_domain_d1_rows(target, fragments, known, text, candidate=candidate)
    transform, diagnostics = transformation(target, fragments, known, tex, text=text, candidate=candidate)
    extra = {"transformation": transform} if transform else {}
    if diagnostics:
        extra["diagnostics"] = diagnostics
    bound, goal = known.get("bound_vars") or [], known.get("goal") or {}
    if (len(bound) != 1 or goal.get("kind") not in ("find_range", "find_minimum", "find_maximum")
            or goal.get("symbol") in (None, bound[0])):
        return {"rows": [], "summary": "", **extra}
    v, s = bound[0], goal["symbol"]
    case = _relation_case(known)
    groups = _groups(fragments, text)
    rows, pieces = [], {}

    def add(kind, used, options, summary, values):
        row_id = f"{target}:{kind}"
        spans = [_spans(group, text) for group in used]
        signature = sha256(json.dumps([kind, [(x["start"], x["end"]) for x in spans], values],
                                      sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        refs = list(dict.fromkeys(r for group in used for f in group for r in f["knowledge_refs"]))
        rows.append({"id": row_id, "kind": kind, "quote": spans,
                     "fragment_ids": [f["id"] for group in used for f in group],
                     "knowledge_refs": refs, "options": _shuffle(row_id, options), "signature": signature})
        pieces[kind] = summary

    quantified = next((g for g in groups if any(f["fragment_kind"] == "quantifier"
                                              and (not transform or f.get("reading_transform")) for f in g)), None)
    if quantified and not diagnostics and known.get("quantifier") in ("∀", "∃") and known.get("domain"):
        used = [quantified]
        if not any(f["fragment_kind"] == "domain" for f in quantified):
            domain_group = next((g for g in groups if all(f["fragment_kind"] == "domain" for f in g)), None)
            used = sorted([quantified] + ([domain_group] if domain_group else []), key=lambda g: g[0]["start"])
        values = [known["quantifier"], v, known["domain"]]
        if transform:
            options, summary = _source_quantifier_row(transform, v, known["domain"])
            values += [transform["signature"]]
        else:
            options, summary = _quantifier_row(known["quantifier"], v, known["domain"])
        add("quantifier", used, options, summary, values)
    relation = next((g for g in groups if g[0]["fragment_kind"] == "relation"
                     and (not transform or g[0].get("reading_transform"))), None)
    if relation and not diagnostics and case and known.get("relation", {}).get("operator") in INEQUALITIES:
        bound_degree = (known.get("degree_in_bound") or {}).get("degree")
        reading_relation = transform["source_relation"] if transform else known["relation"]
        options, summary = _relation_row(case, v, s, reading_relation, bound_degree)
        values = [case, v, s, reading_relation, bound_degree]
        if transform:
            expression = _relation_text(reading_relation)
            for option in options:
                option["text"] = f"原命题中的关系为 {expression}；{option['text']}"
                if option["feedback"]:
                    option["feedback"] = f"这里识别的是原命题中的关系 {expression}。{option['feedback']}"
            values.append(transform["signature"])
        add("relation", [relation], options, summary, values)
    target_group = next((g for g in groups if g[0]["fragment_kind"] == "goal"), None)
    if target_group and case:
        options, summary = _goal_row(case, v, s, goal["kind"])
        values = [case, v, s] + ([] if goal["kind"] == "find_range" else [goal["kind"]])
        add("goal", [target_group], options, summary, values)
    summary = ""
    if len(pieces) == 3:
        summary = (f"合起来：{transform['source_meaning']}" if transform else
                   f"合起来：{pieces['relation']}{pieces['quantifier']}，{pieces['goal']}。")
    return {"rows": rows, "summary": summary, **extra}


def _extremum_d1_rows(target, fragments, known, text):
    """T2 审题：先分清直接求最值／量词比较求参／指定最值求参，再进入题型。"""
    selected = [row for row in fragments if row['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    desc = known['function_extremum']
    task = desc['task']
    row_id = f'{target}:goal'
    spans = [_spans([row], text) for row in selected]
    if task == 'direct':
        quantity = '最大值' if desc.get('quantity') == 'maximum' else '最小值'
        correct = f'求函数在给定区间上的{quantity}'
        wrong = '求函数的单调区间'
        feedback = f'题目要的是{quantity}，不是完整的增减区间。'
        question = '这一问需要做什么？'
    elif task == 'quantified':
        parameter = desc.get('parameter') or 'a'
        correct = f'比较两边取值，求参数 ${parameter}$ 的取值范围'
        wrong = '只求出某一边的最值就结束'
        feedback = f'最值／值域是手段；原题还要求出 ${parameter}$ 的范围。'
        question = '这一问最终要求什么？'
    elif task == 'specified':
        parameter = desc.get('parameter') or 'a'
        correct = f'在指定点已是最值的条件下，求参数 ${parameter}$ 的取值范围'
        wrong = '只算出指定点的函数值就结束'
        feedback = f'指定点的函数值是转化条件；还要求出 ${parameter}$ 的范围。'
        question = '这一问最终要求什么？'
    else:
        return {'rows': [], 'summary': ''}
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [row['id'] for row in selected],
           'knowledge_refs': ['function-range-extrema#extrema'], 'source_refs': [target],
           'options': _shuffle(row_id, [_option(correct), _option(wrong, 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, desc], sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice', 'question': question,
            'feedback': feedback, 'summary': correct}


def _monotonicity_d1_rows(target, fragments, known, text):
    selected = [row for row in fragments if row['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    row_id = f'{target}:goal'
    spans = [_spans([row], text) for row in selected]
    goal = known['function_monotonicity']['source']
    name = {'increasing': '递增区间', 'decreasing': '递减区间', 'both': '单调区间'}[goal['direction']]
    correct = '求函数的'+name if goal['kind'] == 'find_monotonic_intervals' else '证明给定区间内的单调性'
    feedback = '题目要求判断增减，不能把已知表达式当成已知单调性。'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [row['id'] for row in selected],
           'knowledge_refs': ['function-monotonicity#definition'], 'source_refs': [target],
           'options': _shuffle(row_id, [_option(correct), _option('求函数的值域', 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, known['function_monotonicity']], sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice', 'question': '这一问需要做什么？',
            'feedback': feedback, 'summary': correct}


def _graph_d1_rows(target, fragments, known, text):
    selected = [row for row in fragments if row['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    row_id = f'{target}:goal'
    spans = [_spans([row], text) for row in selected]
    correct = '根据解析式，选择对应的图像'
    feedback = '题目给出了函数解析式，要核对原选项中的图像。'
    kind = known['function_graph']['source']['kind']
    if 'source_graph' in known['function_graph']['source']:
        correct, feedback = '根据原图，选择变换后的图像', '题目只给了原图，先判断点的位置和图像方向怎样变化。'
    if 'transformations' in known['function_graph']['source']:
        correct, feedback = '按要求平移图像，再选择对应的图像', '题目给了原解析式和平移要求，要判断移动后的图像。'
    if kind == 'draw_function_graph':
        correct, feedback = '根据解析式画出函数图像', '按绝对值内的正负分段，画出各段图像。'
    elif kind == 'solve_graph_inequality':
        correct, feedback = '结合图像求不等式的解集', '找到图像与水平线的交点，再判断区间和端点。'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [row['id'] for row in selected],
           'knowledge_refs': ['function-representations#graph'], 'source_refs': [target],
           'options': _shuffle(row_id, [_option(correct), _option('根据图像求解析式', 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, known['function_graph']], sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice', 'question': '这一问需要做什么？',
            'feedback': feedback, 'summary': correct}


def _formula_d1_rows(target, fragments, known, text):
    selected = [row for row in fragments if row['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    row_id = f'{target}:goal'
    spans = [_spans([row], text) for row in selected]
    correct = '求出函数解析式，并写出适用范围'
    wrong = '只求出函数解析式'
    feedback = '还要写明求出的解析式在哪些输入上成立。'
    if known['function_formula']['kind'] == 'find_value':
        correct = '求出给定输入对应的函数值'
        wrong = '先求出整个函数的解析式'
        feedback = '这一问只求一个函数值，可以直接在题给关系中代入合适的数。'
    if known['function_formula'].get('function_type'):
        if known['function_formula']['kind'] == 'find_value':
            wrong = '只写出函数解析式'
            feedback = '题目只问函数值。先利用函数类型和已知关系，再计算这个值。'
        elif known['function_formula']['kind'] == 'find_range':
            correct, wrong = '求满足不等式的自变量范围', '只写出函数解析式'
            feedback = '求出解析式后，还要解原题的不等式。'
        else:
            correct, wrong = '求出所有符合条件的函数解析式', '找到一个解析式就结束'
            feedback = '可能有多个解析式，必须保留所有符合题意的结果。'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [row['id'] for row in selected],
           'knowledge_refs': ['function-concept#elements'], 'source_refs': [target],
           'options': _shuffle(row_id, [_option(correct),
                       _option(wrong, 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, known['function_formula']], sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': '这一问需要求什么？',
            'feedback': feedback, 'summary': correct}


def _range_d1_rows(target, fragments, known, text):
    selected = [row for row in fragments if row['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    row_id = f'{target}:goal'
    spans = [_spans([row], text) for row in selected]
    feedback = '定义域是输入的取值范围；值域是在这个范围内得到的全部函数值组成的集合。'
    task = known['function_range'].get('range_task', {})
    correct, wrong = '求给定输入范围内，全部函数值组成的集合', '求自变量的取值范围'
    question, summary = '题目要求求值域，需要确定什么？', '先确定定义域，再求全部实际能取到的函数值。'
    if task.get('kind') == 'select_range_domain':
        requested = '可能' if task['select_relation'] == 'matches' else '不可能'
        correct = f'逐项核对候选定义域对应的完整值域，选择“{requested}”的端点组合'
        wrong = '只比较区间两个端点的函数值，就能确定值域'
        feedback = '区间内的顶点也可能取得最值；还要核对完整值域与题给范围是否一致。'
        question, summary = '题目给出了值域，要求怎样判断候选定义域？', correct
    elif task.get('kind') == 'find_extrema_expression':
        correct = f'确定题设最值，再代入计算 ${task["expression"]}$'
        wrong = '只写出函数的值域区间，不再计算所求式'
        feedback = '值域帮助确定最值；还要确认最值能取到，并计算题目要求的算式。'
        question, summary = '求出值域之后，还需要完成什么？', correct
    if request := known['function_range'].get('answer_request'):
        from ..graph_lesson.stage_two.range_task_surface import QUANTITY_WORDS
        kind = request['kind']
        if kind == 'expression':
            roles = '、'.join(f'${row["symbol"]}$ 表示{QUANTITY_WORDS[row["quantity"]]}' for row in request['bindings'])
            correct = f'{roles}，确定这些量后计算 ${tex(request["expression"])}$'
        elif kind == 'extremum':
            correct = f'从完整值域确定{QUANTITY_WORDS[request["quantity"]]}'
        elif kind == 'compare_set':
            relation = '等于' if request['relation'] == 'equal' else '不等于'
            correct = f'判断完整值域是否{relation} ${tex(request["expected"])}$'
        if kind != 'identity':
            wrong = '只写出值域区间，不再回答原题的提问'
            feedback = '先确定全部函数值，再根据题目的要求提取、计算或判断；最大值和最小值还必须能取到。'
            question, summary = '确定值域后，原题要求怎样使用结果？', correct
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [row['id'] for row in selected],
           'knowledge_refs': ['function-concept#elements'], 'source_refs': [target],
           'options': _shuffle(row_id, [
               _option(correct),
               _option(wrong, 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, known['function_range']], sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': question, 'feedback': feedback, 'summary': summary}


def _piecewise_inequality_d1_rows(target, fragments, known, text):
    description = known['piecewise_inequality']
    selected = [fragment for fragment in fragments if fragment['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    variable = description['variable']
    row_id = f'{target}:goal'
    spans = [_spans([fragment], text) for fragment in selected]
    feedback = '题目要求的是使不等式成立的全部输入；先算比较值，再逐段判断。'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [fragment['id'] for fragment in selected],
           'knowledge_refs': ['piecewise-function#inequality'], 'source_refs': [target],
           'options': _shuffle(row_id, [
               _option(f'求出满足题中不等式的全部 ${variable}$'),
               _option('只算出比较用的函数值就结束', 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, description], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': '题目给出了分段函数和一个不等式，需要求什么？',
            'feedback': feedback, 'summary': f'找出满足题中不等式的全部 ${variable}$，每个解都要符合所在段的范围。'}


def _monotonicity_inequality_d1_rows(target, fragments, known, text):
    description = known['monotonicity_inequality']
    selected = [fragment for fragment in fragments if fragment['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    variable = description['variable']
    function = description['function']
    row_id = f'{target}:goal'
    spans = [_spans([fragment], text) for fragment in selected]
    proved = description.get('mono_basis') == 'proved_monotonicity'
    feedback = (f'要先确认 ${function}$ 的严格单调性，再把函数值比较转成输入比较，求 ${variable}$ 的取值范围。'
                if proved else
                f'已知 ${function}$ 严格单调，把函数值比较转成输入比较，求 ${variable}$ 的取值范围。')
    correct = f'利用 ${function}$ 的严格单调性，求满足题中比较的全部 ${variable}$'
    wrong = '只比较两个函数值大小，不求自变量范围'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [fragment['id'] for fragment in selected],
           'knowledge_refs': ['function-monotonicity#inequality'], 'source_refs': [target],
           'options': _shuffle(row_id, [_option(correct), _option(wrong, 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, description], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': '这一问比较了同一个函数的两个函数值，需要求什么？',
            'feedback': feedback, 'summary': correct + '。'}


def _piecewise_modeling_d1_rows(target, fragments, known, text):
    description = known['piecewise_modeling']
    selected = [f for f in fragments if f['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    modeling = description['goal_ast']['kind'] == 'find_equation'
    correct = '写出总电费随用电量变化的分段关系式' if modeling else '已知电费，求符合计费规则的用电量'
    wrong = '把最高档单价乘以全部用电量' if modeling else '把题给电费当作用电量，代入算电费'
    feedback = '超出部分才使用新单价，前面各档仍按原单价计费。' if modeling else '题目给出的是电费，要求的是用电量，还要检查它是否属于对应档位。'
    spans = [_spans([f], text) for f in selected]
    row_id = f'{target}:goal'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [f['id'] for f in selected], 'knowledge_refs': ['piecewise-function#definition'],
           'source_refs': [target], 'options': _shuffle(row_id, [_option(correct), _option(wrong, 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, description], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': '这一问需要求什么？', 'feedback': feedback, 'summary': correct+'。'}


def _piecewise_equation_d1_rows(target, fragments, known, text):
    description = known['piecewise_equation']
    selected = [fragment for fragment in fragments if fragment['fragment_kind'] == 'goal']
    if not selected:
        return {'rows': [], 'summary': ''}
    variable = description['variable']
    row_id = f'{target}:goal'
    spans = [_spans([fragment], text) for fragment in selected]
    feedback = '题目给出了函数值，要反过来找出所有符合条件的自变量。'
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [fragment['id'] for fragment in selected],
           'knowledge_refs': ['piecewise-function#equation'], 'source_refs': [target],
           'options': _shuffle(row_id, [
               _option(f'求出满足题中等式的全部 ${variable}$'),
               _option('把题中给出的函数值当作自变量，代入求值', 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, description], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': '题目给出了分段函数及其函数值，需要求什么？',
            'feedback': feedback, 'summary': f'找出满足题中等式的全部 ${variable}$，每个解都要符合所在段的范围。'}


def _evaluation_d1_rows(target, fragments, known, text):
    """Read the current output task without computing or hinting its answer."""
    evaluation = known.get('function_evaluation') or {}
    selected = [fragment for fragment in fragments if fragment['fragment_kind'] == 'goal']
    if not evaluation.get('structure_supported') or not selected:
        return {'rows': [], 'summary': ''}
    kind = evaluation['kind']
    if kind == 'check_constant':
        correct = '判断整个表达式在合法输入范围内是否始终保持同一个值'
        opposite = '选一个输入算出函数值，就能确定它是否为定值'
        feedback = '一个输入只能得到一次结果；定值判断需要检查整个合法输入范围。'
        summary = '先按函数规则代入，再验证表达式是否在完整合法范围上恒定。'
    elif kind == 'finite_sum':
        correct = '把题中列出的各次函数值相加，重复出现的项分别计入'
        opposite = '找到一对函数值的和，就已经求出了整个和式'
        feedback = '配对只是整理过程；原和式的每一次出现都必须计入，还要处理剩余项。'
        summary = '按原和式逐项计数，可用已验证的配对关系整理，再合计全部项。'
    else:
        correct = (f'求出代入后的表达式，并注明自变量 ${evaluation["variable"]}$ 的取值范围'
                   if evaluation.get('variable_ref') else '把题目指定的输入代入对应函数，求出输出值')
        opposite = '收集函数在整个定义域上的所有输出，求出值域'
        feedback = '这里求的是给定输入对应的输出；值域才是全部输入产生的输出集合。'
        summary = '代入是把完整输入放进已有函数规则；复合函数从内向外依次代入。'
    row_id = f'{target}:goal'
    spans = [_spans([fragment], text) for fragment in selected]
    row = {'id': row_id, 'kind': 'goal', 'quote': spans,
           'fragment_ids': [fragment['id'] for fragment in selected],
           'knowledge_refs': list(dict.fromkeys(ref for fragment in selected for ref in fragment['knowledge_refs'])),
           'source_refs': [target],
           'options': _shuffle(row_id, [_option(correct), _option(opposite, 'goal', feedback)]),
           'signature': sha256(json.dumps([spans, evaluation], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}
    return {'rows': [row], 'givens': [], 'interaction': 'choice',
            'question': '本问要求处理 ' + '、'.join(span['text'] for span in spans) + '。需要完成什么任务？',
            'feedback': feedback, 'summary': summary}


def _comparison_d1_rows(target, fragments, known, text):
    """Understand the requested relation without revealing any option verdict."""
    comparison = known.get("function_comparison") or {}
    selected = [fragment for fragment in fragments if fragment["fragment_kind"] == "goal"]
    if not comparison.get("structure_supported") or not selected:
        return {"rows": [], "summary": ""}
    mode, relation = comparison["mode"], comparison["select_relation"]
    if mode == "pair":
        correct = "比较这两个函数的定义域和对应关系，判断是否为同一函数"
        opposite = "只比较表达式的外观，不需要检查定义域"
        feedback = "同一函数要求定义域相同，并且每个输入对应的输出都相同。"
    else:
        noun, other = ("不相同", "相同") if relation == "different" else ("相同", "不相同")
        correct = f"逐项判断，再选出表示{noun}函数的选项"
        opposite = f"逐项判断，再选出表示{other}函数的选项"
        feedback = f"再看题目要求：要选的是表示{noun}函数的选项。"
    row_id = f"{target}:goal"
    spans = [_spans([fragment], text) for fragment in selected]
    options = [_option(correct), _option(opposite, "goal", feedback)]
    row = {"id": row_id, "kind": "goal", "quote": spans,
           "fragment_ids": [fragment["id"] for fragment in selected],
           "knowledge_refs": list(dict.fromkeys(ref for fragment in selected for ref in fragment["knowledge_refs"])),
           "source_refs": list(dict.fromkeys(ref for fragment in selected for ref in fragment.get("source_refs", []))),
           "options": _shuffle(row_id, options),
           "signature": sha256(json.dumps([spans, comparison], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}
    return {"rows": [row], "givens": [], "interaction": "choice",
            "question": "题目要求我们判断并选出什么？" if mode != "pair" else "题目要求我们判断什么？",
            "feedback": feedback,
            "summary": "判断同一函数，要先比较定义域，再比较整个定义域上的对应关系。"}


def _domain_d1_rows(target, fragments, known, text, *, candidate=None):
    """Read the input-set task from reviewed features, without solving it."""
    domain = known.get("function_domain") or {}
    variable, function = domain.get("variable"), domain.get("function_name")
    if not domain.get("structure_supported") or not variable or not function:
        return {"rows": [], "summary": ""}
    variable, function = tex(variable), tex(function)
    options = [
        _option(f"自变量 ${variable}$ 的取值范围"),
        _option(f"函数值 ${function}({variable})$ 的取值范围", "goal",
                f"函数值 ${function}({variable})$ 的取值范围是值域；定义域是自变量 ${variable}$ 的取值集合。"),
    ]
    rows, givens = [], []
    for kind in ("expression", "goal", "given_domain"):
        selected = [fragment for fragment in fragments if fragment["fragment_kind"] == kind]
        if not selected:
            continue
        row_id = f"{target}:{kind}"
        spans = [_spans([fragment], text) for fragment in selected]
        signature = sha256(json.dumps([kind, spans, domain], sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()[:16]
        item = {"id": row_id, "kind": kind, "quote": spans,
                "fragment_ids": [fragment["id"] for fragment in selected],
                "knowledge_refs": list(dict.fromkeys(ref for fragment in selected
                                                     for ref in fragment["knowledge_refs"])),
                "source_refs": list(dict.fromkeys(ref for fragment in selected
                                                  for ref in fragment.get("source_refs", []))),
                "signature": signature}
        if kind == "goal":
            rows.append({**item, "options": _shuffle(row_id, options)})
        else:
            item["source_ref"] = domain["source_ref"] if kind == "expression" else domain["input_domain_source_ref"]
            givens.append(item)
    if domain.get("input_domain_source_ref"):
        given = next((item for item in givens if item["kind"] == "given_domain"), None)
        if given is None:
            given = {"id": f"{target}:given_domain", "kind": "given_domain", "quote": [],
                     "fragment_ids": [], "knowledge_refs": [],
                     "source_ref": domain["input_domain_source_ref"],
                     "source_refs": [domain["input_domain_source_ref"]]}
            givens.append(given)
        given["input_domain_ast"] = domain["input_domain_ast"]
        if candidate is not None:
            value = candidate
            for part in domain["input_domain_source_ref"].strip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
            given["text"] = f"题设输入范围：${variable}\\in {tex(value)}$。"
    summary = (f"定义域是自变量的取值集合。本题需要找出所有使原解析式有意义的 ${variable}$。"
               if rows else "")
    if summary and domain.get("input_domain_source_ref"):
        summary += "题设另给的输入范围也要同时满足。"
    return {"rows": rows, "givens": givens, "interaction": "choice",
            "question": "题目要求“定义域”，也就是要确定什么？", "summary": summary}


def _abstract_domain_d1_rows(target, fragments, known, text, *, candidate=None):
    """Separate the given call's domain from the requested outer-variable set."""
    domain = known.get("abstract_function_domain") or known.get('abstract_function_range') or {}
    if domain.get('kind') == 'find_abstract_domain_parameter':
        return _abstract_parameter_d1_rows(target, fragments, domain, text, candidate=candidate)
    selected = [fragment for fragment in fragments if fragment["fragment_kind"] == "goal"]
    if not domain.get("structure_supported") or not selected or candidate is None:
        return {"rows": [], "summary": ""}
    goal = candidate
    for part in target.strip("/").split("/"):
        goal = goal[int(part)] if isinstance(goal, list) else goal[part]
    variable = tex(domain["variable"])
    known_call, target_call = tex(goal["known_call"]), tex(goal["target_call"])
    correct = f"使 ${target_call}$ 有意义的自变量 ${variable}$ 的取值范围"
    feedback = f"目标函数的定义域是外层自变量 ${variable}$ 的取值范围；函数值的取值范围叫值域。"
    range_goal = domain.get('kind') == 'find_abstract_range'
    wrong = f"函数值 ${target_call}$ 的取值范围"
    if range_goal:
        correct, wrong = wrong, correct
        feedback = f'本问求全部能取到的函数值；先确定定义域，再检验新输入能否完整覆盖 ${domain["function_name"]}$ 的输入范围。'
    row_id = f"{target}:goal"
    spans = [_spans([fragment], text) for fragment in selected]
    row = {
        "id": row_id, "kind": "goal", "quote": spans,
        "fragment_ids": [fragment["id"] for fragment in selected],
        "knowledge_refs": list(dict.fromkeys(ref for fragment in selected for ref in fragment["knowledge_refs"])),
        "source_refs": [f"{target}/target_call"],
        "signature": sha256(json.dumps([spans, domain], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
        "options": _shuffle(row_id, [
            _option(correct),
            _option(wrong, "goal", feedback),
        ]),
    }
    givens = []
    for index, fragment in enumerate(fragments):
        kind = fragment["fragment_kind"]
        if kind not in ("given_domain", "given_range"):
            continue
        outer = fragment["source_refs"] == [f"{target}/input_domain"]
        given_text = (f"题设另限外层自变量：${variable}\\in {tex(goal['input_domain'])}$。" if outer else
                      f"已知 ${known_call}$ 的定义域为 ${tex(goal['known_domain'])}$。")
        if kind == 'given_range':
            given_text = (f"已知 ${known_call}$ 的值域为 ${tex(goal['known_range'])}$；"
                          "这是函数值的范围，不是自变量的范围。")
        givens.append({
            "id": f"{target}:{kind}:{index}", "kind": kind,
            "quote": [_spans([fragment], text)], "fragment_ids": [fragment["id"]],
            "knowledge_refs": fragment["knowledge_refs"], "source_refs": fragment["source_refs"],
            "text": given_text,
        })
    summary = (f"题面给出了 ${known_call}$ 的定义域；本题要找出所有使 ${target_call}$ 有意义的"
               f"外层自变量 ${variable}$，需要让完整输入落在同一对应关系的输入范围内。")
    if domain.get("concrete_denominator_ast") is not None:
        summary += "具体分母自身有意义且不为零的条件也要同时满足。"
    if "input_domain" in goal:
        summary += "题设另给的外层自变量范围也要同时满足。"
    if range_goal:
        summary = (f'已知 ${known_call}$ 的定义域和值域；本问求 ${target_call}$ 的值域。'
                   f'先确定目标函数的定义域，再检验新输入是否完整覆盖 ${domain["function_name"]}$ 的输入范围。')
    elif 'known_range' in goal:
        summary += "当前目标只求定义域；题设值域保留为已知条件，不用它限制自变量。"
    return {"rows": [row], "givens": givens, "interaction": "choice",
            "question": f"题目要求 ${target_call}$ 的{'值域' if range_goal else '定义域'}，也就是要确定什么？",
            "feedback": feedback, "summary": summary}


def _abstract_parameter_d1_rows(target, fragments, domain, text, *, candidate=None):
    selected = [fragment for fragment in fragments if fragment['fragment_kind'] == 'goal']
    if not domain.get('structure_supported') or not selected or candidate is None:
        return {'rows': [], 'summary': ''}
    goal = candidate
    for part in target.strip('/').split('/'):
        goal = goal[int(part)] if isinstance(goal, list) else goal[part]
    variable, parameter = tex(domain['variable']), tex(domain['parameter'])
    expression = tex(goal['target_call'])
    scope = '在题设给定的输入范围内，' if domain['known_strength'] == 'meaningful_only' else ''
    correct = f'{scope}求能保证至少存在一个合法 ${variable}$，使所有调用同时有意义的 ${parameter}$ 范围'
    feedback = f'固定参数 ${parameter}$ 后，至少要能找到一个 ${variable}$，让每个调用的输入同时落在题设给定范围内。'
    if domain['known_strength'] == 'meaningful_only':
        feedback += '只使用这个已知输入范围，不推断范围外是否有定义。'
    row_id = f'{target}:goal'
    spans = [_spans([fragment], text) for fragment in selected]
    row = {
        'id': row_id, 'kind': 'goal', 'quote': spans,
        'fragment_ids': [fragment['id'] for fragment in selected],
        'knowledge_refs': list(dict.fromkeys(ref for fragment in selected for ref in fragment['knowledge_refs'])),
        'source_refs': [f'{target}/parameter', f'{target}/quantifier'],
        'signature': sha256(json.dumps([spans, domain], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
        'options': _shuffle(row_id, [
            _option(correct),
            _option(f'求让每一个实数 ${variable}$ 都合法的 ${parameter}$ 范围', 'goal', feedback),
            _option(f'只要其中一个调用有意义，就接受这个 ${parameter}$', 'goal', feedback),
        ]),
    }
    given_text = (f"已知 ${tex(goal['known_call'])}$ 在 ${tex(goal['known_domain'])}$ 上有定义；只使用题设保证的输入范围。"
                  if domain['known_strength'] == 'meaningful_only' else
                  f"已知 ${tex(goal['known_call'])}$ 的定义域恰为 ${tex(goal['known_domain'])}$。")
    givens = [{
        'id': f'{target}:given_domain:{index}', 'kind': 'given_domain',
        'quote': [_spans([fragment], text)], 'fragment_ids': [fragment['id']],
        'knowledge_refs': fragment['knowledge_refs'], 'source_refs': fragment['source_refs'], 'text': given_text,
    } for index, fragment in enumerate(fragments) if fragment['fragment_kind'] == 'given_domain']
    summary = f'{given_text}本题要求 ${expression}$ 中各调用同时有意义，即{correct}。'
    return {'rows': [row], 'givens': givens, 'interaction': 'choice',
            'question': f'要使 ${expression}$ 有意义，这里要求参数 ${parameter}$ 满足什么条件？',
            'feedback': feedback, 'summary': summary}


def _match_domain_d1_rows(target, fragments, known, text, *, candidate=None):
    """Read Dom(f)=D → find parameter from reviewed features, without solving."""
    domain = known.get("function_domain") or {}
    goal = known.get("goal") or {}
    variable, function, parameter = domain.get("variable"), domain.get("function_name"), goal.get("symbol")
    if not domain.get("structure_supported") or not variable or not function or not parameter:
        return {"rows": [], "summary": ""}
    variable, function, parameter = tex(variable), tex(function), tex(parameter)
    options = [
        _option(f"使定义域恰为题给集合的参数 ${parameter}$ 的取值范围"),
        _option(f"自变量 ${variable}$ 的取值范围", "goal",
                f"题面已给出定义域，要求的是参数 ${parameter}$；不是再求自变量 ${variable}$ 的集合。"),
    ]
    rows, givens = [], []
    for kind in ("expression", "goal"):
        selected = [fragment for fragment in fragments if fragment["fragment_kind"] == kind]
        if not selected:
            continue
        row_id = f"{target}:{kind}"
        spans = [_spans([fragment], text) for fragment in selected]
        signature = sha256(json.dumps([kind, spans, domain, goal], sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()[:16]
        item = {"id": row_id, "kind": kind, "quote": spans,
                "fragment_ids": [fragment["id"] for fragment in selected],
                "knowledge_refs": list(dict.fromkeys(ref for fragment in selected
                                                     for ref in fragment["knowledge_refs"])),
                "source_refs": list(dict.fromkeys(ref for fragment in selected
                                                  for ref in fragment.get("source_refs", []))),
                "signature": signature}
        if kind == "goal":
            rows.append({**item, "options": _shuffle(row_id, options)})
        else:
            item["source_ref"] = domain["source_ref"]
            givens.append(item)
    if domain.get("prescribed_domain_ast") == ["real"]:
        summary = (f"定义域已给定为全体实数。本题要求使 ${function}({variable})$ 的定义域恰为 "
                   f"$\\mathbb R$ 的参数 ${parameter}$ 的取值范围。")
    else:
        summary = (f"题面已给出函数的定义域。本题要求使 ${function}({variable})$ 的全部合法输入恰好是题给集合的 "
                   f"参数 ${parameter}$ 的取值范围。集合内每个输入都要合法，集合外的输入都不能合法。")
    if not rows:
        summary = ""
    return {"rows": rows, "givens": givens, "interaction": "choice",
            "question": "题目已知定义域，实际要求确定什么？", "summary": summary}


def d2_options(goal):
    primary = goal["primary"]
    branch = ((goal.get("llm") or {}).get("selection") or {}).get("branch_id")
    labels = {o["type_id"]: o["label"] for o in goal["d2"]["options"]}
    options = []
    for option in goal["d2"]["options"]:
        role = option["role"]
        if role == "primary":
            checks = [c for c in option["checks"] if c["status"] == "supported" and c["role"] == "required"
                      and (branch is None or c["check_id"].startswith(f"{primary}/{branch}/"))]
            reasons = list(dict.fromkeys(c["student_cue"]["text"] for c in checks if c.get("student_cue")))
            feedback = ""
        elif role == "alternative":
            reasons = []
            feedback = f"这条思路也能做，但不是最直接的；这节课先按「{labels.get(primary, primary)}」学。"
        else:
            reasons = []
            sources = [s["text"] for s in option.get("confuse_sources", []) if s.get("text")]
            cues = [c["student_cue"]["text"] for c in option["checks"]
                    if c["status"] == "conflict" and c.get("student_cue")]
            feedback = "；".join(dict.fromkeys(sources or cues)) or "这类题的条件与本题不符。"
        row = {"type_id": option["type_id"], "label": option["label"], "role": role,
               "feedback": feedback, "reasons": reasons}
        hint = option.get("choice_hint")
        if isinstance(hint, str) and hint.strip():
            row["choice_hint"] = hint.strip()
        options.append(row)
    return sorted(options, key=lambda o: sha256((goal["target_ref"] + o["type_id"]).encode()).hexdigest())
