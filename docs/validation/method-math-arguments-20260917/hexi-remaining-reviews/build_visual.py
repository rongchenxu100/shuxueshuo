"""Embed verified sample evidence in the task's literal visualization fragment."""

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
VISUAL = Path("/Users/haorong/.codex/visualizations/2026/09/17/01a0af4d-0f94-7eb0-8705-8ea68da9f3c3/hexi-remaining-samples.html")

SUMMARIES = {
    2: [
        {"input": "共同上下文；feedback=[]", "blocker": "直角等长条件用逗号，expected ∈, got =", "next": "下一轮只收到 parser 错误；无 previous Plan",
         "expression": "∠CAD = 90°, AC = AD", "mechanism": "逗号进入 A,B∈Γ 分支 → expr(21) 只读 AC → take(∈) 遇到 =",
         "independent": "四处具名 StepResultRef 可由原规则归一；自由参数 c、约束省略均可通过。",
         "change": "首轮保留 c；先求 C；Point 正确使用 A"},
        {"input": "共同上下文 + 逗号错误；无前次表达", "blocker": "只改空格，继续触发同一逗号语法错误", "next": "S3 与 S2 的完整 Prompt 逐字相同",
         "expression": "∠CAD=90°, AC=AD", "mechanism": "parser 忽略空白 → 条件语法没有修正 → 仍报 expected ∈, got =",
         "independent": "仅修条件字符串，原 10 步方法链通过；不需更改 c 或补约束参数。",
         "change": "具名状态改为 Γ 字符串；条件只去部分空格"},
        {"input": "与 S2 相同的 Prompt；仍无 previous Plan", "blocker": "新增 A=(-1,0) Point 表达，提前失败", "next": "∠CAD∈90° 和 III 问 Point 错误没有进入实际反馈",
         "expression": "curve_points=[\"A=(-1,0)\"]", "mechanism": "坐标等式解析为条件 → 参数要求 Point → 与可见点 A 的表达键不匹配",
         "independent": "另有 III 问 Point 错误、角度 ∈ 和逗号错误；仅改逗号还会触发 type.membership。",
         "change": "自由参数 c→b；角度 =→∈；两个 Point 改回坐标等式"},
    ],
    3: [
        {"input": "共同上下文；feedback=[]", "blocker": "II 的逗号条件；缺 C 坐标状态尚未暴露", "next": "下一轮只收到逗号错误，没有缺 C 的诊断",
         "expression": "∠CAD = 90°, AC = AD", "mechanism": "顶层逗号被当作成员列表 → expected ∈, got =；原始 9 步均未执行",
         "independent": "离线修表达后缺 C 的 reference Point 状态；7 个调用执行，I/III passed，II unbound。",
         "change": "II 只有建曲线、列候选、筛选三步；缺 C 的状态 producer"},
        {"input": "共同上下文 + 逗号错误；无 previous Plan", "blocker": "II 的 curve_points=A=(-1,0) 无法绑定 Point", "next": "下一轮只收到 Point 错误；旧逗号问题不在反馈中",
         "expression": "curve_points=\"A=(-1,0)\"", "mechanism": "Point 参数收到坐标等式 → 无匹配点表达；单个字符串的基数形式本身合法",
         "independent": "另有 III 问 Point 和逗号条件；三处表达修正后通过。C producer 已自行补齐。",
         "change": "补 C producer；保留 b；II/III 又使用坐标等式传点"},
        {"input": "共同上下文 + Point 错误；没有前两轮计划", "blocker": "II 逗号条件再次出现；I 版本问题尚未到达", "next": "原始 sample blocked；离线才暴露独立配置错误",
         "expression": "∠CAD = 90°, AC = AD", "mechanism": "原始仍止于逗号绑定；离线修正后，I 的模板直读缺 StateVersionId，两种编码一致",
         "independent": "I 按公开模板规则直接读取 Γ；最终强制来源版本时，math_object 未连接到 StateVersionId。",
         "change": "Point 修为 A；保留 C producer；按 Catalog 说明删 I 问建曲线步骤"},
    ],
}

