"""Render only saved live results; never invoke a provider or change acceptance."""

import json
from hashlib import sha256
from html import escape
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BATCH = ROOT / "internal/solver-runs/math-notation-provider-comparison-20260916-153340"
LABELS = ["和平一模", "和平二模", "河西一模", "南开一模", "西青一模", "K 倍四边形", "函数量词"]


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def total(values):
    return sum(values) if all(v is not None for v in values) else None


def n(value):
    return "未提供" if value is None else f"{value:,}"


def detail(usage, group, field):
    return (usage.get(group) or {}).get(field)


def main():
    frozen = read(BATCH / "frozen-comparison.json")
    timings = read(BATCH / "timings.json")
    assert set(timings) == {"deepseek", "doubao"}, "both batches must finish"
    rows, aggregates, diagnostics = [], {}, {}
    for provider in ("deepseek", "doubao"):
        summary = read(BATCH / provider / "batch-summary.json")
        assert summary["completed"] == 7
        current = []
        diagnostics[provider] = {}
        for case, label in zip(frozen["cases"], LABELS):
            source = BATCH / provider / case
            result = summary["results"][case]
            call = read(source / "call.json", {})
            usage = call.get("usage") or {}
            attempts = call.get("provider_attempts", [])
            reasoning = total([detail(a.get("usage") or {}, "completion_tokens_details", "reasoning_tokens") for a in attempts]) if attempts else None
            cache = total([(a.get("usage") or {}).get("prompt_cache_hit_tokens", detail(a.get("usage") or {}, "prompt_tokens_details", "cached_tokens")) for a in attempts]) if attempts else None
            case_frozen = read(source / "frozen.json")
            for path, digest in case_frozen["template_files"].items():
                assert frozen["code_and_templates"][path] == digest
            for name, digest in case_frozen["implementation_files"].items():
                assert frozen["code_and_templates"]["server/shuxueshuo_server/problem_understanding/" + name] == digest
            for name, digest in frozen["inputs"][case].items():
                assert sha256((source / "input-fixture" / name).read_bytes()).hexdigest() == digest
            parsed = read(source / "parsed.json", {})
            diff = read(source / "diff.json", {})
            acceptance = read(source / "acceptance.json", {})
            raw_file = source / "raw-response.txt"
            row = {"case": case, "label": label, "provider": provider,
                   "model": call.get("response_model", frozen["providers"][provider]["model"]),
                   "passed": result["passed"], "strict_passed": result.get("strict_semantics_passed", False),
                   "elapsed_seconds": result.get("elapsed_seconds"), "latency_ms": call.get("latency_ms"),
                   "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                   "total_tokens": usage.get("total_tokens"), "reasoning_tokens": reasoning,
                   "cached_input_tokens": cache, "usage_complete": call.get("usage_complete", False),
                   "network_attempts": result.get("network_attempts"), "finish_reason": call.get("finish_reason"),
                   "continuation": result.get("continuation"), "match_correct": result.get("match_correct"),
                   "source_dir": str(source), "raw_sha256": sha256(raw_file.read_bytes()).hexdigest() if raw_file.exists() else None}
            current.append(row)
            diagnostics[provider][case] = {"summary": result, "ir_issues": parsed.get("reports", {}).get("ir", {}).get("issues", []),
                                           "match": parsed.get("reports", {}).get("match"), "comparison": diff, "acceptance": acceptance}
        rows.extend(current)
        elapsed = [r["elapsed_seconds"] for r in current]
        aggregates[provider] = {"model": frozen["providers"][provider]["model"],
            "passed": sum(r["passed"] for r in current), "strict_passed": sum(r["strict_passed"] for r in current), "cases": 7,
            "pass_rate": sum(r["passed"] for r in current) / 7,
            "wall_seconds": timings[provider]["wall_seconds"],
            "sum_case_seconds": round(sum(elapsed), 3), "mean_case_seconds": round(mean(elapsed), 3), "median_case_seconds": round(median(elapsed), 3),
            **{field: total([r[field] for r in current]) for field in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "cached_input_tokens", "network_attempts")},
            "usage_complete": all(r["usage_complete"] for r in current)}
    metrics = {"live_runs": True, "code_changed_during_run": False, "concurrency": 3,
               "frozen_inputs_verified": True, "aggregates": aggregates, "rows": rows}
    (HERE / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    (HERE / "diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 七题真实集成测试：DeepSeek 与 Doubao", "",
        "同一代码、Prompt、Schema、七题图片、金标及验收政策，各运行一次。每批并发上限 3，两家顺序执行，thinking enabled / low，300 秒超时、16,384 输出 token 上限。每题一次语义调用，最多两次受控网络尝试；无自动修复、复核或供应商回退。", "",
        "[完整模型输出对照](outputs.html) · [用量数据](metrics.json) · [验收差异](diagnostics.json) · [失败原因与统计解读](analysis.md)", "",
        "| 供应商 / 模型 | 通过率 | 严格通过 | 输入 token | 输出 token（含思考） | 总 token | 其中思考 | 整批秒 | 单题平均秒 | 单题中位秒 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for p, a in aggregates.items():
        lines.append(f"| {p} / {a['model']} | {a['passed']}/7（{a['pass_rate']:.1%}） | {a['strict_passed']}/7 | {n(a['input_tokens'])} | {n(a['output_tokens'])} | {n(a['total_tokens'])} | {n(a['reasoning_tokens'])} | {a['wall_seconds']:.2f} | {a['mean_case_seconds']:.2f} | {a['median_case_seconds']:.2f} |")
    lines += ["", "| 题目 | DeepSeek 结果 | 秒 | 输入 / 输出 token | Doubao 结果 | 秒 | 输入 / 输出 token |", "| --- | --- | ---: | ---: | --- | ---: | ---: |"]
    for case, label in zip(frozen["cases"], LABELS):
        a, b = [next(r for r in rows if r['case'] == case and r['provider'] == p) for p in ("deepseek", "doubao")]
        lines.append(f"| {label} | {'通过' if a['passed'] else '未通过'} | {a['elapsed_seconds']:.2f} | {n(a['input_tokens'])} / {n(a['output_tokens'])} | {'通过' if b['passed'] else '未通过'} | {b['elapsed_seconds']:.2f} | {n(b['input_tokens'])} / {n(b['output_tokens'])} |")
    lines += ["", "输出 token 已包含思考 token，不重复相加。总 token 按供应商实际 usage 统计；未提供的思考／缓存明细记为未知。两家的 tokenizer、图片计量和缓存机制不同，token 数不能直接等同于费用。整批时间包含各批准备检查和并发执行，单题时间包含网络响应及本地解析验收；并发时不能把单题耗时之和当作批次时间。", "",
        "K 题只有完整提取并正确报告缺图、触发阻断才算成功；通过不代表可进入 Solver。历史回放成绩没有混入本轮结果。此处仅一轮七题对照，结论限于本次样本。", "",
        "完整请求、图片和金标哈希、原始响应、解析、失败差异、耗时及用量保存在 `internal/solver-runs/math-notation-provider-comparison-20260916-153340`。"]
    (HERE / "README.md").write_text("\n".join(lines) + "\n")
    def esc(value):
        return escape(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2))
    cards = []
    for case, label in zip(frozen['cases'], LABELS):
        pair = []
        for p in ('deepseek', 'doubao'):
            r = next(r for r in rows if r['case'] == case and r['provider'] == p)
            raw = (Path(r['source_dir']) / 'raw-response.txt')
            pair.append(f"<article><h3>{p} <span class={'ok' if r['passed'] else 'bad'}>{'通过' if r['passed'] else '未通过'}</span></h3><p>{r['elapsed_seconds']:.2f} 秒 · 输入 {n(r['input_tokens'])} · 输出 {n(r['output_tokens'])} token</p><details><summary>校验差异与阻断状态</summary><pre>{esc(diagnostics[p][case])}</pre></details><pre>{esc(raw.read_text() if raw.exists() else '未收到有效响应')}</pre></article>")
        cards.append(f"<section><h2>{label}</h2><div class=pair>{''.join(pair)}</div></section>")
    table = '<table><tr><th>模型</th><th>通过率</th><th>整批耗时</th><th>输入 token</th><th>输出 token</th><th>总 token</th></tr>'
    for p, a in aggregates.items():
        table += f"<tr><td>{esc(a['model'])}</td><td>{a['passed']}/7</td><td>{a['wall_seconds']:.2f} 秒</td><td>{n(a['input_tokens'])}</td><td>{n(a['output_tokens'])}</td><td>{n(a['total_tokens'])}</td></tr>"
    table += '</table>'
    analysis = HERE / 'analysis.md'
    if analysis.exists():
        table += '<details><summary>失败原因与统计解读（不改变真实成绩）</summary><pre>' + esc(analysis.read_text()) + '</pre></details>'
    (HERE / 'outputs.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>七题双模型真实测试对比</title><style>body{font:16px/1.65 system-ui;color:#182439;max-width:1500px;margin:36px auto;padding:0 24px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:18px;border-radius:8px;font:14px/1.6 ui-monospace,monospace}section{border-top:2px solid #ccd2db;margin-top:32px}.ok{color:#087b50}.bad{color:#b43e2c}summary{cursor:pointer}h1{margin-bottom:8px}@media(max-width:850px){.pair{grid-template-columns:1fr}table{font-size:13px}}</style><h1>七题双模型真实集成测试</h1><p>同一冻结输入，各运行一轮；每批并发 3。以下为模型原始返回，未自动修复。输出 token 包含思考 token；候选尚未接入 Solver。</p>' + table + ''.join(cards) + '</html>')
    print(json.dumps(aggregates, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
