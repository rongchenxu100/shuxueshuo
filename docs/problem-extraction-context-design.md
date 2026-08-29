# Track F：图片到 Problem 领域模型设计

## 1. 状态与范围

Track F0–F4 已完成。本文描述当前有效的图片提取、验证、投影和 Solver 接线边界，不再
保存已完成迁移的逐轮 batch 记录。

本 Track 负责：

- 从完整题图建立可追溯的 SourceObservation；
- 生成并验证 `problem-domain/v1`；
- 对失败 unit 执行局部 `problem-repair/v1`；
- promotion 为不可变 `VerifiedProblem`；
- 确定性投影 Solver ProblemIR、projection manifest 与 Planning Context。

本 Track 不负责：

- 让提取模型生成 FunctionalPlan；
- 用 expected answer 修正题面语义；
- 在 retry 中重新调用 OCR、领域提取或 projector；
- 从扁平 Solver handle 反推 source identity。

## 2. 当前权威链

```text
Source asset + selection
  -> source fingerprint
  -> Layout / OCR / Formula / Ink observations
  -> SourceObservation
  -> problem-domain/v1
  -> immutable ProblemDraft
  -> ProblemDomainValidator
  -> problem-repair/v1（仅失败 unit）
  -> VerifiedProblem
  -> ProblemDomainProjector
       -> canonical Solver ProblemIR
       -> projection manifest
       -> ProblemExtractionContext v3
  -> VerifiedSolverProblemBundle
```

权威顺序固定为：

1. 完整题图是题面语义权威；OCR 只是辅助转录和缺失定位。
2. `VerifiedProblem` 是 Scope、Entity、Fact 和 Goal 的领域权威。
3. projection manifest 只记录 `source unit -> ProblemIR handle -> runtime identity` 的确定映射。
4. Solver ProblemIR 是物理投影，不得成为反向修补领域语义的依据。
5. `ProblemPlanningContext` 与 Binding Catalog 必须从同一 accepted Bundle 派生。

## 3. `problem-domain/v1`

领域响应是一棵递归 Scope 树。每个 Scope 可拥有：

```text
scope_ref
entities[]
facts[]
goals[]
children[]
```

语义规则：

- Entity 只表达对象身份；坐标、构造、成员关系、等量和最值条件由 Fact 表达。
- Segment、Ray、Angle 和 Length 默认是值对象；只有题面赋予独立身份时才提升为 Entity。
- Goal 是附着在 Scope 上的原子答案要求，不拥有 Entity、Fact 或 child Scope。
- 当前 Scope 只能看到自身与祖先 unit，不能读取 sibling 或 descendant 私有内容。
- LLM 选择 `family_id`；代码验证 family contract，但不静默替换 family。
- Pass 1 不输出 runtime handle、scope path、valid scope、StateVersion 或 source unit ID。

所有公开集合应显式存在或由严格 Schema 规定省略语义；不能让“字段缺失”和“空集合”承担
不同但未声明的含义。

## 4. Draft、验证与局部修复

`ProblemDraft` 是一次提取响应的不可变快照。Validator 为每个可修复 unit 生成 typed
结果，至少区分：

- accepted；
- planner-repairable extraction issue；
- configuration/nonretryable issue；
- dependency blocked。

局部修复使用 `problem-repair/v1`：

```text
当前 Draft
  + 精确失败 unit
  + 题图证据切片
  + typed diagnostic
  -> replacement unit
  -> 全局重验
  -> 新 Draft revision
```

约束：

1. 已冻结 unit 不得被 replacement 静默修改。
2. replacement key 必须与 repair authority 完全一致。
3. 修复后重新验证引用、Scope 可见性、family、Goal 和投影闭包。
4. 只有全部 required unit 拥有有效 verification stamp 才能 promotion。
5. Schema、authority 或 revision 漂移 fail loud，不消耗语义 retry。

## 5. Projection 与 Bundle

Projector 只执行确定性结构转换：

