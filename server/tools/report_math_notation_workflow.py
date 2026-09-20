"""Render a frozen workflow batch and a separately labelled offline comparison."""

import argparse
import json
import os
from hashlib import sha256
from html import escape
from pathlib import Path

from shuxueshuo_server.problem_understanding.notation_semantics import evaluate
from shuxueshuo_server.problem_understanding.transport_accounting import (
    transport_cohorts,
    workflow_image_transport,
)
from shuxueshuo_server.problem_understanding.workflow import frozen_files
from shuxueshuo_server.problem_understanding.workflow_usage import call_usage, stages


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def pre(value):
    return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def link(path, output, label):
    return (
        '<a href="'
        + escape(os.path.relpath(path, output), quote=True)
        + '">'
        + escape(label)
        + "</a>"
    )


def total(rows, field):
    values = [row[field] for row in rows]
    return sum(values) if all(v is not None for v in values) else None


def report(batch, output):
    batch, output = batch.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary, frozen = (
        read(batch / "batch-summary.json"),
        read(batch / "frozen-batch.json"),
    )
    cases, sections = [], []
    for case in summary["cases"]:
        source = batch / case
        result = read(source / "workflow/workflow-result.json")
        gold = read(source / "input-fixture/gold.json")
        policy_path = source / "input-fixture/acceptance-policy.json"
        policy = read(policy_path) if policy_path.exists() else None
        offline = evaluate(gold, result["candidate"], policy)
        live = summary["results"][case]
        row = {
            "case": case,
            "live": live,
            "image_transport": workflow_image_transport(source / "workflow"),
            "offline_after_code_fix": offline,
            "stages_from_raw_provider_records": stages(source / "workflow"),
            "calls": [],
        }
        ledger = read(source / "workflow/ledger.json")
        calls_html = []
        for call in ledger["calls"]:
            saved = read(source / "workflow" / call["response_file"])
            raw_text = saved["text"]
            record = {
                "stage": call["stage"],
                "number": call["number"],
                "seconds": call.get("elapsed_seconds"),
                "network_attempts": call.get("network_attempts"),
                "usage": call_usage(saved),
                "finish_reason": saved["finish_reason"],
                "response_sha256": sha256(
                    (source / "workflow" / call["response_file"]).read_bytes()
                ).hexdigest(),
                "visible_output": json.loads(raw_text),
            }
            row["calls"].append(record)
            event = next(
                (e for e in result["events"] if e["call"] == call["number"]), {}
            )
            calls_html.append(
                f"<details><summary>调用 {call['number']} · {escape(call['stage'])} · {record['seconds']:.3f}s</summary>"
                + pre(record["usage"])
                + "<h4>模型返回</h4>"
                + pre(record["visible_output"])
                + "<h4>校验、修改范围和采用决定</h4>"
                + pre(event)
                + "<p>"
                + link(
                    source / "workflow" / call["directory"] / "request.json",
                    output,
                    "完整请求",
                )
                + " · "
                + link(
                    source / "workflow" / call["response_file"], output, "完整原始响应"
                )
                + "</p></details>"
            )
        cases.append(row)
        passed = "通过" if live["passed"] else "未通过"
        sections.append(
            '<section id="'
            + escape(case)
            + '"><h2>'
            + escape(case)
            + " · 冻结验收："
            + passed
            + " · 当前离线："
            + ("通过" if offline["ok"] else "未通过")
            + "</h2>"
            + "<p>冻结时首轮："
            + ("通过" if live["first_passed"] else "未通过")
            + "；冻结时闭环："
            + passed
            + "；冻结时严格等价："
            + ("是" if live["strict_semantics_passed"] else "否")
            + "；source_reviewed："
            + str(live["source_reviewed"]).lower()
            + "；repair 次数："
            + str(live["content_calls"] - 1)
            + "</p>"
            + "<p>终态："
            + escape(live["status"])
            + "；缺图阻断："
            + str(live["missing_figure_blocked"]).lower()
            + "</p>"
            + '<details><summary>本题原图</summary><img alt="原图" src="'
            + escape(
                os.path.relpath(source / "input-fixture/source.png", output), quote=True
            )
            + '"></details>'
            + (
                "<details><summary>首轮候选</summary>"
                + pre(result["first_candidate"])
                + "</details>"
                if result["first_candidate"] != result["candidate"]
                else ""
            )
            + "<details open><summary>最终完整候选</summary>"
            + pre(result["candidate"])
            + "</details>"
            + "".join(calls_html)
            + "<details><summary>冻结验收结果</summary>"
            + pre(read(source / "final-acceptance.json"))
            + "</details>"
            + "<details><summary>代码修复后的离线比较（无新模型调用）</summary>"
            + pre(offline)
            + "</details>"
            + "</section>"
        )
    all_stages = [
        stage
        for row in cases
        for stage in row["stages_from_raw_provider_records"].values()
    ]
    totals = {
        field: total(all_stages, field)
        for field in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "visible_output_tokens",
            "seconds",
            "calls",
        )
    }
    totals.update(
        wall_seconds=summary["wall_seconds"],
        first_passed=summary["first_passed"],
        live_passed=summary["passed"],
        strict_passed=sum(r["live"]["strict_semantics_passed"] for r in cases),
        offline_passed=sum(r["offline_after_code_fix"]["ok"] for r in cases),
        offline_strict_passed=sum(
            r["offline_after_code_fix"]["strict"]["ok"] for r in cases
        ),
        review_confirmed=sum(r["live"]["source_reviewed"] for r in cases),
        repair_calls=sum(r["live"]["content_calls"] - 1 for r in cases),
    )
    totals["seconds"] = round(totals["seconds"], 3)
    cohorts = transport_cohorts(
        {
            row["case"]: {
                **row["live"],
                "image_transport": row["image_transport"],
                "stages": row["stages_from_raw_provider_records"],
                "file_api_calls": total(
                    list(row["stages_from_raw_provider_records"].values()),
                    "file_api_calls",
                ),
            }
            for row in cases
        }
    )
    artifact = {
        "batch": batch.name,
        "source_batch_sha256": sha256(
            (batch / "batch-summary.json").read_bytes()
        ).hexdigest(),
        "network_calls_during_report": 0,
        "candidate_only": True,
        "solver_ready": False,
        "live_frozen_inputs": frozen,
        "offline_code": frozen_files(),
        "totals": totals,
        "kpi_by_image_transport": cohorts,
        "cases": cases,
        "accounting_note": "输出 token 已包含 reasoning，不能再次相加。图片传输方式从各次原始请求恢复；Files、base64、mixed 和 unknown 分组统计，不能直接合并比较质量或性能。资源总量仅作本批次消耗汇总。",
    }
    write(output / "results.json", artifact)
    write(output / "transport-kpi.json", cohorts)
    table_rows, md_rows = [], []
    for row in cases:
        r = row["live"]
        usage = row["stages_from_raw_provider_records"]
        inp, out = (
            total(list(usage.values()), k) for k in ("input_tokens", "output_tokens")
        )
        values = [
            row["case"],
            row["image_transport"],
            "通过" if r["first_passed"] else "失败",
            "通过" if r["passed"] else "失败",
            "严格"
            if r["strict_semantics_passed"]
            else "政策接受"
            if r["passed"]
            else "有差异",
            "严格通过"
            if row["offline_after_code_fix"]["strict"]["ok"]
            else "政策接受"
            if row["offline_after_code_fix"]["ok"]
            else "有差异",
            r["source_status"],
            str(r["content_calls"] - 1),
            str(inp),
            str(out),
            f"{r['elapsed_seconds']:.3f}",
        ]
        table_rows.append(
            "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in values) + "</tr>"
        )
        md_rows.append("| " + " | ".join(values) + " |")
    headers = [
        "题目",
        "图片传输",
        "冻结首轮",
        "冻结闭环",
        "冻结语义",
        "当前离线",
        "复核",
        "修复",
        "输入 token",
        "输出 token",
        "调用累计秒",
    ]
    table = (
        "<table><thead><tr>"
        + "".join("<th>" + v + "</th>" for v in headers)
        + "</tr></thead><tbody>"
        + "".join(table_rows)
        + "</tbody></table>"
    )
    html = (
        '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>七题抽取复核与修复验证</title><style>body{font:16px/1.6 system-ui;color:#182236;max-width:1120px;margin:40px auto;padding:0 22px}"
        "h1{font-size:32px}section{border-top:1px solid #cbd1d9;margin-top:42px;padding-top:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f8;padding:18px;font:14px/1.65 monospace}"
        "table{border-collapse:collapse;display:block;overflow:auto;font-size:13px}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left;white-space:nowrap}details{margin:14px 0}summary{cursor:pointer;font-weight:600}img{max-width:100%}a{color:#165eb4}.note{border-left:4px solid #db962d;background:#fff6e6;padding:16px}</style>"
        "<h1>七题 DeepSeek 抽取、复核与修复</h1>"
        "<p>真实批次："
        + escape(batch.name)
        + "。模型 deepseek-flash；并发 3。</p>"
        + f'<p class="note">冻结时验收：首轮 {totals["first_passed"]}/{len(cases)}，闭环 {totals["live_passed"]}/{len(cases)}；{totals["strict_passed"]} 题严格等价。'
        + f" 当前代码离线复验：{totals['offline_passed']}/{len(cases)}，其中 {totals['offline_strict_passed']} 题严格等价；没有新增模型调用。"
        + f"{totals['review_confirmed']} 份候选经 review confirmed，repair 共 {totals['repair_calls']} 次。所有结果仍是 candidate_only，solver_ready=false。</p>"
        + table
        + "<h2>按图片传输方式统计</h2><p>Files 与 base64 的质量、用量和耗时分开统计；缺少记录时标为 unknown，不依据当前默认值猜测历史方式。</p>"
        + pre(cohorts)
        + "<p>总墙钟 "
        + str(totals["wall_seconds"])
        + " 秒；各题耗时为 provider 调用时间之和，包含传输过程，存在并发，不能当成墙钟时间。输出 token 已包含 reasoning。</p>"
        "<details><summary>完整统计</summary>" + pre(totals) + "</details>"
        "<p>离线结果单独展示；真实批次和冻结验收结果没有改写，也没有追加付费调用。"
        + link(output / "README.md", output, "分析报告")
        + " · "
        + link(output / "results.json", output, "机器可读统计")
        + "</p>"
        + "".join(sections)
        + "</html>"
    )
    (output / "outputs.html").write_text(html)
    (output / "case-table.md").write_text(
        "| "
        + " | ".join(headers)
        + " |\n|"
        + "---|" * len(headers)
        + "\n"
        + "\n".join(md_rows)
        + "\n"
    )
    print(json.dumps(totals, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report(args.batch, args.output)
