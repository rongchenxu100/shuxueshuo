# 数学说系统路线图

## 总目标

建立一条从题目图片到课程页的可追溯主链：

```text
图片 / PDF
  -> SourceObservation
  -> VerifiedProblem + projection manifest
  -> ProblemPlanningContext + FunctionalPlan
  -> transactional runtime + VerifiedFunctionalPlanExecution
  -> Explanation / Diagram / Voiceover / Animation
  -> 课程页
```

稳定冷路径完成后，再实施最终 artifact cache、并发去重和条件式 Best-of-N。

## 阶段状态

| Track | 状态 | 当前结果 |
| --- | --- | --- |
| A–D：Solver 基础 | `COMPLETE` | FunctionalPlan、typed state、事务执行和默认入口完成 |
| F0–F4：图片提取 | `COMPLETE` | source identity、observation、domain extraction、patch authority 完成 |
| F5-A–F5-F3：Scoped Solver | `COMPLETE` | Bundle、Planning View、binding、增量执行和 Scope Retry 完成 |
| F5-F4.1–F5-F4.3A：Macro runtime 基础 | `COMPLETE` | preparation、bounded search、typed binding、companion output authority 完成 |
| F5-F4.3B：原子 Macro golden reference | `COMPLETE` | equal-length 四 Fact 固定契约、shadow/replay/restore 与单根诊断门禁完成 |
| F5-F4.3C：和平二模正方形 Macro | `COMPLETE` | 三公开输入、两公开输出；离线门禁及最终 live `1x3` 发布验收通过 |
| F5-F4.3D：南开耦合路径 Macro | `COMPLETE` | 两公开输入、两公开输出；共享 Scope、构造点诊断、few-shot hash 与最终 live `1x3` 通过 |
| F5-F4.3E：加权路径原子 Macro | `COMPLETE` | 单路径 Fact 输入、单表达式输出；河西/西青最终 live 各 `1x3` 均首轮通过 |
| F5-F4.3F：旧能力清理与全量验收 | `NEXT` | 物理删除公开 Path 内部类型与兼容链，运行 full gate 和 Planner-only `5x3` |
| F5-F5：Teaching scope | `AFTER F4.3` | 从 verified execution 派生教学归属并退役剩余兼容入口 |
| G：Post-solver Context | `AFTER F5` | Explanation、Diagram、Voiceover、Animation Context |
| E：端到端优化 | `AFTER F/G` | cache、最小失效、并发去重、条件式 Best-of-N |

已完成迁移的逐提交过程、旧协议说明和 batch 流水不保留在当前路线图；Git 历史与
`internal/solver-runs/` 是历史证据源。

## 当前生产链

```text
VerifiedSolverProblemBundle
  -> planner-problem-view/v2
  -> functional-plan-content/v2
  -> canonical functional_plan/v2
  -> typed reconciliation + incremental execution
  -> functional-goal-execution-checkpoint/v3
  -> functional-annotated-plan/v1          # 需要 retry 时
  -> functional-scope-repair/v1            # 完整 Scope replacement
  -> restore / replay / final transaction
  -> VerifiedFunctionalPlanExecution
```

当前边界：

1. `VerifiedProblem` 持有 scope、Entity、Fact 和 Goal 的题面语义权威。
2. `ProblemPlanningContext` 只投影当前 scope 与祖先可见内容，结构上排除 sibling 泄漏。
3. `FunctionalPlanAuthorityFrame` 固定 scope 树、Goal owner、目标与可用 capability。
4. LLM 首轮只提交各 scope/Goal 的 authored steps 与 `answer_from`。
5. Retry 编辑权只开在 Scope；开放 Scope 的 `scope_steps` 和全部直属 Goal body 整块替换。
6. runtime 持有 placement、typed binding、checkpoint、restore、transaction 和 provenance。
7. Macro 对 LLM 始终是一个原子 step；内部 Method、candidate、winner 和 witness 不进入 Plan/Retry wire。

## 当前工作：F5-F4.3 原子路径 Macro

目标不是建立一套可由 LLM 编辑的路径子图 DSL，而是让复杂路径能力保持原子 Planner
接口，并在 runtime 内完成有界搜索、数学验证和 clean replay。

实施顺序：

1. **F4.3B 原子边界与 golden reference（COMPLETE）**
   - 固定一个 Macro 对应一个 canonical Plan step；
   - 固定 public arg 与 code-owned hidden arg，不再按候选数动态隐藏角色；
   - `equal_length_ray_path_reduction` 的四个公开 Fact 与四个 code-owned role 已固定；
   - 覆盖结构不匹配、非等价歧义、shadow 隔离、clean replay 和 restore；
   - Macro 失败只向 Retry 投影一个公开根诊断。