- 为领域 unit 分配稳定 source identity；
- 生成 Solver ProblemIR handle；
- 记录完整 source/runtime 映射；
- 保持 Scope、Goal owner、目标类型和 family 不变；
- 生成供 Planner 和 runtime 共同验证的 semantic hash。

`VerifiedSolverProblemBundle` 至少绑定：

```text
problem revision
VerifiedProblem
Solver ProblemIR
projection manifest
validation report
source/dependency fingerprints
```

任何 revision、semantic hash、family 或映射不一致都必须在 Planner 调用前失败。

## 6. Solver 接线

Accepted Bundle 进入 Solver 后使用以下当前协议：

```text
VerifiedSolverProblemBundle
  -> planner-problem-view/v2
  -> functional-plan-content/v2
  -> canonical functional_plan/v2
  -> typed reconciliation / execution
  -> functional-goal-execution-checkpoint/v3
  -> functional-annotated-plan/v1（需要 retry 时）
  -> functional-scope-repair/v1
```

接线边界：

- Planner View 只显示 Scope-local Entity/Fact refs 和当前可见祖先内容。
- Binding Catalog 把公开 ref 绑定到 source unit、runtime node 和 typed identity。
- Plan/Retry 使用与 `VerifiedProblem` 同构的 Scope/Goal 骨架。
- Retry 只开放 Scope；开放 Scope 的完整 authored body 被替换。
- checkpoint、StateVersion、CallResult、Condition、placement 和 restore signature 留在 runtime。
- Solver retry 复用同一 Bundle revision，不重新执行图片提取。
- Macro 对 Planner/Retry 是原子 step，内部 evidence 只供 runtime、Explanation 和 debug 使用。

Retry 的完整规范见
[FunctionalPlan Scope Retry](functional-scope-retry-design.md)；当前 Solver 路线见
[数学说系统路线图](functional-planner-next-stage-roadmap.md)。

## 7. Debug 与可审计性

每个 extraction attempt 应保存真实且互不覆盖的：

```text
request metadata
source/selection fingerprint
prompt 与原始响应
parsed domain payload
validation report
repair authority / replacement（如有）
Draft revision
projection manifest
Bundle summary
token 与耗时
```

不得：

- 用最后一轮 prompt/response 覆盖早期 attempt；
- 把 expected answer 写入 prompt 或 validation authority；
- 在公开诊断中暴露内部 runtime identity；
- 用历史 artifact 冒充当前代码下的 live 验收。

## 8. 门禁

### 8.1 领域与修复

- 完整题图输入率为 100%；
- Scope/Entity/Fact/Goal Schema 严格；
- sibling visibility、父子 scope 和多 Goal 场景有确定性测试；
- repair 只修改授权 unit，无 ghost mutation；
- accepted Draft 的 semantic hash 可稳定重放。

### 8.2 Projection 与 Bundle

- source unit、ProblemIR handle 和 runtime identity 覆盖完整；
- revision、family、semantic hash 和 dependency 漂移均 fail loud；
- 同一 accepted Bundle 可重复构建相同 Planning Context 和 Binding Catalog；
- 提取模型在 Solver retry 中调用次数为 0。

### 8.3 Cold path

- recorded fixtures 通过 extraction、projection、Plan authority 和 runtime gate；
- live smoke 分离记录 extraction 与 Solver semantic attempts；
- configuration、unclassified、identity leak 和 artifact 覆盖为 0；
- 并行运行后按错误簇分析，不串行重复执行整套长测试。

## 9. 后续责任

Track F0–F4 不再新增迁移阶段。F5-F4.3B 已固化 LLM-facing 原子 Macro 边界与
`equal_length_ray_path_reduction` golden reference；F5-F4.3C 已将和平二模迁移为
`quadratic_square_path_minimum`；F5-F4.3D 已将南开迁移为
`coupled_segment_endpoint_replacement_path_minimum`；F5-F4.3E 已将河西/西青迁移为
`weighted_axis_path_minimum`，并在共享 synthetic few-shot 下各通过最终 live `1x3`。
下一项工程工作是 F5-F4.3F 旧公开 Path 能力清理与全量验收；完成后再进入 F5-F5
teaching scope 与 Track G。
