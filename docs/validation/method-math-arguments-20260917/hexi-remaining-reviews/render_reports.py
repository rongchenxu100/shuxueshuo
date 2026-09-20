"""Insert evidence-derived tables, all original steps and scope diagrams."""

import json
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads(path.read_text())


def code(value):
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def graph(attempt, sample):
    rows = attempt["graph"]
    number = attempt["number"]
    ids = {row["step"]["step_id"]: f"s{number}n{i}" for i, row in enumerate(rows)}
    invalid = {row["step_id"] for row in attempt["isolated_argument_checks"] if row["status"] == "invalid_in_isolation"}
    independent = {}
    if sample == 3 and number == 1:
        independent["candidates_D_ii"] = "离线还检出缺 C 坐标状态"
    if sample == 3 and number == 3:
        independent["i_vertex"] = "离线检出版本配置错误"
    lines = ["```mermaid", "flowchart TD"]
    for scope in ("i", "ii", "iii"):
        group = [row for row in rows if row["scope"] == scope]
        lines.append(f'  subgraph s{number}{scope}["Scope {scope} / Goal {group[0]["goal"]}"]')
        for row in group:
            step = row["step"]
            label = [step["step_id"], step["capability_id"]]
            if attempt["actual_failure"]["path"].startswith(row["path"] + "."):
                label.append("FAIL：首个数学绑定阻断")
            elif step["step_id"] in invalid:
                label.append("独立参数错误（离线检出）")
            if step["step_id"] in independent:
                label.append(independent[step["step_id"]])
            label.extend(["NOT EXECUTED", "no runtime result"])
            lines.append(f'    {ids[step["step_id"]]}["' + "<br/>".join(label) + '"]')
        lines.append("  end")
    for row in rows:
        for value in row["step"].get("args", {}).values():
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict) and "step_id" in item and "return" in item:
                    lines.append(f'  {ids[item["step_id"]]} -->|"{item["return"]}"| {ids[row["step"]["step_id"]]}')
    return "\n".join(lines + ["```"])


