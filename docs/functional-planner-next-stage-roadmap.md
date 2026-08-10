# 数学说系统路线图

## 总目标

建立一条从题目图片到课程页的可追溯主链：

```text
图片 / PDF
  -> Source fingerprint
  -> Layout / OCR / Formula / Ink observation
  -> Problem domain extraction
  -> VerifiedProblem + projection manifest
       -> goal-scoped ProblemPlanningContext -> FunctionalPlan
       -> canonical Solver ProblemIR -> ContextBuilder
  -> Transactional Solver
  -> Explanation / Diagram / Animation
  -> 课程页
```

完整冷路径通过后，再做最终页面缓存、并发去重和条件式 Best-of-N。

## 阶段状态

| Track | 状态 | 当前结果 |
| --- | --- | --- |
| A：Functional parity | `COMPLETE` | FunctionalPlan 与 authored fixture 对齐 |
| B：Typed state authority | `COMPLETE` | typed identity、StateVersion、placement、finalization、retry |
| C：Transactional execution | `COMPLETE` | binding ledger、逐 call 事务、symbolic closure、provenance |
| D：Functional default | `COMPLETE` | FunctionalPlan 为唯一规划协议，StepIntent 已退役 |
| F0：Gold corpus | `COMPLETE` | 五题原图、selection、evidence annotation、semantic diff |
| F1：Source identity | `COMPLETE` | source/selection/dependency fingerprint 与 immutable Context |
| F2：Source observation | `COMPLETE` | Layout、OCR、公式、笔迹、artifact ledger、review pack |
| F3：Domain extraction | `COMPLETE` | 豆包完整题图提取、嵌套 scope、不可变 ProblemDraft |
| F4：Validation / patch authority | `COMPLETE` | freeze、局部 patch retry、VerifiedProblem、Context v3 |
| F5：Scoped planning / Solver lifecycle | `IN PROGRESS` | F5-A Bundle authority与F5-B scope-native planning projection完成，下一步为typed binding |
| G：Post-solver Context | `AFTER F5` | Explanation、Diagram、Voiceover、Animation Context |
| E：End-to-end optimization | `AFTER F/G` | 最终 artifact cache、最小失效、条件式 Best-of-N |

已完成阶段的逐轮 finding 不再保留在路线图中；历史证据由 Git 与 batch artifact 保存。

## Track F：图片题目提取

当前权威链：

```text
F2完整题图与SourceObservation
  -> 豆包输出problem-domain/v1
  -> immutable ProblemDraft
  -> ProblemDomainValidator
  -> 冻结已验证unit
  -> problem-repair/v1局部patch
  -> VerifiedProblem
  -> ProblemDomainProjector
  -> canonical Solver ProblemIR + projection manifest
  -> ProblemExtractionContext v3
```

关键决策：

1. 完整题图是语义权威，OCR只作辅助转录与缺失定位。
2. scope在领域模型中递归嵌套；实体、事实和目标归属于其最小有效scope。
3. LLM选择`family_id`；代码只验证family contract，不自动换family。
4. Entity只表达身份；坐标、构造、成员关系、等量和最值均由Fact表达。
5. Segment、Ray、Angle和Length是值对象；只有题面赋予独立身份时才提升为Entity。
6. Pass 1不输出fact/goal unit id、runtime handle、scope_id、valid_scope或value type。
7. Draft建立后只允许局部`problem-repair/v1`，不再接受整题替换。
8. 只有全部unit拥有有效verification stamp时才能promotion为`VerifiedProblem`。
9. 投影器只展平scope与生成runtime identity，不得补数学事实或改变family。
10. 提取smoke只运行领域校验、ContextBuilder和family pure runtime preflight，不调用Planner或完整Solver。

当前证据：

- 当前全量Solver离线回归：`1587 passed, 12 skipped`；`git diff --check`通过。
- 豆包请求统一流式接收，在首个完整顶层JSON结束；Pass 1和retry不再等待尾部重复输出。
- 2026-08-10最终`5x3`得到15/15 accepted、15/15 family一致和15/15 Solver ProblemIR投影一致；最终canonicalizer对同批live artifact重放后domain semantic hash为15/15一致。
- 南开最终补充批次3/3首轮严格通过，河西修复批次1/1首轮严格通过；完整题图输入率100%，Planner与完整Solver调用数均为0。
- 配置错误、未分类错误、patch drift和provider长尾均为0。F3/F4据此关闭，F5解锁。

详细设计和门禁见 [problem-extraction-context-implementation-plan.md](problem-extraction-context-implementation-plan.md)。

## Track F5：Scoped Planning与Solver生命周期接线

```text
accepted ProblemExtractionContext v3
  -> VerifiedSolverProblemBundle
       -> VerifiedProblem -> goal-scoped ProblemPlanningContext -> FunctionalPlan
       -> Solver ProblemIR -> ContextBuilder / runtime identity
       -> projection manifest连接source unit与runtime handle
  -> typed reconciliation / PlannerStateContext
  -> transactional runtime
  -> answer、protocol、runtime、provenance gate
```

