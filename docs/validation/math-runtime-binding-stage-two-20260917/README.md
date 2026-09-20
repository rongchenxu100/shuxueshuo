# 阶段二冻结证据回放与简洁输入审阅

十组回放全部通过：五题人工样例、五题冻结真实候选。逐目标核对答案和全部合法分支，并检查实际输入、提交状态版本与来源作用域。

**本目录是离线回放证据，不是当前产品准入结果。** 回放使用测试侧的合成授权；历史 `confirmed` 没有被改写为当前复核。当前产品检查由页面按钮或 API 单独触发。无模型调用。

旧输入由当前生产 `StrategyPayloadBuilder.build_scoped()` 生成；新输入由本次代码生成器生成。运行时适配只读取新候选，旧 fixture 只用于旧输入对照、计划选择与答案断言。

| 题目 | 旧题目字符 | 新题目字符 | 题目段减少 | 审阅文件 |
|---|---:|---:|---:|---|
| tj-2026-nankai-yimo-25 | 5,189 | 902 | 82.6% | [旧输入](tj-2026-nankai-yimo-25/existing-problem.json) · [新输入](tj-2026-nankai-yimo-25/recorded/compact-problem.json) · [方法](tj-2026-nankai-yimo-25/recorded/compact-methods.json) · [覆盖](tj-2026-nankai-yimo-25/recorded/coverage.json) · [回放](tj-2026-nankai-yimo-25/recorded/execution-audit.json) |
| tj-2026-heping-ermo-25 | 4,413 | 795 | 82.0% | [旧输入](tj-2026-heping-ermo-25/existing-problem.json) · [新输入](tj-2026-heping-ermo-25/recorded/compact-problem.json) · [方法](tj-2026-heping-ermo-25/recorded/compact-methods.json) · [覆盖](tj-2026-heping-ermo-25/recorded/coverage.json) · [回放](tj-2026-heping-ermo-25/recorded/execution-audit.json) |
| tj-2026-heping-yimo-25 | 4,068 | 688 | 83.1% | [旧输入](tj-2026-heping-yimo-25/existing-problem.json) · [新输入](tj-2026-heping-yimo-25/recorded/compact-problem.json) · [方法](tj-2026-heping-yimo-25/recorded/compact-methods.json) · [覆盖](tj-2026-heping-yimo-25/recorded/coverage.json) · [回放](tj-2026-heping-yimo-25/recorded/execution-audit.json) |
| tj-2026-hexi-yimo-25 | 4,271 | 675 | 84.2% | [旧输入](tj-2026-hexi-yimo-25/existing-problem.json) · [新输入](tj-2026-hexi-yimo-25/recorded/compact-problem.json) · [方法](tj-2026-hexi-yimo-25/recorded/compact-methods.json) · [覆盖](tj-2026-hexi-yimo-25/recorded/coverage.json) · [回放](tj-2026-hexi-yimo-25/recorded/execution-audit.json) |
| tj-2026-xiqing-yimo-25 | 3,542 | 647 | 81.7% | [旧输入](tj-2026-xiqing-yimo-25/existing-problem.json) · [新输入](tj-2026-xiqing-yimo-25/recorded/compact-problem.json) · [方法](tj-2026-xiqing-yimo-25/recorded/compact-methods.json) · [覆盖](tj-2026-xiqing-yimo-25/recorded/coverage.json) · [回放](tj-2026-xiqing-yimo-25/recorded/execution-audit.json) |

字符数统一使用 `json.dumps(ensure_ascii=False, separators=(",", ":"), sort_keys=True)` 的 Unicode 字符数。只比较题目段，不能据此声称整个请求的压缩比例。每题方法段体积另存 `size-statistics.json`。无匹配 tokenizer，token 保持 null。

每题 `recorded/` 与 `authored/` 均包含原候选、编译对象/关系、canonical input、初始状态、来源映射、简洁输入、方法签名、覆盖清单和受信计划的执行审计。`local-input-after-replay.json` 展示当前问及祖先条件和已提交的可见结果。

南开旧计划把最值步骤放在父问；新候选仅在两个子问声明最值。测试侧保留方法和数学选择，在两个子问分别绑定该步骤，未把子问条件提升到父问。

方法签名的参数与返回值来自执行能力注册表；数学前提由同一能力 ID 的数学说明补充。它们是审阅文档，尚不是新的可执行步骤语言。

复现：在 `server` 执行 `PYTHONPATH=. .venv/bin/python tools/replay_math_runtime_binding.py --output ../docs/validation/math-runtime-binding-stage-two-20260917`。
