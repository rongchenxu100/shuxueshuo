# 和平二模 math 编码复测（2026-09-18）

对照原批次 [`method-math-arguments-20260917`](../method-math-arguments-20260917/README.md) 的配置，仅重跑：

- 题目：`tj-2026-heping-ermo-25`
- 编码：`math-expression/v1`
- 次数：3（sample 1–3）
- 模型：`deepseek-v4-flash`，thinking `low`，语义尝试预算 3

**不覆盖**原批次 evidence 与成绩。原始 live 目录仍为：

`internal/solver-runs/method-math-arguments-20260917/live/tj-2026-heping-ermo-25/`

本复测 evidence：

`internal/solver-runs/method-math-arguments-heping-ermo-math-recheck-20260918/`

机器可读汇总：[同目录 `live-report.json`](../../internal/solver-runs/method-math-arguments-heping-ermo-math-recheck-20260918/live-report.json)（相对仓库根）。

## 结果（相对原批次）

| | 原批次 math | 本复测 |
|---|---|---|
| sample 1 | 执行终止(1)（`functional_arg_version_drift` / `intercept_A.parabola`） | **accepted(3)** |
| sample 2 | 成功(1) | **accepted(3)** |
| sample 3 | 成功(1) | **accepted(1)** |
| 终局成功 | 2/3 | **3/3** |
| 首轮成功 | 2/3（sample1 未到成功） | 1/3 |
| `version_drift` / 执行配置中止 | 1 | **0** |
| 中断未知 | 0（本 run；原批次曾拖死进程池） | 0 |

复测中 sample 1/2 的前序失败码为 `functional.math_argument_invalid` 与 `functional.plan_content_invalid_json`（authoring 可 retry），最终均 accepted 且答案匹配。这是当前代码下的新 live 成绩，**不改写**原批次表。

## 复现

```sh
cd server
RUN_LLM_INTEGRATION=1 PYTHONPATH=. .venv/bin/python \
  tools/recheck_heping_ermo_math_live.py \
  --output ../internal/solver-runs/method-math-arguments-heping-ermo-math-recheck-20260918 \
  --workers 3
```

若目标目录已有 `result.json`，工具会按原 `live_job` 规则直接读取、不重复付费调用。
