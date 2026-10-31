"""Self-contained, escaped reports for inspecting method choices without a server."""

import base64
import json
import re
from html import escape
from pathlib import Path
from urllib.parse import quote

from ..stage_one.report import CSS
from ..stage_two.contracts import ROOT
from .math_values import adapt_legacy_math_values

LABELS = {
    "completed": "选法评估完成", "input_error": "输入未通过校验", "partial": "部分失败", "failed": "失败",
    "no_verified_route": "暂无已验证解法", "unsupported_type": "题型暂无选法契约", "skipped": "跳过未确认目标",
    "no_applicable_method": "暂无可用方法", "triggered": "触发", "not_triggered": "未触发", "unknown": "未知",
    "applicable": "适用", "not_applicable": "不适用", "preferred": "优先", "optional": "可选",
    "superseded": "不优先", "capability_gap": "详细步骤暂不支持", "not_planned": "不生成路线",
    "execution_error": "目标处理异常",
    "solved": "已完成求解", "verified": "完整验证通过", "math_failed": "数学校验未通过",
    "conflict": "路线结论冲突", "running": "计算中", "planned": "已安排执行",
}
METHODS = {"discriminant": "判别式法", "interval": "区间最值法", "separation": "分离参数法", "swap": "更换主元法"}


def _read(path):
    try:
        return adapt_legacy_math_values(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        return None


def _json(value):
    return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def _details(label, value):
    return "<details><summary>" + escape(label) + "</summary>" + _json(value) + "</details>"


def _label(value):
    return escape(LABELS.get(value, str(value)) if value is not None else "—")


def _math_text(value):
    """Only author text nodes; KaTeX runs in untrusted, MathML-only mode."""
    return ''.join('<span class="math">' + escape(part[1:-1]) + '</span>'
                   if part.startswith('$') and part.endswith('$') else escape(part)
                   for part in re.split(r'(\$[^$]+\$)', str(value)))


def _answer_math(value):
    if not isinstance(value, dict):
        return ""
    formula = value.get("latex")
    return '<span class="math">' + escape(formula) + '</span>' if isinstance(formula, str) and formula else ""


def _goal_answer(answer, feasible_set):
    """Display supplied typed closure only; never infer or compute an extremum."""
    if not isinstance(answer, dict) or answer.get("kind") not in ("find_minimum", "find_maximum"):
        return ""
    minimum = answer["kind"] == "find_minimum"
    name, direction = ("最小值", "下") if minimum else ("最大值", "上")
    status = answer.get("status")
    if status == "attained":
        formula = _answer_math(answer.get("value"))
        explanation = name + "：" + formula if formula else None
    elif status == "not_attained":
        formula = _answer_math(answer.get("bound"))
        explanation = name + "不存在；只能趋近 " + formula + "。" if formula else None
    elif status == ("unbounded_below" if minimum else "unbounded_above"):
        explanation = name + "不存在：可行集没有" + direction + "界。"
    elif status == "empty_feasible_set":
        explanation = "没有满足题设的参数，" + name + "不存在。"
    else:
        explanation = None
    if explanation is None:
        status, explanation = "unknown", "目标答案尚未确定，暂不发布完成结论。"
    feasible = _answer_math(feasible_set)
    return ('<div class="goal-answer" data-answer-status="' + escape(status) + '">'
            + ('<p>完整可行集：' + feasible + '</p>' if feasible else '')
            + '<p>' + explanation + '</p></div>')


def _math_step(step, seq):
    body = '<article class="math-card" data-math-seq="' + str(seq) + '"><h4>'
    body += escape(str(step['ordinal'])) + '. ' + _math_text(step['title']) + '</h4>'
    body += '<p>' + _math_text(step.get('explanation', '')) + '</p>'
    for key, label in (('before', '由'), ('after', '得')):
        for expression in step.get(key, []):
            body += '<p>' + label + ' <span class="math">' + escape(expression['latex']) + '</span></p>'
    body += '<p class="muted">本步局部检查通过 · ' + escape(step['method_ref']) + '</p>'
    body += _details('条件、依据与来源', {key: step.get(key) for key in
                                        ('case_path', 'premise_refs', 'used_basis', 'source_refs', 'step_id', 'math_step_sha256')})
    return body + '</article>'


def _safe_artifact(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError('报告产物引用越过输出目录。')
    return _read(path)


def _route_details(directory, goal, events):
    body = ''
    for route in goal['routes']:
        body += '<h3>' + escape(METHODS.get(route['branch'], route['method'])) + ' · ' + _label(route['status']) + '</h3>'
        artifact = _safe_artifact(directory, route['trajectory']) if route.get('trajectory') else None
        if not artifact:
            body += _details('路线诊断', route)
            continue
        for ref in artifact.get('math_steps', []):
            step = _safe_artifact(directory, ref['file'])
            if not step:
                continue
            seq = next((event['seq'] for event in events if event.get('target_ref') == goal['target_ref']
                        and event.get('route_id') == route['route_id']
                        and event.get('payload', {}).get('kind') == 'math_step'
                        and event.get('step_id', event.get('payload', {}).get('step_id')) == step['step_id']), 0)
            body += _math_step(step, seq)
        body += _details('完整方法轨迹：调用、跳过与判断', artifact.get('steps'))
        body += _details('完整约束处理、独立分区证明与目标收束', artifact.get('finalization'))
        body += _details('路线题设处理记录', artifact.get('constraint_context'))
        body += _details('验证预算与各阶段耗时', artifact.get('verification_timing'))
        body += _details('方法求解预算与各阶段耗时', artifact.get('solve_timing'))
        body += _details('实际用量、保留额度与剩余预算', artifact.get('budget_accounting'))
        route_result = artifact.get('result') or {}
        body += _goal_answer(route_result.get('answer'), route_result.get('feasible_set'))
        body += _details('路线结果与诊断', {'result': artifact.get('result'), 'diagnostics': artifact.get('diagnostics')})
    return body


def _page(title, body):
    extra = (".columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}"
             "table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border:1px solid #dbe4e2}"
             "td.current{background:#e0f4e9}pre{overflow-wrap:anywhere;white-space:pre-wrap}"
             ".original{white-space:pre-wrap}code{overflow-wrap:anywhere}"
             ".math-card{border:1px solid #dbe4e2;border-radius:12px;padding:16px;margin:16px 0}"
             ".math{font-size:1.1em}math{overflow-x:auto;max-width:100%}[hidden]{display:none!important}")
    katex = (ROOT / 'site/assets/practice/vendor/katex-0.18.9/katex.min.js').read_text()
    scripts = '<script data-vendor="katex">' + katex.replace('</script', '<\\/script') + '</script><script>' + """
document.querySelectorAll('.math').forEach(node => {
  katex.render(node.textContent, node, {throwOnError:false, trust:false, output:'mathml'});
});
const cursor = document.querySelector('#event-cursor');
if (cursor) cursor.addEventListener('input', () => {
  document.querySelector('#event-position').textContent = cursor.value;
  document.querySelectorAll('[data-math-seq]').forEach(node => {
    node.hidden = Number(node.dataset.mathSeq) > Number(cursor.value);
  });
});
""" + '</script>'
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(title)
            + '</title><style>' + CSS + extra + '</style></head><body><main>' + body + '</main>' + scripts + '</body></html>')


def _plane(d3):
    if not d3:
        return '<p>本目标没有学生 D3 片段。</p>'
    interaction = d3["interaction"]
    if interaction["type"] in ("read", "method_cards"):
        return "<p>" + escape(d3.get("question", d3["title"])) + "</p>"
    xs, ys = interaction["x"]["options"], interaction["y"]["options"]
    cell = d3["expected_answer"]["cell"]
    body = '<p>本目标格子：<code>' + escape(", ".join(cell)) + '</code></p><table><thead><tr><th>'
    body += escape(interaction["y"]["label"] + " / " + interaction["x"]["label"]) + '</th>'
    body += ''.join('<th>' + escape(x["label"] + " · " + x["value"]) + '</th>' for x in xs)
    body += '</tr></thead><tbody>'
    for y in ys:
        body += '<tr><th>' + escape(y["label"] + " · " + y["value"]) + '</th>'
        for x in xs:
            current = [x["value"], y["value"]]
            methods = [METHODS.get(branch, branch) for branch, cells in interaction["coverage"].items()
                       if current in cells]
            body += ('<td class="current">' if current == cell else '<td>')
            body += escape("、".join(methods) or "无可选方法") + '</td>'
        body += '</tr>'
    return body + '</tbody></table><p class="muted">高亮格为本目标；其他格只展示方法的典型用途。</p>'


def _verdicts(d3):
    if not d3:
        return ""
    return "".join('<p><strong>' + escape(METHODS.get(key, key)) + '</strong> · '
                   + escape(item["value"]) + '<br>' + _math_text(item["message"]) + '</p>'
                   for key, item in d3["verdicts"].items())


def render_result(directory):
    directory = Path(directory)
    result = _read(directory / "stage-three-result.json")
    if not isinstance(result, dict):
        raise TypeError("缺少有效的阶段③结果，不能重建报告。")
    stage_one = _read(directory / "stage-one-input.json")
    stage_one = stage_one if isinstance(stage_one, dict) else {}
    candidate = stage_one.get("candidate") or {}
    candidate = candidate if isinstance(candidate, dict) else {}
    demo_source = _read(ROOT / "site/data/graph-walk/quadratic-always-q01.source.json") or {}
    demo = next((row for row in demo_source.get("intro", []) if row.get("id") == "D3"), None)
    title = "图谱课程 · 阶段③调试报告"
    milestone = result.get('milestone', '1a')
    body = '<header><div class="eyebrow">批次 ' + escape(milestone) + '</div><h1>' + title + '</h1><p>'
    status_label = '本批处理完成' if result['status'] == 'completed' and milestone != '1a' else _label(result['status'])
    body += status_label + ' · <code>' + escape(result["run_id"]) + '</code></p>'
    body += ('<p>本批生成选法与 D3/D4；尚未执行数学路线，不生成答案、求解事件或问答。</p>' if milestone == '1a'
             else '<p>数学步骤逐步保存；局部检查通过不代表整题完成。完整验证后发布答案和教学问答交接清单，本阶段不调用 LLM。</p>')
    body += '</header>'
    event_path = directory / 'events.jsonl'
    events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()] if event_path.is_file() else []
    if events:
        last = events[-1]['seq']
        body += '<section><h2>已提交步骤回放</h2><label>事件水位 <output id="event-position">' + str(last) + '</output>'
        body += '<input id="event-cursor" type="range" min="0" max="' + str(last) + '" value="' + str(last) + '"></label>'
        body += '<p>游标控制下方已提交数学卡片；路线结果与校验证据保留最终状态，供对照。</p>'
        body += _details('持久事件（回放不重新计算）', events) + '</section>'
    body += '<section><h2>题图与原文</h2>'
    if (directory / "source.png").is_file():
        image = base64.b64encode((directory / "source.png").read_bytes()).decode()
        body += '<img style="max-width:100%;max-height:420px" alt="原题图" src="data:image/png;base64,' + image + '">'
    body += '<div class="original">' + escape(str(candidate.get("original_text", ""))) + '</div></section>'
    body += '<section><h2>输入准入与出处</h2>' + _json(result["input_validation"])
    body += _details("输入引用与哈希", _read(directory / "input.json"))
    body += _details("阶段①准入状态", stage_one.get("statuses"))
    if result.get("preparation") is not None:
        body += _details("准入与选法计算预算、耗时及诊断", result["preparation"])
    if result.get("retained_goals"):
        body += _details("核验未完成：已撤销可用性的历史目标与已发布片段", result["retained_goals"])
    body += _details("阶段③本次调用数（恒为零）", result["llm"])
    body += _details("上游阶段②调用计数（与本阶段分开）", result.get("upstream_llm")) + '</section>'
    for number, goal in enumerate(result["goals"], 1):
        body += '<section id="goal-' + str(number) + '"><h2>' + escape(goal["label"] or f"目标 {number}") + '</h2>'
        body += '<p>' + _label(goal["status"]) + ' · <code>' + escape(goal["target_ref"]) + '</code></p>'
        body += _goal_answer(goal.get('answer'), goal.get('feasible_set'))
        body += '<p>主要归属：' + escape(str(goal["primary"])) + ' · 来源：' + escape(str(goal["primary_source"])) + '</p>'
        body += _details("原始目标", goal["goal"]) + _details("诊断", goal["diagnostics"])
        body += '<h3>完整原始题设与来源</h3><p>各路线的处理记录见下方路线详情。</p>' + _json(goal["constraint_context"])
        body += _details("阶段①原始特征（本阶段不重新提取）", goal["features"])
        selection = goal.get("selection") or {}
        body += '<h3>分支四项结论与前提证据</h3><table><thead><tr>'
        body += '<th>方法</th><th>触发</th><th>适用性</th><th>推荐</th><th>路线计划</th></tr></thead><tbody>'
        for branch in selection.get("branches", []):
            body += '<tr><th>' + escape(METHODS.get(branch["branch"], branch["branch"])) + '</th>'
            body += ''.join('<td>' + _label(branch[key]) + '</td>'
                            for key in ("trigger", "applicability", "recommendation", "route_plan")) + '</tr>'
        body += '</tbody></table>'
        for branch in selection.get("branches", []):
            body += _details(METHODS.get(branch["branch"], branch["branch"]) + " · 检查与绑定", branch)
        body += _details("推荐规则", selection.get("recommendation_rule"))
        body += '<h3>D3 · 方法坐标图</h3>' + _plane(goal.get("d3"))
        body += '<div class="columns"><div><h4>本题判断说明</h4>' + _verdicts(goal.get("d3")) + '</div>'
        body += '<details><summary>Q01 Demo 原稿参考（不参与本题计算）</summary>' + _verdicts(demo) + '</details></div>'
        body += _details("D3 原始片段", goal.get("d3"))
        body += '<h3>D4 · 方法路线</h3>' + _json(goal.get("d4"))
        body += _details("数学路线状态", goal["routes"])
        body += _route_details(directory, goal, events) + '</section>'
    body += '<section><h2>完整产物</h2><p>'
    links = [("stage-three-result.json", "阶段③结果"), ("input.json", "输入引用"),
             ("stage-two-input.json", "阶段②快照"), ("stage-one-input.json", "阶段①快照"), ("frozen.json", "实现版本")]
    links += [(name, label) for name, label in [('events.jsonl', '已提交事件'), ('checkpoint.json', '恢复快照')]
              if (directory / name).is_file()]
    body += ' · '.join('<a href="' + name + '">' + label + '</a>' for name, label in links) + '</p></section>'
    path = directory / "index.html"
    path.write_text(_page(title, body), encoding="utf-8")
    return path