FINDINGS = {
    2: [
        "三轮原始首个阻断均属于数学参数绑定；30 个 step 均未执行。",
        "S1/S2 各修一个条件字符串即通过；S3 修三个字符串后通过，方法和 Scope 不变。",
        "S1 的四处具名状态 StepResultRef 由既有 named_entity_result_ref_normalized 安全归一。",
        "S2 与 S3 的 system/user Prompt 完全相同；反馈没有携带前次计划或出错表达。",
        "S3 reasoning 按 expected ∈ 把角度 = 改为 ∈；仅把逗号改成 ∧ 仍触发 type.membership。",
    ],
    3: [
        "三轮原始分别 9/10/9 个 step，共 28 个全部未执行。",
        "S1 修表达后缺 C 的 Point 状态，属于独立计划依赖缺口；补显式 C producer 后通过。",
        "S2 允许 many 参数的单值 wire 形式；只修两个 Point 表达和条件字符串后通过。",
        "S3 按实际 Catalog 选择直接读 Γ；其模板物化结果没有进入最终精确版本账本。",
        "S3 两种编码的规范计划和配置异常现场相同；补显式曲线 producer 能绕过问题，但未修复模板直读契约。",
    ],
}


def read(path):
    return json.loads(path.read_text())


def main():
    context = read(BASE / "hexi-sample-02-review" / "attempt-1.context.json")
    keys = ("problem_planning_context", "plan_authority_frame", "strategy_principles", "functional_capability_catalog", "few_shot_examples", "functional_few_shot_selection", "output_json_schema")
    data = {"context": {key: context[key] for key in keys}, "samples": []}
    modes = {"expression-only": "修全部错误表达", "point-only": "只修 Point", "angle-only": "只修直角等长表达", "source-ref": "修表达后换旧编码", "add-c-state": "修表达 + C producer", "add-i-state": "修表达 + I 曲线 producer"}
    for sample in (2, 3):
        folder = BASE / f"hexi-sample-{sample:02d}-review"
        analysis = read(folder / "analysis.json")
        result = read(folder / "original-result.json")
        probes = read(folder / "counterfactual-results.json")
        item = {"sample": sample, "tokens": result["tokens"]["total_tokens"], "seconds": result["seconds"],
                "steps": sum(len(a["graph"]) for a in analysis["attempts"]), "findings": FINDINGS[sample],
                "probe_records": probes, "probes": [], "attempts": []}
        if sample == 3:
            item["controls"] = read(folder / "encoding-controls.json")
        for p in probes:
            if p["status"] == "accepted":
                outcome = "accepted · 三问核验通过"
            elif p["status"] == "execution_exception":
                outcome = "配置异常 · 无 StateVersionId"
            else:
                encoded = json.dumps(p.get("errors", []), ensure_ascii=False)
                outcome = "仍缺 C 状态" if "condition_role_state_unavailable" in encoded else "仍有 Point 表达错误" if "math_argument_unresolved" in encoded else "仍有逗号条件错误"
            item["probes"].append({"attempt": f"S{p['attempt']}", "label": modes[p["mode"]], "outcome": outcome})
        for a in analysis["attempts"]:
            n = a["number"]
            independent = {check["step_id"] for check in a["isolated_argument_checks"] if check["status"] == "invalid_in_isolation"}
            if sample == 3 and n == 1:
                independent.add("candidates_D_ii")
            if sample == 3 and n == 3:
                independent.add("i_vertex")
            item["attempts"].append({
                "number": n, "summary": SUMMARIES[sample][n-1], "graph": a["graph"], "error": a["actual_failure"],
                "feedback": a["feedback_received"], "runtime_reuse": a["runtime_reuse"],
                "prompt_tokens": a["metadata"]["usage"]["prompt_tokens"], "reasoning_tokens": a["thinking_tokens"],
                "visible_tokens": a["visible_tokens_by_subtraction"], "system_chars": a["system_chars"], "user_chars": a["user_chars"],
                "system": (folder / f"attempt-{n}.prompt.system.md").read_text(), "user": (folder / f"attempt-{n}.prompt.user.md").read_text(),
                "plan": read(folder / f"attempt-{n}.steps.json"), "raw": (folder / f"attempt-{n}.raw-response.txt").read_text(),
                "independent_steps": sorted(independent),
            })
        data["samples"].append(item)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    text = VISUAL.read_text()
    if "__HEXI_REMAINING_DATA__" in text:
        text = text.replace("__HEXI_REMAINING_DATA__", encoded)
    else:
        text = re.sub(r'(<script type="application/json" id="hr-data">).*?(</script>)', lambda m: m[1] + encoded + m[2], text, count=1, flags=re.S)
    VISUAL.write_text(text)
    assert VISUAL.stat().st_size < 1_000_000
    print("visual bytes:", VISUAL.stat().st_size)


if __name__ == "__main__":
    main()