def main():
    for sample in (2, 3):
        folder = BASE / f"hexi-sample-{sample:02d}-review"
        data = read(folder / "analysis.json")
        original = Path(data["source"])
        relative = Path(os.path.relpath(original, folder)).as_posix()
        markdown = (folder / "README.md").read_text()
        evidence = [f"原始证据目录：[math/{sample}]({relative})。以下阅读副本由 artifact 无改写提取。", "", "| 轮次 | 实际输入 | 原始输出 | 阶段与错误 |", "|---|---|---|---|"]
        metadata = ["| Semantic / Provider | 输入 tokens | reasoning tokens | 可见 tokens¹ | total tokens | cache hit / miss | steps |", "|---|---:|---:|---:|---:|---|---:|"]
        chars = ["| 轮次 | system 字符 / 字节 | user 字符 / 字节 | reasoning 字符 | 可见输出字符 |", "|---|---|---|---:|---:|"]
        for attempt in data["attempts"]:
            n = attempt["number"]
            evidence.append(f"| S{n} / P1 | [system](attempt-{n}.prompt.system.md)、[user](attempt-{n}.prompt.user.md)、[上下文](attempt-{n}.context.json) | [原文](attempt-{n}.raw-response.txt)、[完整 steps](attempt-{n}.steps.json)、[reasoning](attempt-{n}.reasoning.txt) | [索引]({relative}/attempt-{n}.evidence-index.json)、[原错误]({relative}/attempt-{n}.attempt-error.json)、[复用/执行]({relative}/attempt-{n}.reuse.json) |")
            usage = attempt["metadata"]["provider_attempts"][0]["usage"]
            metadata.append(f"| S{n} / P1 | {usage['prompt_tokens']:,} | {attempt['thinking_tokens']:,} | {attempt['visible_tokens_by_subtraction']:,} | {usage['total_tokens']:,} | {usage['prompt_cache_hit_tokens']:,} / {usage['prompt_cache_miss_tokens']:,} | {len(attempt['graph'])} |")
            system = (folder / f"attempt-{n}.prompt.system.md").read_text()
            user = (folder / f"attempt-{n}.prompt.user.md").read_text()
            chars.append(f"| S{n} | {len(system):,} / {len(system.encode()):,} | {len(user):,} / {len(user.encode()):,} | {attempt['thinking_chars']:,} | {attempt['visible_chars']:,} |")
            plan = read(folder / f"attempt-{n}.steps.json")
            part = ["实际错误：", "", code(attempt["actual_failure"]), "", "图按原 Scope / Goal 分组；实线仅为 raw 中明确的 `{step_id, return}` 引用，不代表已经建立 runtime DAG。具名对象仍保留在 JSON 中。", "", graph(attempt, sample), "", f"<details><summary>S{n} 原始完整 JSON：{len(attempt['graph'])} 个 step，全部参数、输出目标与 answer_from</summary>", "", code(plan), "", "</details>"]
            markdown = markdown.replace(f"<!-- ATTEMPT-{n} -->", "\n".join(part))
            markdown = markdown.replace(f"<!-- FEEDBACK-{n} -->", code(attempt["feedback_received"]))
        markdown = markdown.replace("<!-- EVIDENCE -->", "\n".join(evidence))
        markdown = markdown.replace("<!-- METADATA -->", "\n".join(metadata + ["", "¹ 可见 tokens = provider completion_tokens − reasoning_tokens；这是由 provider 数据计算的差值。", "", *chars]))
        context = read(folder / "attempt-1.context.json")
        root = context["problem_planning_context"]["root"]
        diagram = ["```mermaid", "flowchart TD", '  P["Scope problem<br/>Γ: y=a*x²-b*x+c<br/>b>0"]']
        for i, child in enumerate(root["children"]):
            label = [f"Scope {child['scope_ref']} / Goal {child['goals'][0]['goal_ref']}", *child["facts"]]
            diagram.append(f'  Q{i}["' + "<br/>".join(label) + '"]')
            diagram.append(f"  P --> Q{i}")
        diagram.append("```")
        section_table = ["| 实际 user 段 | S1 字符 | S2 字符 | S3 字符 |", "|---|---:|---:|---:|"]
        for i, item in enumerate(data["attempts"][0]["prompt_sections"]):
            counts = " | ".join(str(a["prompt_sections"][i]["chars"]) for a in data["attempts"])
            section_table.append(f"| {item['name'].removeprefix('## ')} | {counts} |")
        markdown = markdown.replace("<!-- CONTEXT -->", "\n".join([*diagram, "", *section_table, "", "user 开头短指令另计。system 三轮相同；user 变化仅在 Validation Feedback 段。全部三组 sample 的首轮 system/user/Catalog/Schema 哈希一致，完整值保存在 analysis.json。", "", "<details><summary>实际 Scope / Goal authority frame</summary>", "", code(context["plan_authority_frame"]), "", "</details>"]))
        retry = ["```mermaid", "flowchart TD", '  X["math adapter 遇首个错误"] --> N["Compilation(content=None, plan=None)<br/>局部成功绑定记录未返回"]', '  N --> F["authoring_feedback 仅当前一条错误<br/>previous_invalid_content=None"]', '  F --> R["仍用 functional-plan-content/v2<br/>重写完整三问计划"]', '  Z["原始已执行/冻结 Goal：0<br/>canonical Plan / checkpoint：无<br/>scope-repair authority：未建立"] --> R', "```", "", "依据：[提前返回](../../../../server/shuxueshuo_server/solver/runtime/functional_plan_content.py:912)、[previous_invalid_content 来源](../../../../server/shuxueshuo_server/solver/runtime/functional_scope_retry.py:1095)、[原协议分支](../../../../server/shuxueshuo_server/solver/runtime/functional_scope_retry.py:940)。"]
        markdown = markdown.replace("<!-- RETRY -->", "\n".join(retry))
        probes = read(folder / "counterfactual-results.json")
        modes = {"expression-only": "修正全部错误数学表达", "point-only": "只修 Point", "angle-only": "只修直角等长条件", "add-c-state": "修表达 + 新增显式 C producer", "add-i-state": "修表达 + 新增显式 I 问曲线 producer", "source-ref": "修表达后转换为旧对象引用编码"}
        probe_rows = [f"共 {len(probes)} 组本地录制响应实验，0 次模型调用。[全部逐项改动与结果](counterfactual-results.json)", "", "| 原响应 | 副本变更 | 离线结果 | 证据 |", "|---|---|---|---|"]
        for p in probes:
            status = "accepted，三问答案核验通过" if p["status"] == "accepted" else "配置异常：无 StateVersionId（非 retryable）" if p["status"] == "execution_exception" else "仍阻断，具体独立错误见本轮分析"
            probe_rows.append(f"| S{p['attempt']} | {modes[p['mode']]} | {status} | [完整改动/结果]({p['evidence']}/result.json) |")
        probe_rows.extend(["", "这些结果只描述对应响应副本；不修改真实成功率，也不表示新 Prompt 经真实调用验证。除表中明确新增 producer 的两个模式外，实验保留全部原方法、步骤、Scope、Goal、结果引用和自由参数基底。"])
        markdown = markdown.replace("<!-- COUNTERFACTUALS -->", "\n".join(probe_rows))
        assert not re.search(r"<!-- [A-Z]+", markdown)
        (folder / "README.md").write_text(markdown)
        print(sample, "lines", len(markdown.splitlines()), "step nodes", sum(len(a["graph"]) for a in data["attempts"]))


if __name__ == "__main__":
    main()