def render_batch(directory):
    directory = Path(directory)
    summary = _read(directory / "batch-summary.json")
    if not isinstance(summary, dict):
        raise TypeError("缺少有效批次汇总。")
    title = "阶段③ · 录制批次验收"
    body = '<header><h1>' + title + '</h1><p>阶段①真实录制重验 → 阶段②离线判型 → 阶段③选法与方法执行。</p>'
    body += '<p>批次 ' + escape(summary.get('milestone', '1a')) + '</p>'
    body += '<p>' + ("批次完成" if summary["completed"] else "批次未通过") + '</p></header>'
    body += '<section><h2>本阶段调用计数</h2>' + _json(summary["llm"]) + '</section>'
    body += '<section><h2>逐题调试</h2><table><thead><tr><th>样本</th><th>状态</th><th>已确认目标</th>'
    body += '<th>跳过</th><th>已解决目标</th><th>已验证路线</th></tr></thead><tbody>'
    for row in summary["results"]:
        relative = Path(row["sample_dir"]) / "index.html"
        resolved = (directory / relative).resolve()
        if not resolved.is_relative_to(directory.resolve()) or not resolved.is_file():
            raise ValueError("批次报告只链接本输出目录内的有效报告。")
        body += '<tr><td><a href="' + quote(relative.as_posix(), safe="/") + '">'
        body += escape(f"{row['case_id']} / {row['sample_id']}") + '</a></td>'
        body += '<td>' + _label(row["status"]) + '</td><td>' + str(row["eligible"]) + '</td><td>'
        body += str(row["skipped"]) + '</td><td>' + str(row.get('solved', 0)) + '</td><td>'
        body += str(row.get('verified_routes', 0)) + '</td></tr>'
    body += '</tbody></table></section><p><a href="batch-summary.json">批次结果 JSON</a> · '
    body += '<a href="stage-two/index.html">本次阶段②报告与阶段①重验材料</a></p>'
    for relative, label in (("selection-replay/stage-three/index.html", "Q01 · 历史 LLM 判型准入"),
                            ("student-upload/stage-three/index.html", "Q13 · 真实学生上传准入")):
        if (directory / relative).is_file():
            body += '<p><a href="' + relative + '">' + label + '</a>（单列证据，不计入 22 份样本）</p>'
    path = directory / "index.html"
    path.write_text(_page(title, body), encoding="utf-8")
    return path
