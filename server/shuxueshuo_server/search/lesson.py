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

from .proposition import transformation
from .walk import walk

NODES = ROOT / "site/data/knowledge-next/nodes"
RESULT = "stage-two-result.json"
INEQUALITIES = {"<", "<=", ">", ">="}
BREAKS = re.compile(r"[，,。；;：:]")


def stage_one_result(result, problem_id):
    """The stage-two input for a student upload: no gold, so no evaluation claim."""
    return {
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


def present_lesson(stage_two, features, text, problem_id="problem", *, candidate=None):
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
        goal["walk"] = walk(goal, text, problem_id)
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
    if known.get("goal", {}).get("kind") in ("find_domain", "match_domain"):
        # The domain locator proves the original arithmetic tree separately
        # from the generic polynomial reader (which can reject valid \frac).
        diagnostics = [item for item in goal["d1"].get("diagnostics", [])
                       if item["code"] in {"d1.scope_or_features_ambiguous",
                                           "d1.function_definition_not_uniquely_located"}]
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
    if known.get("goal", {}).get("kind") == "find_domain":
        return _domain_d1_rows(target, fragments, known, text, candidate=candidate)
    if known.get("goal", {}).get("kind") == "match_domain":
        return _match_domain_d1_rows(target, fragments, known, text, candidate=candidate)
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
        options.append({"type_id": option["type_id"], "label": option["label"], "role": role,
                        "feedback": feedback, "reasons": reasons})
    return sorted(options, key=lambda o: sha256((goal["target_ref"] + o["type_id"]).encode()).hexdigest())