F5不修改提取语义，也不改写现有扁平Solver ProblemIR。它建立三个明确边界：

1. `VerifiedProblem`是scope、实体、Fact和Goal的语义权威；
2. `ProblemPlanningContext`是按Goal临时派生的Planner视图，只包含当前scope与祖先可见unit，结构上排除sibling；
3. Solver ProblemIR是ContextBuilder与runtime的物理投影，projection manifest负责`source_unit_id -> ProblemIR handle -> runtime identity`映射。

`FunctionalPlan`继续使用`functional_plan/v1`和现有`SemanticRef`。服务端catalog sidecar把每个ref绑定到source unit与runtime handle；LLM不能发明scope或跨sibling引用。call的声明scope由Goal视图约束，实际execution scope仍由现有B2 placement根据typed dependency和LCA计算。同一个根Entity在不同子问中的Fact投影为独立scope-local `StateVersion`，不会因handle相同而合并状态。

实现顺序：

1. **F5-A Bundle authority（COMPLETE）**：从accepted Context加载VerifiedProblem、内嵌manifest的Solver projection envelope和validation report；交叉校验artifact、revision、semantic hash、family与完整source/runtime映射。pending、blocked或authority token漂移全部fail loud。
2. **F5-B Scoped planning view（COMPLETE）**：从嵌套scope树生成一个全题PlanningContext、共享祖先摘要与逐Goal视图；每个Goal只声明owner到root的可见scope，`semantic_reads`与可见scope refs严格相等，F5-C通过按Goal authority API消费；source/runtime覆盖与跨sibling来源在投影时fail loud。
3. **F5-C Planner binding**：将SemanticRef确定映射到source unit、MathObjectId和StateVersion；跨sibling、未知source unit或revision漂移在编译前失败。
4. **F5-D Retry/provenance**：checkpoint、repair cone和result记录problem revision/hash及实际消费的source units；Solver retry不重新提取题目。
5. **F5-E Cold path**：默认入口从accepted bundle运行Planner与transactional Solver，并删除Planner只读扁平ProblemIR的旧prompt路径。

F5-A/B当前证据：五题accepted Context可确定加载并各生成一个`problem-planning-context/v1`；南开/和平二模分别生成6/4个GoalView，其余三题各3个。F5-A/B定向联合门禁`81 passed`，全量Solver回归`1587 passed, 12 skipped`。PlanningContext为纯内存投影，不调用OCR、豆包、domain validator/projector、ContextBuilder、Planner或完整Solver；prompt payload不包含source unit、runtime handle、artifact、Bundle token或typed state identity。SemanticRef按source local id、scope、Fact语义和answer边界稳定生成，完整覆盖所有非scope runtime node；shared scope只序列化一次，answer ref不会进入其他Goal的输入集合。prompt schema具有checked-in JSON快照；F5-C必须使用`input_authorities_for_goal()`和`answer_authority_for_goal()`，不得直接消费全局sidecar。F5-B尚未接入默认`StrategyPayloadBuilder`，生产Planner输入切换留到F5-E。

退出条件是五题各3份完成图片到verified Solver结果的冷路径，且answer、protocol、runtime、binding、closure和provenance gate全部通过；提取模型不被重复调用，跨scope identity drift和失败事务幽灵write均为0。

## Track G：解题后 Context

```text
PlannerStateContext
  -> LessonExplanationContext
  -> DiagramContext
  -> VoiceoverContext
  -> AnimationContext
  -> compiled lesson page
```

目标是让教学步骤、图形对象、旁白和动画均具有不可变Context、显式dependency与typed validation。F5完成默认Solver接线后，G消费同一`problem_revision_id`下的VerifiedProblem、PlannerStateContext与runtime provenance。

退出条件：

- 五题均能从verified solver artifact编译课程页；
- failed、provisional和alias call不进入学生内容；
- 上游Context变化会使下游显式stale；
- 至少一题完成图片到课程页的真实冷路径；
- latency、token、模型调用和artifact dependency可审计。

## Track E：端到端优化

F/G冷路径稳定后依次实施：

1. 最终Lesson artifact cache；
2. 相同dependency key的并发构建去重；
3. extraction、solver、lesson semantic和render的分层缓存；
4. 仅在cold miss且单候选未通过门禁时启用Best-of-N；
5. 只缓存通过完整门禁的winner。

## 全局不变量

1. Context state是事实源；prompt、review和debug只是projection或artifact。
2. Context不可变，并记录parent、dependency和attempt authority。
3. `VerifiedProblem`是图片提取的语义权威；Solver ProblemIR是确定性投影。
4. 扁平Solver ProblemIR不是Planner的唯一语义输入；Planner视图只能从VerifiedProblem确定派生。
5. `PlannerStateContext`只管理动态执行状态，不回写或替代VerifiedProblem的题目语义。
6. expected answer只用于测试，不进入prompt、validator或retry。
7. LLM边界必须有strict schema、确定性validator、budget和fail-closed行为。
8. 下游不得从显示文案、runtime handle或path猜测缺失identity。
9. F/G验收运行完整冷路径；缓存与Best-of-N留到Track E。