2. **F4.3C 和平二模正方形路径（COMPLETE）**
   - 新增 `quadratic_square_path_minimum` 原子入口；
   - 公开参数固定为 `parabola + path_minimum_target + square`；
   - midpoint/center/axis/moving/fixed roles 由代码从结构化关系唯一解析；
   - `attainment_point` 的降维后动点 identity 由代码绑定，Planner 只用 StepResultRef 消费；
   - 删除该 family 对公开路径降维、locus handoff 和 broken-path 链的依赖。
   - 最终 live `1x3` 为 `3/3` completion；一次对象身份错误由 Scope Retry 正确修复，
     无 authority drift、ghost write、identity leak 或未分类异常。
3. **F4.3D 南开路径（COMPLETE）**
   - 迁移耦合线段端点替换和单动点路径；
   - 删除 LLM-facing 两阶段路径链；
   - release smoke 五题统一使用 synthetic `quadratic_constraints_vertex`
     few-shot，禁止把当前题抽取出的机制片段喂回同题；
   - 公平条件下最终 live `1x3` 为 `3/3`，三份均首次 response 通过且
     few-shot payload hash 一致。
4. **F4.3E 加权路径（COMPLETE）**
   - 新增 `weighted_axis_path_minimum` 原子入口，只公开一个
     `path_minimum_target` 输入和一个 `minimum_expression` 输出；
   - typed path terms 无损保存权重与 canonical endpoints，代码解析端点、参数、定义域
     和登记过的三角形 profile；
   - kernel 内完成 transform、straightening、取等可达性与定义域边界分支，不公开
     auxiliary Point/Line 或 `PathTransformation`；
   - 河西/西青公平 live 各 `3/3`，六份均首次 response 完成。
5. **F4.3F 清理与验收**
   - 从 prompt、catalog、Schema、fixture 和 few-shot 删除公开 Path 内部类型；
   - 删除旧 capability、recipe、Explanation/Visual fallback 与孤儿注册；
   - 运行 Solver full gate 和并行 Planner-only `5x3` live smoke。

详细契约与分段门禁见 [路径最值原子 Macro 设计](path-minimum-macro-redesign.md)。

## F5-F5：Teaching scope

原子路径 Macro 完成后，教学链只消费已验证的执行证据：

- 教学归属使用 `plan_scope_id` / `semantic_owner_scope_id`，不从物理 `execution_scope_id` 反推；
- failed、provisional、dead-pruned 和 shadow candidate 不进入学生内容；
- Macro 内部 evidence 可投影为讲解步骤，但不会反向变成 Planner-authored steps；
- Explanation、Visual 和 animation 使用同一 problem revision 与 provenance。

## Track G：解题后 Context

```text
VerifiedFunctionalPlanExecution
  -> LessonExplanationContext
  -> DiagramContext
  -> VoiceoverContext
  -> AnimationContext
  -> compiled lesson page
```

退出条件：

- 五题均能从 verified solver artifact 编译课程页；
- failed、provisional 和 shadow 数据不进入学生内容；
- 上游 Context 变化会使下游显式 stale；
- 至少一题完成图片到课程页的真实冷路径；
- latency、token、模型调用和 artifact dependency 可审计。

## Track E：端到端优化

F/G 冷路径稳定后依次实施：

1. 最终 Lesson artifact cache；
2. 相同 dependency key 的并发构建去重；
3. extraction、solver、lesson semantic 和 render 的分层缓存；
4. 仅在 cold miss 且单候选未通过门禁时启用 Best-of-N；
5. 只缓存通过完整门禁的 winner。

## 全局不变量

1. Context state 是事实源；prompt、review 和 debug 只是 projection 或 artifact。
2. Context 不可变，并记录 parent、dependency 和 attempt authority。
3. `VerifiedProblem` 是图片提取的语义权威；Solver ProblemIR 是确定性物理投影。
4. `PlannerStateContext` 只管理动态执行状态，不回写题目语义。
5. expected answer 只用于测试，不进入 prompt、validator 或 retry。
6. LLM 边界必须有 strict Schema、确定性 validator、budget 和 fail-closed 行为。
7. Retry 只开放 Scope，不向 LLM 暴露 Goal/Step 权限或 checkpoint bookkeeping。
8. Macro 内部复杂性不得转化为 Planner/Retry wire 复杂性。
9. 下游不得从显示文案、runtime handle 或 path 猜测 identity。
10. F/G 验收运行完整冷路径；cache 与 Best-of-N 留到 Track E。
