# LLM Planner 可靠性工程

## 1. 目标

可靠性工程的目标不是让 LLM 永不出错，而是让每类错误：

- 在正确边界被发现；
- 被归到正确责任层；
- 可以通过离线测试稳定复现；
- 只在确实属于计划问题时进入 LLM retry；
- 以较低 token 和延迟成本获得可靠结果。

## 2. 当前执行链

```text
ProblemIR
→ FunctionalPlan
→ typed reconciliation / placement
→ direct compiler
→ transactional execution
→ typed goal verification
→ Context / checkpoint / retry
→ PlannerOutput
```

LLM 只选择能力和公开语义参数。身份、版本、scope、binding、closure 和 runtime destination 由代码权威负责。

## 3. 关键指标

### 正确性

- Pass@1：首次计划直接通过；
- Pass@K：最多 K 轮后通过；
- answer/protocol/runtime/provenance/explanation gate；
- configuration error count；
- unclassified error count；
- identity/placement/finalization/retry/closure drift；
- failed transaction ghost write count。

### 成本

- input、reasoning、output token；
- 每次成功求解成本；
- 每个题族和每个 retry round 的成本；
- prompt fixed prefix 与 per-attempt delta；
- Pass@1 与总成本的联合变化。

### 稳定性

- 同一输入多次执行的成功率；
- root failure 分布；
- retry 是否修复原问题而未破坏 committed subgraph；
- provider 空响应、限流和 solver 错误的独立统计。

## 4. 故障分层

| 层 | 典型问题 | 处理方式 |
|---|---|---|
| Extraction | OCR、对象、条件或 scope 错 | 修提取与证据模型 |
| Catalog | 能力描述歧义、contract 缺失 | 修 capability 事实源 |
| Plan | 选错能力、漏参、角色传错 | typed issue + LLM retry |
| Identity | object/version/binding 漂移 | configuration error |
| Compiler | input/output mapping 缺失 | configuration error |
| Runtime | method 数学失败、return 缺失 | root issue + 回滚 |
| Closure | 欠定、多解、冲突 | 结构化 closure feedback |
| Goal | answer identity/evidence 不足 | 撤销 goal commit，保留 evidence |
| Downstream | Explanation/Visual/Voiceover 错 | 修对应 Context consumer |
| Provider | reasoning-only、空响应、限流 | 单独重试与统计 |

不要用 prompt 特判修复代码 authority 缺陷，也不要把模型计划错误归成 configuration drift。

## 5. 修复优先级

1. 先确认失败属于哪个 authority stage。
2. 若代码可以确定唯一答案，补 contract、validator 或 typed sidecar。
3. 若是通用语义组合缺陷，加入 executable oracle/generated gate。
4. 若是能力选择歧义，修改 catalog 文案和相邻能力负例。
5. 若是模型仍有合理多种方案，再优化 few-shot 或候选策略。
6. 最后用真实 LLM smoke 验证行为，不把 smoke 当主要发现工具。

## 6. 离线门禁

### 定向测试

每个缺陷至少留下一个最小回归：

- 原始错误输入；
- 首个失败 authority；
- expected vs actual；
- retry/rollback 行为。

### 生成式测试

旧C0.5 oracle系统覆盖：

- scope topology；
- create/reuse/transition；
- exact/latest reads；
- hidden/version/call-result edges；
- alias、placement 和 destination；
- committed/provisional retry；
- role/binding 与 closure checkpoint。

旧adapter只经过扁平FunctionalPlan及B1-B5/C0局部服务，不能继续作为scope-native覆盖证据。它由`scope-native-c0-c5/v1`与`scope-native-goal-retry/v1`直接替代：Problem/Plan/Retry三棵scope树逐项对齐，生产adapter真实经过Bundle、PlanningContext、F5-C binding、content/v2、Goal execution checkpoint与repair/v4。门禁同时覆盖唯一前序producer、显式CallResult、多个producer歧义、sibling producer拒绝、scope-local answer规范化，以及scope-level/单Goal replacement；前缀成功后第`k`个step失败、dependent suffix阻断、独立Goal继续并整体冻结、ancestor-scope producer影响多个Goal、失败Goal完整替换不修改solved Goal和provisional write零提交也属于硬门禁。Reference model保持独立，不导入生产placement、binding、retry或closure helper。

F5-F1.1进一步把LLM可见Function facade与Method runtime contract分离：prompt只出现稳定语义名，例如`parabola`和`adjacent_vertex`，compiler再映射到`quadratic`和`point`。确定性修复只能处理显式alias，或唯一未知输入与唯一缺失required参数之间可证明的一对一类型映射；optional参数、多个同类型参数和多对象候选不得参与猜测。输出对象也只能由显式target、Goal answer，或capability声明的source-fact selector唯一确定；selector必须同时通过scope可见性、F5-C对象authority和runtime type检查，零候选或多候选不得按名称兜底。pure scope step的提升同样必须由consumer Goal依赖、LCA可见性、对象authority和exact state共同证明。authority诊断应聚合相互独立的参数、输出身份、scope与DAG root issues，但任何issue存在时都不能产生部分lowered authority。

