# 阶段三：Method 数学参数绑定

日期：2026-09-17。范围为数学表达式 → 现有 SourceRef → 原 Method 调用。候选到正式产品页面的数据迁移仍是后续工作。

## 实现边界

- 首轮仍为 `functional-plan-content/v2`：`scope_steps`、`goal_plans`、`answer_from`、步骤字段和归属不变。
- 重试仍为 `functional-scope-repair/v1`：先检查原开放 Scope 边界，再绑定数学参数，整块替换后按原规则编译完整候选。
- 内部计划、MethodInvocation、Scope/Goal authority、依赖、状态读取、前置条件、返回身份、分支、闭包、事务、检查点和恢复规则均沿用原实现。
- `{step_id, return}` 原样保留。`output_targets` 仅换回原有对象引用；exact-result 禁止命名 target 等规则仍由原编译器校验。
- 配置明确指定 `source-ref` 或 `math-expression/v1`。旧录制计划及既有入口默认保持 `source-ref`；不会猜测或混用字符串编码。

## 参数契约与解析

`solver/runtime/method_math_arguments.py` 的 `MethodMathArgumentContract` 从现有 Capability 参数的 domain_type、Fact 类型和原 runtime 类型推导可接受类别；参数名、必填性、基数、allowed_refs、返回值和前提要求仍由原目录拥有。

`MethodMathArgumentResolver` 复用受限 notation parser、类型检查和有界规范化，在只读符号环境中解析表达式。对象身份来自当前 notation bundle 的来源映射，候选范围来自原授权目录；最终还要通过原绑定目录的可见性检查。参数不会新增符号、题设或自动补参。

| 参数示例 | 绑定行为 |
|---|---|
| `"parabola":"Γ"` | 原抛物线对象引用，后续仍按参数契约读取最近可见状态 |
| `"known_coefficients":"a=1"` | 本 Scope 或祖先中既有的系数条件 |
| `"point_on_ray":"N∈ray(C,D)"` | 原有定向射线条件，不能与反向射线或直线互换 |
| `"path_minimum_target":"min(sqrt(2)*MN+AN)"` | 既有路径目标，不计算其答案 |
| `"minimum_value":"min(sqrt(2)*MN+AN)=21/4"` | 已有最值数值题设，不能替代取等点/状态 |
| `"free_parameters":"b"` | 原自由参数 Symbol；完整参数基底仍由原规则验证 |
| `{"step_id":"derive_minimum","return":"minimum_expression"}` | 原精确结果引用，不重新解析 |

条件支持已证明安全的等价写法，例如 `a=1`、`1=a`、`2*a=2`。需要未证明的除数非零或根式定义域等前提时拒绝关联。显式 `min_{n}(S)` 的变量必须匹配阶段二已有 motion binding 证明；不能靠规范化丢弃错误变量。

一个表达式对应零个或多个可见、类型匹配的来源时分别报告 `functional.math_argument_unresolved` / `functional.math_argument_ambiguous`；语法、类型和变量错误报告 `functional.math_argument_invalid`。诊断进入原 authoring feedback 或 Scope retry，使用原预算与权限。

## 接线与证据

`FunctionalPlanContentCompiler` 的可选解析器在原语义校验前还原 args/output_targets。`FunctionalScopeRepairCompiler` 在原 repair envelope/authority 检查之后调用同一解析器。内部候选重新编译和检查点恢复均不传解析器。

`StrategyPlanner(..., argument_encoding="math-expression/v1")` 和 `strategy_planner_provider(..., argument_encoding="math-expression/v1")` 是显式入口，要求 notation bundle 与原授权目录相符。数学录制模式读取 `<problem_id>.functional-plan-content.json`；原录制模式仍读取原文件。

每次 attempt 继续保存原响应、规范内容、规范计划和执行证据，新增 `math-argument-bindings`：原表达式、规范引用、所属 Scope、来源 JSON pointer 和 source unit ID。保存的规范状态不依赖数学原文再次解释。

`method_math_prompt.py` 装饰原 PayloadBuilder：数学题意保留原 Scope/Goal 标识及隶属，首轮保留原 frame，retry 保留原执行状态/结果/诊断/锁定注解。目录与 Schema 只投影数学字符串的表示。机制示例位于 `internal/functional-few-shots-v2-math`，与原示例相比只有 args/output_targets 的字符串不同。旧模式 Prompt 的逐字哈希回归通过。

## 验收

- 五题人工候选、五题冻结真实候选，共十组，规范计划与完整 execution audit 全等。audit 包含 Method 实际输入、输出身份、依赖和提交版本、题设绑定账本、Goal 验证与答案。
- 同名对象、兄弟问隔离、等价改写、对象改名、错误比例、错误射线、不可见条件、歧义、自由参数、显式最值变量和精确结果引用均有反例测试。
- 同一失败计划双编码回归：仅开放原失败 Scope；检查点、权限、复用调用、重算和最终提交一致；错误数学参数不能扩大 repair 权限。
- 全量离线 Solver 门禁：**3416 passed**。初次运行发现模板空行改变旧 Prompt 哈希，已修复输出；原断言与历史基线未改动。
- 真实调用暴露的原执行器终止异常另补双编码回归；新增参数、Prompt 和测试归属回归合计 **68 passed**。同一失败计划在两种编码下均触发原状态错误，批量工具只记录异常，不改变终止或 retry 规则。
- 五题既有 Snapshot → LessonIR → VisualStepIR → 页面已重新生成；29 个公开能力覆盖门禁诊断为 0。页面为录制执行和确定性讲解，不代表新候选已接入产品数据库或正式页面。
- 另外从数学参数录制入口执行五题，与对象引用模式的完整 ExplanationSnapshot 逐字比较一致，再经原有生成器产出 LessonIR、VisualStepIR 和页面。五页滑块均带动 SVG 更新，当前服务无脚本错误。详见[双编码 Snapshot 与页面审计](validation/method-math-pages-20260917/math-encoded/equivalence.json)。

页面检查材料：[五题及公开能力页面](validation/method-math-pages-20260917/review.html)。真实模型对照及离线证据摘要见[验收报告](validation/method-math-arguments-20260917/README.md)。

复现（从 `server` 运行）：

```sh
PYTHONPATH=. .venv/bin/python tools/compare_method_math_arguments.py --phase offline --output ../internal/solver-runs/method-math-arguments-20260917
.venv/bin/python tools/run_solver_tests.py full
PYTHONPATH=. .venv/bin/python tools/compare_method_math_arguments.py --phase pages --output ../internal/solver-runs/method-math-arguments-20260917 --page-output ../docs/validation/method-math-pages-20260917/math-encoded
RUN_LLM_INTEGRATION=1 PYTHONPATH=. uv run python tools/compare_method_math_arguments.py --phase live --output ../internal/solver-runs/method-math-arguments-20260917 --workers 3
PYTHONPATH=. .venv/bin/python tools/compare_method_math_arguments.py --phase report --output ../internal/solver-runs/method-math-arguments-20260917
```

真实批次固定五题、双编码、每题各三次，使用相同冻结候选、方法集合、模型配置和原有重试策略。完成的组直接读取结果；存在已开始但结果未落盘的组会阻止自动重发，需先检查调用证据。

页面输出目录必须是新目录；已生成的验收材料可直接审阅。`report` 只汇总保存的记录，不调用模型。当前仍默认 `source-ref`，数学参数为显式启用；切换前还需解决真实对照暴露的表达稳定性问题。
