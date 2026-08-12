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
| F5：Scoped planning / Solver lifecycle | `IN PROGRESS` | F5-A/B/C/D/E完成；F5-F统一Problem/Plan/Retry的scope树并承担最终5x3可靠性门禁 |
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

- 当前全量Solver离线回归：`1707 passed, 12 skipped`。
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

F5-E切换期间`FunctionalPlan`继续使用`functional_plan/v1`和现有`SemanticRef`。服务端catalog sidecar把每个ref绑定到source unit与runtime handle；LLM不能跨sibling引用，实际execution scope仍由现有B2 placement根据typed dependency和LCA计算。同一个根Entity在不同子问中的Fact投影为独立scope-local `StateVersion`，不会因handle相同而合并状态。

F5-F不作为一个大改动一次落地，而是拆成协议、执行、retry、宏和教学归属五个可独立验收的子阶段。Problem、Plan与Retry统一使用同一棵scope/Goal树；scope骨架和Goal identity来自VerifiedProblem，LLM只在对应Goal下编写步骤。增量执行以Goal完成为冻结边界，失败Goal允许完整重写自己的思路；family-specific path macro独立替换`PathTransformation`；最后由同一scope权威生成教学结果并删除v1兼容。

实现顺序：

1. **F5-A Bundle authority（COMPLETE）**：从accepted Context加载VerifiedProblem、内嵌manifest的Solver projection envelope和validation report；交叉校验artifact、revision、semantic hash、family与完整source/runtime映射。pending、blocked或authority token漂移全部fail loud。
2. **F5-B Scoped planning view（COMPLETE）**：内部从嵌套scope树生成一个全题PlanningContext与逐Goal authority；Prompt投影为单棵`planner-problem-view/v1` scope树，每个Entity/Fact直接携带唯一ref，Goal位于owner scope，空集合省略。F5-C通过按Goal authority API消费内部allowlist；source/runtime覆盖与跨sibling来源在投影时fail loud。
3. **F5-C Planner binding（COMPLETE）**：从F5-B的按Goal authority确定映射SemanticRef、runtime node、source unit与typed Context identity；call按answer producer和typed dependency绑定Goal，共享call只读取Goal allowlist交集。source snapshot固定为未演进typed slot的ordinal 0，Catalog不得从mid-planning latest重建。具名对象的SemanticRef若存在唯一、可见、同对象的前序状态，reconciliation确定性绑定该精确call result；匿名结果、非最近版本或歧义仍使用显式CallResultRef。answer authority不能作为C3 input。跨sibling、answer串线、多Goal target、未知source unit、sidecar/C3版本或revision漂移均在direct compile前失败。Catalog与sidecar各有strict schema snapshot。
4. **F5-D Retry/provenance（COMPLETE）**：`ProblemCallSourceProvenance`把每个call的Goal、revision/hash、binding signature和直接Problem source reads写入runtime write/result、PlannerStateContext与`functional-retry-graph-checkpoint/v2`。跨call传递统一保存为typed result DAG，不复制上游source unit，无论wire使用SemanticRef自动绑定还是显式CallResultRef。checkpoint restore对locked call执行完整authority比较；repair call不得越出原Goal集合。retry prompt从可信PlanningContext和checkpoint重新生成，仅包含repair call对应GoalView及祖先scope；source unit只参与内部signature/authority，不暴露给Planner，revision、runtime node和StateVersion同样不进入prompt。旧checkpoint版本不可hydrate。Solver retry不重新运行OCR、豆包、domain projector或完整Solver。
5. **F5-E Cold path（COMPLETE）**：公开`solve_problem()`只接收authenticated Bundle；裸ProblemIR仅可走deterministic `solve_problem_ir_debug()`。Strategy每轮从同一Bundle重建ProblemIR、RuntimeContext和初始PlannerStateContext，强制派生PlanningContext与BindingCatalog。Planner只接收`planner-problem-view/v1`：一棵嵌套scope树，exact SemanticRef直接内嵌于Entity/Fact，Goal位于owner scope；不再发送`available_refs`、逐Goal reads、scope path或shared/local重复切片。recorded与DeepSeek均使用scope-native fixture/authority，旧扁平ProblemIR prompt和全局SemanticRef fallback已删除。`ProblemColdPathService`只运行一次提取，accepted后重新加载Bundle再求解；Planner retry复用同一revision，不重复调用OCR或豆包。F5-E的退出责任是证明默认入口和authority冷路径真实贯通，不要求即将删除的v1完整计划重写达到稳定`5x3`。过渡retry清理与全量离线门禁已完成，不再为v1追加付费smoke。
6. **F5-F Scope-derived FunctionalPlan（NEXT，分五步）**
   - **F5-F1 Scoped Plan v2 authority**：新增`functional_plan/v2`。输出scope树必须与`planner-problem-view/v1`的scope骨架一致；每个scope可包含`shared_steps`，每个Goal包含自己的完整`steps`。模型不能创建scope或Goal，execution scope、typed binding和canonical return authority仍由F5-C/B2派生。
   - **F5-F2 Incremental Goal run**：建立`functional-goal-execution-checkpoint/v1`。内部仍逐step执行`prepare -> compile -> sandbox method -> result/closure`，但冻结单位是完成门禁的Goal或可信shared-scope block，而不是失败Goal中的零散call。每个已尝试step都保存prompt-safe的实际输入、实际输出、执行状态和typed error；未执行suffix保存`blocked_by`。一个Goal失败时这些结果全部作为诊断返回，整个Goal仍可重写；无依赖的sibling Goal继续执行。所有Goal通过前仍不写authoritative Context。
   - **F5-F3 Goal replacement retry**：新增`functional-goal-repair/v1`。每次retry同时发送完整上一版canonical `functional_plan/v2`和与其同构的scope/Goal执行树，不裁掉solved或sibling Goal。执行树中solved Goal为`editable=false`并携带逐step结果和可发布结果；failed Goal为`editable=true`并携带逐step实际输入、输出、错误与blocked suffix。模型只返回失败Goal的完整`goal_replacements`，必要时返回失败shared block的`shared_scope_replacements`，不做call级JSON patch，也不能修改solved Goal。
   - **F5-F4 Family path macros**：删除LLM可见`PathTransformation`。正方形中点/中心、射线等长、加权路径和linked auxiliary等family分别声明高层macro；内部可共享`ReducedPathWitness`和straightening core，但不建立运行时猜family的万能macro。
   - **F5-F5 Teaching scope与退役**：根据call-to-Goal authority生成`TeachingStepPlacement`和按Problem scope嵌套的学生步骤结果。`execution_scope_id`与`teaching_scope_id`分别审计；通过两组5×3后删除`functional_plan/v1`、authored scope fixture和兼容分支。物理清理同时删除底层reconciler/replay的`problem_binding_catalog=None`与全局`semantic_read_catalog()`回退、v1的`replace_answer_ref_with_goal_target`/`bind_unique_condition_role`确定性repair，并将裸`RuntimeOrchestrator.solve(ProblemIR)`私有化；deterministic测试统一通过`solve_problem_ir_debug()`。`planner-problem-view`及v2 Plan/Retry schema对每个typed variant使用`additionalProperties: false`，不再依赖Python projector兜底宽松item字段。