Source-fact selector同时区分内部Domain fact kind与Planner Problem View公开kind。例如参数化对称轴点内部匹配`point_on_axis`，Prompt只展示实际可引用的`axis_membership`；两者由Function facade显式映射，避免让模型学习内部命名。真实批次若provider在请求超时窗口后仍悬挂且没有sample artifact，必须终止并记录为transport failure，不能把其余样本汇总成完整验收，也不能静默补跑后覆盖原批次。

C5 symbolic closure门禁仍然有效，它验证的是参数闭合、分支数、残余自由元和checkpoint语义，不依赖LLM是否输出scope。F5-F高层路径macro接入后，C5需补macro内部closure与Goal/source provenance，同时断言内部`PathTransformation`不会出现在Planner wire；还要验证method实际产生结果但closure失败时，retry接收真实残余自由元而不是泛化编译错误，且独立Goal的closure checkpoint可继续冻结。不得用新macro替换或删减原有unique/ambiguous/inconsistent/underdetermined场景。

生成式门禁必须覆盖真实维度，不能只统计场景数量。比较器必须 fail closed，缺字段、缺 owner、多余边和错误 issue 都应失败。

### Metamorphic tests

- 重命名对象/call/scope 不改变语义；
- 改变 wire 顺序不改变 canonical graph；
- 新增 dead branch 不影响原分支；
- answer projection 不改变 computation identity；
- exact read 不被后续版本升级。

## 7. 真实 LLM smoke

真实 smoke 用于验证：

- prompt 是否可理解；
- provider 行为；
- Pass@1/Pass@K；
- retry feedback 是否有效；
- token 与延迟成本。

`scoped_functional_plan_smoke`是严格生产authority smoke：每个样本都从accepted Bundle
构建`ProblemPlanningBindingCatalog`，并把同一catalog传给payload builder与Goal retry
execution。直接调用底层reconciler且省略catalog的测试属于deterministic/debug软模式，
允许typed source暂缺，不能用于宣称F5-C、exact StateVersion或restore authority通过。
smoke报告中的`reconciliation_ok`也不单独代表可执行；最终仍必须通过compile后的
binding consumption、transaction、Goal与completion gate。

标准批次至少报告：

- 每题 raw pass 与 executable-plan pass；
- provider failure；
- 每轮 root issue；
- token 分类；
-所有 typed drift 和 ghost writes。

真实样本暴露新缺陷时，流程固定为：

```text
样本分析
→ 匿名化/缩减
→ 离线复现
→ 修权威层
→ 全量离线门禁
→ 再跑 smoke
```

逐个sample的证据读取顺序、输出超长诊断、semantic/provider attempt区分、逐轮
Plan执行图和retry authority图统一遵循
`docs/llm-sample-failure-review-guide.md`。真实失败审查不得只引用最终error；每个
semantic attempt都必须按scope/Goal画出Plan依赖，标注实际runtime结果或明确说明
未执行。

## 8. Retry 设计

- freeze的权威单位是完成全部answer/runtime/closure/provenance gate的Goal，以及独立验证通过的scope-level execution block；
- retry始终发送上一版完整canonical `functional_plan/v2`，包含全部scope、`scope.steps`和Goal steps；执行树通过`step_id`关联，不重复复制计划定义；
- solved Goal在retry执行树中携带逐step实际输入、输出、状态、错误和`published_results`，但标记`editable=false`；
- failed Goal的逐step实际输入、输出、状态、typed error及blocked suffix全部进入反馈；该Goal内部没有call级冻结，模型可以完整重写全部steps；
- blocked dependents不生成次生root issue，独立sibling Goal继续执行；
- scope-level步骤块失败时按typed dependency确定consumer Goal repair group，不因共享根Entity扩大范围；
- runtime actual value/form/free symbols优先于静态预测；compile失败不得伪造输出，closure feedback说明target、status、branch count、剩余自由元和来源；
- retry payload按Problem的scope/Goal树组织，不再暴露平面的repair/validated/locked call列表；
- prompt不暴露typed ids、runtime path或expected answer，跨Goal绑定只允许使用`published_results`。

## 9. Prompt 成本策略

当前原则：

- system 保存协议规则；user 只保存题目数据和本轮反馈；
- catalog 使用 compact JSON；
- DeepSeek 使用 JSON Output；
- Pass 1 关闭 thinking，重试使用低 reasoning effort；
- temperature 取确定性设置；
-暂不通过删减 capability 描述牺牲可选择性；
-缓存和 goal-reachable catalog 裁剪作为后续独立优化。

任何成本优化都必须同时比较 Pass@1、Pass@K 和总成功成本。

## 10. 候选优化（Track E）

Track E 在 F/G 完成后进行。它可以：

- 生成少量 FunctionalPlan 候选；
- 用 typed preflight 和低成本执行信号排序；
- 选择最可能完成 required goal closure 的候选。

候选选择不能绕过 transactional authority，也不能用 expected answer 排序。

## 11. 发布门禁

- 全量 solver tests 通过；
- scope-native C0-C5与Goal retry generated gate零mismatch；
- 五题真实 smoke 达到当前 acceptance；
- configuration/unclassified error 为零；
-所有 authority drift 为零；
- provider failure 单独归因；
- `git diff --check` 通过。

## 12. 相关文档

- `docs/functional-planner-next-stage-roadmap.md`
- `docs/scope-native-c0-c5-executable-gate.md`
- `docs/capability-authoring-guide.md`
- `docs/llm-context-model-design.md`