F5-A/B/C/D当前证据：五题accepted Context可确定加载并各生成一个`problem-planning-context/v1`；南开/和平二模分别生成6/4个GoalView，其余三题各3个。五份scope-native recorded FunctionalPlan已通过validation、reconciliation、direct compile、authoritative closure、transaction、checkpoint v2和Goal-scoped retry projection，SemanticRef到runtime/source/typed identity及write/result/checkpoint provenance覆盖缺口为0。missing、revision、Goal、source unit与call signature mutation及repair foreign-Goal mutation均fail loud；answer-check撤销commit后只保留带authority的provisional runtime evidence，不产生locked checkpoint；失败事务ghost write为0。

F5-E离线证据：五题accepted Bundle均通过默认recorded Strategy入口；公开Strategy入口拒绝裸ProblemIR，`StrategyPlanner`构造和`StrategyPayloadBuilder`均在缺少Problem authority/BindingCatalog时fail loud，payload中不存在`problem_ir`，Strategy生产模块不再调用全局`semantic_read_catalog()`。底层通用reconciler的nullable catalog分支只供尚未迁移的deterministic/debug测试，生产Strategy不可达，并已列入F5-F5物理删除门禁。`RuntimeSuccessArtifacts`保留Bundle token、PlanningContext、BindingCatalog、最终PlannerStateContext和Problem provenance。Planner Problem View精简后的真实DeepSeek Planner-only `5×1`为`5/5`；v1 `5×3`基线为`11/15`。真实图片cold-path统一批次中，五题提取均一次accepted，domain/projection diff、完整图片输入、scope-native prompt及configuration/unclassified gate均通过，Solver为`3/5`；历史定向批次已分别证明五题能够完成同一冷路径。剩余失败位于F5-F要物理替换的PathTransformation、整图pre-runtime、call级冻结与完整plan重写，不是Bundle、PlanningContext或F5-C/D authority漂移。该数据固定为v1对照，不再消耗模型成本追求旧协议`5/5`或`15/15`。

F5-E退出条件收口为：默认Bundle入口、scope-native prompt、BindingCatalog、transaction/provenance和cold-path两阶段authority的离线门禁全绿；真实图片五题均一次accepted且不因Planner retry重复提取；configuration/unclassified、revision和source-binding drift为0。旧v1 Planner的最终answer成功率不再属于F5-E。F5整体退出条件移到F5-F：Planner-only与图片cold path各自`5×3=15/15`，Problem/Plan/Retry三棵scope树可确定对齐，Goal冻结/替换、execution scope和teaching scope可确定重放，提取模型不被重复调用，跨scope identity drift和失败事务幽灵write均为0。

## Track G：解题后 Context

```text
PlannerStateContext
  -> LessonExplanationContext
  -> DiagramContext
  -> VoiceoverContext
  -> AnimationContext
  -> compiled lesson page
```

目标是让教学步骤、图形对象、旁白和动画均具有不可变Context、显式dependency与typed validation。F5完成默认Solver接线后，G消费同一`problem_revision_id`下的VerifiedProblem、PlannerStateContext、runtime provenance和F5-F派生的教学scope归属。

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
