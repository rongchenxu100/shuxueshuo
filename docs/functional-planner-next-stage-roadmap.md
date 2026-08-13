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

Scope是本地题面、Entity、Fact、词法可见性和教学分段的容器；Goal是附着在scope上的原子答案要求。常见小问scope恰有一个Goal，但二者不等价：公共条件scope可以没有Goal，同一小问“求P、A两点”可以拥有两个Goal。Goal不再派生人工scope，也不拥有Entity、Fact或child scope。Plan中的`scope.steps`归该scope所有并可服务一个或多个后代Goal，`goal.steps`只服务对应Goal；服务集合由typed dependency推导，不增加`shared_steps`字段。

实现顺序：

1. **F5-A Bundle authority（COMPLETE）**：从accepted Context加载VerifiedProblem、内嵌manifest的Solver projection envelope和validation report；交叉校验artifact、revision、semantic hash、family与完整source/runtime映射。pending、blocked或authority token漂移全部fail loud。
2. **F5-B Scoped planning view（COMPLETE）**：内部从嵌套scope树生成一个全题PlanningContext与逐Goal authority；Prompt投影为单棵`planner-problem-view/v2` scope树，每个Entity/Fact直接携带唯一ref，Goal位于owner scope，空集合省略。Prompt Goal使用与Plan相同的`goal_ref`，内部F5-C answer authority保持不变。F5-C通过按Goal authority API消费内部allowlist；source/runtime覆盖与跨sibling来源在投影时fail loud。
3. **F5-C Planner binding（COMPLETE）**：从F5-B的按Goal authority确定映射SemanticRef、runtime node、source unit与typed Context identity；call按answer producer和typed dependency绑定Goal，共享call只读取Goal allowlist交集。source snapshot固定为未演进typed slot的ordinal 0，Catalog不得从mid-planning latest重建。旧v1 reconciliation曾对具名对象自动选择唯一同对象前序状态；`functional_plan/v2`已禁用该规则，字符串SourceRef只读固定snapshot，所有动态状态统一要求显式StepResultRef。answer authority不能作为C3 input。跨sibling、answer串线、多Goal target、未知source unit、sidecar/C3版本或revision漂移均在direct compile前失败。Catalog与sidecar各有strict schema snapshot。
4. **F5-D Retry/provenance（COMPLETE）**：`ProblemCallSourceProvenance`把每个call的Goal、revision/hash、binding signature和直接Problem source reads写入runtime write/result、PlannerStateContext与`functional-retry-graph-checkpoint/v2`。跨call传递统一保存为typed result DAG，不复制上游source unit，无论wire使用SemanticRef自动绑定还是显式CallResultRef。checkpoint restore对locked call执行完整authority比较；repair call不得越出原Goal集合。retry prompt从可信PlanningContext和checkpoint重新生成，仅包含repair call对应GoalView及祖先scope；source unit只参与内部signature/authority，不暴露给Planner，revision、runtime node和StateVersion同样不进入prompt。旧checkpoint版本不可hydrate。Solver retry不重新运行OCR、豆包、domain projector或完整Solver。
5. **F5-E Cold path（COMPLETE）**：公开`solve_problem()`只接收authenticated Bundle；裸ProblemIR仅可走deterministic `solve_problem_ir_debug()`。Strategy每轮从同一Bundle重建ProblemIR、RuntimeContext和初始PlannerStateContext，强制派生PlanningContext与BindingCatalog。Planner只接收`planner-problem-view/v2`：一棵嵌套scope树，exact SemanticRef直接内嵌于Entity/Fact，Goal位于owner scope；不再发送`available_refs`、逐Goal reads、scope path或shared/local重复切片。recorded与DeepSeek均使用scope-native fixture/authority，旧扁平ProblemIR prompt和全局SemanticRef fallback已删除。`ProblemColdPathService`只运行一次提取，accepted后重新加载Bundle再求解；Planner retry复用同一revision，不重复调用OCR或豆包。F5-E的退出责任是证明默认入口和authority冷路径真实贯通，不要求即将删除的v1完整计划重写达到稳定`5x3`。过渡retry清理与全量离线门禁已完成，不再为v1追加付费smoke。
6. **F5-F Scope-derived FunctionalPlan（F5-F1/F2 COMPLETE，分五步）**
   - **F5-F1 Scoped Plan v2 authority（COMPLETE）**：已新增严格`functional_plan/v2`、固定四层且无scope递归引用的Python/JSON schema、独立system/user prompt、五份authored fixture、七份mechanism few-shot及专用raw-response replay入口。输出scope树必须与`planner-problem-view/v2`的scope骨架一致；根scope计为第一层，第四层必须为叶子。每个scope可包含普通`steps`，每个Goal也可包含自己的`steps`。父scope中的步骤天然由父scope拥有，服务哪些后代Goal由answer producer和typed dependency推导，不定义`shared_steps`。模型不能创建scope或Goal，execution scope、typed binding和canonical return authority仍由F5-C/B2派生。v2 authority会确定性lower到现有v1内部执行结构，继续复用B1/B2/B3/C3、direct compiler和transaction；生产DeepSeek默认协议尚未切换。
   - **F5-F1.1 和平二模泛化加固（COMPLETE）**：Function facade统一公开`quadratic_x_axis_intercept_point.parabola`和`square_adjacent_vertex_from_side.adjacent_vertex`，底层Method仍使用`quadratic`和`point`；catalog对required runtime input、公开return、同类型多return role执行完整覆盖审计。v2 authority只允许显式alias或“唯一未知输入→唯一缺失required参数”的类型归一，optional与多候选不参与，并把`canonicalize_capability_arg_name`纳入authority和semantic hash。Goal答案统一由`answer_from`绑定，中间题面对象统一由`output_targets`绑定；capability只有声明了结构化source-fact target selector且当前scope恰好得到一个F5-C可见、类型兼容对象时，代码才可补target，并记录`infer_unique_output_target`；零候选和多候选均fail loud，正方形顶点仍必须显式绑定。共享计算必须直接 authored 在consumer Goal的共同祖先`scope.steps`，lowering不自动移动step或合并兄弟调用；B2只验证最终execution scope。authority analyzer聚合独立参数、输出身份、scope和DAG root issues。
   - **F5-F1.2 Goal identity同名化（COMPLETE）**：Prompt-facing Problem View升级为`planner-problem-view/v2`，Goal与Plan统一使用`goal_ref`；模型必须逐字复制，不能用scope id、target或自造名称。内部`ProblemPlanningGoalView.answer_ref`及F5-C typed answer authority不变。scope树完全一致、owner scope恰有一个expected Goal且Plan也恰有一个未知Goal id时，authority可记录`canonicalize_unique_goal_ref`并机械改为expected id；多Goal、数量不等、重复Goal及把已知Goal放到错误scope一律不猜。Debug同时保存raw结构、归一记录、canonical Plan和归一后结构报告。真实low-thinking批次`f5f1-deepseek-v2-goal-ref-v2-low-5x1-20260813`达到`5/5 schema-valid`与`5/5 scope/Goal tree`，五题均原生逐字输出正确`goal_ref`，Goal归一触发数为0；`4/5 plan authority`和`2/5 transaction`的剩余错误已推进到SemanticRef、Goal closure和runtime层，不属于Goal identity契约。
   - **F5-F1.3 Goal target identity与MathObject安全归一（COMPLETE）**：Prompt Goal明确分离`goal_ref`（Goal/answer authority）与`target_ref`（被回答的题面MathObject），并从Prompt wire删除旧`target`。Capability参数通过`semantic_ref_role`声明普通值或对象identity；对象identity只能使用可见Entity/Goal `target_ref`，不能使用`goal_ref`。若Goal私有step误用自己的answer ref，代码只在F5-C证明answer与唯一可见input ref拥有相同`MathObjectId`、scope与类型均匹配时记录`canonicalize_goal_target_input_ref`并机械改写；跨Goal、scope step、computed value、零/多候选和无typed identity全部fail loud。未能安全归一的answer输入使用专用`functional.answer_ref_used_as_input`诊断，原始模型响应不变。
   - F1.3首轮真实批次`f5f1-deepseek-v2-goal-target-identity-low-5x1-20260813`为`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 Plan authority`。西青失败暴露既有scope placement只支持向祖先提升；补成对称且authority受限的LCA placement后，五份原始响应离线重放`5/5 Plan authority`，child-local `D`的producer从authored root确定性收窄到`ii`。第二个独立批次`f5f1-deepseek-v2-goal-target-scope-placement-low-5x1-20260813`继续保持`5/5 schema/tree`，但one-shot authority为`1/5`，剩余root issues是未声明的可选`return_expectations`和同一对象多producer未显式选取，均不属于Goal/target MathObject转换。两个批次unsafe normalization、identity leak、configuration和unclassified error均为0；F1.3实现完成，F5-F1 live门禁仍pending。
   - **F5-F1.4 Return expectation policy与安全归一（COMPLETE）**：Capability catalog的每个return显式声明`return_expectation_policy`。有非空`possible_forms`的开放/闭合return为`selectable`，模型可以在`return_expectations`中逐字选择；fixed-form return为`omit`且catalog不输出`possible_forms`。authority保留合法selectable expectation，非法form和未知role继续fail loud；仅对已存在且policy为omit的return确定性删除多余expectation并记录`drop_fixed_form_return_expectation`。删除不改变raw response、runtime form验证或semantic hash，重复归一零漂移；review展示policy、原始expectation、删除记录和canonical Plan。
   - F1.4真实DeepSeek low-thinking单轮批次`f5f1-deepseek-v2-return-expectation-policy-low-5x1-20260813`为`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 Plan authority`，五题均原生遵守policy，omit删除数、expectation authority issue、unsafe normalization、identity leak、configuration和unclassified error均为0。唯一authority失败为和平一模使用三个不存在的SemanticRef，不属于return contract；F1.4硬门禁通过，F5-F1整体仍等待`5/5 Plan authority`。
   - **F5-F1.5 Scope-native step identity（IMPLEMENTED）**：v2固定`step_id == canonical_call_id`，任意call alias稳定失败；同scope/兄弟scope的相同调用不再merge，scope树是唯一共享机制。字符串SourceRef只能逐字引用Problem View并固定读取source snapshot/object identity；任何前序动态值或已更新对象都必须使用StepResultRef。仅对“参数名或Fact kind占位符→当前Goal唯一、可见、kind/runtime/cardinality完全匹配的F5-C Fact authority”执行`canonicalize_unique_fact_ref`；已知错误ref与多候选不修。raw Plan保留dead pure branch，effective plan确定性剪除不影响Goal closure、provenance、Condition或外部状态的无消费者pure closure。
   - **F5-F1.6 Scope-local SourceRef（COMPLETE）**：Problem View中的Entity/Fact ref统一为scope-local裸名称，Goal ref继续全题唯一。内部authority key固定为`(owner_scope_id, local_ref, kind)`并按当前scope到祖先词法解析；兄弟同名合法且身份隔离，父子同名遮蔽失败，同scope冲突只生成稳定本地后缀。BindingCatalog、Goal allowlist、semantic index和v2 authority均使用复合键，不再按全局ref字符串索引。Prompt要求复制当前scope视图显示的裸ref且不得添加scope前缀，旧prefix wire不兼容。
   - **F5-F2 Incremental Goal run（COMPLETE）**：建立`functional-goal-execution-checkpoint/v1`。在全局schema、revision和scope/Goal骨架通过后，服务逐step隔离authority错误；坏step不执行，显式依赖suffix标记`blocked_by_dependency`，其余ready前缀和独立Goal继续`prepare -> compile -> sandbox method -> result/closure`。成功write/result只进入attempt-local provisional state，所有Goal通过前不写authoritative Context。scope-shaped checkpoint逐step保存authored wire、prompt-safe实际输入/输出、状态和typed issue；内部另存revision、Goal/source unit和binding/provisional signatures并fail closed。Smoke分别统计authority-valid/invalid、dead-pruned、provisional-executed、blocked、transaction-attempted/ok与blocked-stage。
   - **F5-F2.1 固定点执行边界（COMPLETE）**：v2 pinned step禁止进入任何preallocated alias/merge。Replay拆成reconcile-only与finalized-authority execute两阶段，placement/Goal closure/sidecar错误先形成typed report，未通过不得执行Method。增量服务以`step_count+1`为上界反复隔离localizable reconciliation issue并重算依赖；动态SourceRef错误精确指出所需StepResult，显式DAG和经MathObject authority证明的隐式对象状态依赖共同阻断suffix，clean subset继续provisional transaction。可解析Plan在authoring、reconciliation、placement或runtime失败时都生成scope-shaped checkpoint，记录stage、root issues与`all_required_goals_verified`；invalid JSON/schema不伪造scope checkpoint，revision/source authority漂移继续nonretryable fail loud。
   - **F5-F2.2 Step三层Scope authority（COMPLETE）**：每个step分别保存模型authoring位置`plan_scope_id`、lowering验证后的数学归属`semantic_owner_scope_id`和B2运行位置`execution_scope_id`。`finalize_reconciliation()`只能填写execution scope，不得覆盖前两者；final binding signature显式覆盖scope三元组和最终consumer Goal。重复finalize零漂移，authority payload可确定round-trip。F5-F5只能将plan/semantic scope作为教学placement输入，禁止从execution scope反推语义或讲解归属。
   - 最新离线基线为F5-F1/F2/PlanningContext/Binding/transaction联合`190 passed`、全量Solver`1793 passed, 12 skipped`。五份recorded v2 Plan均保持`step_id == canonical_call_id`且call alias为0；坏Fact ref、动态SourceRef误用、dead pure branch、suffix阻断、checkpoint round-trip/authority drift、实际StepResult输入与prompt identity卫生均有定向覆盖。
   - 最终真实DeepSeek low-thinking单轮批次`f5f1-step-identity-incremental-low-5x1-20260813`未静默重跑：provider response、schema和scope/Goal tree均为`5/5`，Plan authority为`4/5`；identity leak、configuration/unclassified error、unsafe normalization和call alias均为0。河西是唯一F1失败：同一`i` scope的Prompt ref使用`i.symbol_value_a`与无前缀`symbol_value_b/c`两种命名，模型一致化为`i.symbol_value_a/b/c`后，后两个成为未知SourceRef。该问题优先归类为Prompt-facing identity不一致诱发的模型错误，F5-F1仍为`IMPLEMENTED / LIVE 5x1 PENDING`，需修复后用新批次重新达到真实`5/5 Plan authority`才可关闭。
   - 该批次F5-F2诊断为authority-valid `50`、invalid `1`、blocked suffix `1`、provisional executed `23`、dead-pruned `0`、transaction `2/2`。和平一模与西青完整执行；河西和南开分别因动态`M/N`仍以SourceRef而非StepResultRef读取，在reconciliation层整体停住，暴露“reconciliation issue尚未降为局部step issue并继续独立DAG”的缺口；和平二模因`compute_A_ii` placement缺失在authority finalize抛错，未生成checkpoint。失败样本没有authoritative transaction write，F5-F2继续保持`IMPLEMENTED / LIVE DIAGNOSTIC PENDING`。
   - F1.6/F2.1修复后的真实批次`f5f1-scope-local-return-types-fixed-point-low-5x1-20260813`仍严格为每题一个semantic attempt：provider response、schema和scope/Goal tree均为`5/5`，scope前缀、call alias、identity leak、configuration/unclassified error和unsafe normalization均为0。执行服务此前把F2 reconciliation/runtime issue合并进F1 report，导致落盘摘要误记`3/5 Plan authority`；分离authoring report与scope-shaped execution checkpoint后，对同一批五份原始响应进行确定性重放得到`5/5 Plan authority`，因此F5-F1关闭为`COMPLETE`。原始响应、normalization和执行错误未被改写。
   - 同批F5-F2诊断为authority-valid `63`、authority-invalid `3`、blocked suffix `7`、provisional executed `60`、dead-pruned `3`、transaction attempted `5/5`、transaction clean `3/5`，五题均生成checkpoint。和平二模与西青全部Goal通过；和平一模和河西的动态SourceRef被定位到具体step并继续执行独立分支；南开完成`5/6` Goal后保留runtime错误。F2问题不再污染F1 authoring gate，partial execution仍无authoritative ghost write；下一阶段由F5-F3消费这些checkpoint执行Goal replacement retry。
   - **F5-F3 Goal replacement retry**：新增`functional-goal-repair/v1`。每次retry同时发送完整上一版canonical `functional_plan/v2`和与其同构的scope/Goal执行树，不裁掉solved或sibling Goal。执行树中solved Goal为`editable=false`并携带逐step结果和可发布结果；failed Goal为`editable=true`并携带逐step实际输入、输出、错误与blocked suffix。模型只返回失败Goal的完整`goal_replacements`；scope-level步骤失败时返回对应`scope_step_replacements`，不做call级JSON patch，也不能修改solved Goal。
   - **F5-F4 Family path macros**：删除LLM可见`PathTransformation`。正方形中点/中心、射线等长、加权路径和linked auxiliary等family分别声明高层macro；内部可共享`ReducedPathWitness`和straightening core，但不建立运行时猜family的万能macro。
   - **F5-F5 Teaching scope与退役**：根据call-to-Goal authority生成`TeachingStepPlacement`和按Problem scope嵌套的学生步骤结果。教学placement消费不可变的`plan_scope_id`与`semantic_owner_scope_id`，并与`execution_scope_id`分别审计；不得从运行位置反推语义或讲解归属。通过两组5×3后删除`functional_plan/v1`、authored scope fixture和兼容分支。物理清理同时删除底层reconciler/replay的`problem_binding_catalog=None`与全局`semantic_read_catalog()`回退、v1的`replace_answer_ref_with_goal_target`/`bind_unique_condition_role`确定性repair，并将裸`RuntimeOrchestrator.solve(ProblemIR)`私有化；deterministic测试统一通过`solve_problem_ir_debug()`。`planner-problem-view`及v2 Plan/Retry schema对每个typed variant使用`additionalProperties: false`，不再依赖Python projector兜底宽松item字段。

F5-A/B/C/D当前证据：五题accepted Context可确定加载并各生成一个`problem-planning-context/v1`；南开/和平二模分别生成6/4个GoalView，其余三题各3个。五份scope-native recorded FunctionalPlan已通过validation、reconciliation、direct compile、authoritative closure、transaction、checkpoint v2和Goal-scoped retry projection，SemanticRef到runtime/source/typed identity及write/result/checkpoint provenance覆盖缺口为0。missing、revision、Goal、source unit与call signature mutation及repair foreign-Goal mutation均fail loud；answer-check撤销commit后只保留带authority的provisional runtime evidence，不产生locked checkpoint；失败事务ghost write为0。

F5-E离线证据：五题accepted Bundle均通过默认recorded Strategy入口；公开Strategy入口拒绝裸ProblemIR，`StrategyPlanner`构造和`StrategyPayloadBuilder`均在缺少Problem authority/BindingCatalog时fail loud，payload中不存在`problem_ir`，Strategy生产模块不再调用全局`semantic_read_catalog()`。底层通用reconciler的nullable catalog分支只供尚未迁移的deterministic/debug测试，生产Strategy不可达，并已列入F5-F5物理删除门禁。`RuntimeSuccessArtifacts`保留Bundle token、PlanningContext、BindingCatalog、最终PlannerStateContext和Problem provenance。Planner Problem View精简后的真实DeepSeek Planner-only `5×1`为`5/5`；v1 `5×3`基线为`11/15`。真实图片cold-path统一批次中，五题提取均一次accepted，domain/projection diff、完整图片输入、scope-native prompt及configuration/unclassified gate均通过，Solver为`3/5`；历史定向批次已分别证明五题能够完成同一冷路径。剩余失败位于F5-F要物理替换的PathTransformation、整图pre-runtime、call级冻结与完整plan重写，不是Bundle、PlanningContext或F5-C/D authority漂移。该数据固定为v1对照，不再消耗模型成本追求旧协议`5/5`或`15/15`。

F5-F1至F1.4离线证据：五份v2 fixture均完成strict parse、scope/Goal authority、lowering、F5-C reconciliation、direct compile与transaction；四层schema、公开Function facade、安全参数归一、source-fact唯一目标选择、dependency-based scope lifting、Goal/MathObject identity、return expectation policy、聚合authority报告和专用live authoring service均有离线覆盖。最新专项联合回归`372 passed`，全量Solver回归`1770 passed, 12 skipped`；scope/Goal drift、第五层scope、跨sibling/跨Goal引用、forward reference、answer producer、output target、多producer歧义、optional/多类型参数误修、不安全scope提升、非法selectable form和未知return role均有fail-loud覆盖，v2 prompt不暴露内部identity、Method runtime slot或v1 return binding。

首轮真实DeepSeek v2 `5×1`批次`f5f1-deepseek-v2-contract-5x1-20260812`主门禁为`0/5`：五题均在单次provider attempt返回可见响应，identity leak、configuration error和unclassified error均为0；仅西青通过JSON schema，但因父scope公共step被复制进`ii_1`而触发全题`step_id`重复。和平一模、河西、南开为JSON括号损坏且诊断修复后仍存在scope/Goal结构漂移；和平二模JSON合法，但复制了Problem View的Entity/Fact、形成双层root并漏掉`i_1.A/i_1.P`两个Goal。总usage为`59,419 tokens`，其中prompt `51,449`、completion `7,970`。该批次不做静默重跑，F5-F1保持`LIVE 5x1 PENDING`。

将递归scope schema改为固定四层展开后，真实批次`f5f1-deepseek-v2-finite-scope-5x1-20260812`仍为`0/5`，但schema-valid由`1/5`提升到`2/5`：和平二模和西青均通过JSON/schema，分别在完整scope树和backward step-result authority失败；和平一模仍为坏JSON，河西输出空`goals`，南开输出空参数数组。identity leak、configuration error和unclassified error继续为0，总usage为`60,914 tokens`。有限深度schema关闭了递归输出歧义，但scope骨架复制、空集合和step DAG仍需后续收口，F5-F1保持`LIVE 5x1 PENDING`。

同一四层schema下开启Pass 1 low thinking的单轮批次`f5f1-deepseek-v2-finite-scope-low-thinking-5x1-20260812`取得`5/5 schema-valid`、`1/5 scope/Goal authority`和`1/5 transaction`，西青完整通过；其余四题分别停在capability arg命名、Goal identity和额外scope。五题均只有一个provider sub-attempt，无semantic retry。代价是总usage升至`175,575 tokens`，其中`114,761`为reasoning tokens，平均单题延迟由约`10.1s`升至`187.8s`。历史disabled批次当时未将summary中的`temperature=0`显式透传给provider，因此两批仅作方向性比较；当前专用runner已对disabled/low两种profile都显式发送`temperature=0`，生产DeepSeek默认策略不变。

最新真实单轮批次`f5f1-deepseek-v2-f1-1-generalized-low-5x1-20260812`为`5/5 schema-valid`、`3/5 scope/Goal tree`、`3/5 plan authority`和`1/5 transaction`；五题均只有一个provider sub-attempt，identity leak、configuration error和unclassified error均为0，总usage为`134,429 tokens`。和平二模已显式绑定两个参数化`E`并通过F5-F1 authority，当前失败是路径降维确定moving object为`G`而Plan选择`E`轨迹，属于后续策略/执行问题；河西漏`i.P`，和平一模漏`i_1.parabola`并输出额外Goal，均停在结构门禁。F5-F1仍标记`LIVE 5x1 PENDING`。

将source-fact selector的Prompt术语统一为Problem View实际使用的`axis_membership`后，最终单轮批次`f5f1-deepseek-v2-f1-1-final-low-5x1-20260812`有四题完成落盘：西青通过schema、scope/Goal、authority、compile与transaction；河西、和平一模分别漏`i.P`和`i_1.parabola`；南开输出空`goals`并由strict schema拒绝。四题均只有一个provider sub-attempt，identity leak、configuration error和unclassified error为0，共使用`114,022 tokens`。和平二模首个provider请求运行超过14分钟且没有生成sample artifact，明显超过配置的300秒窗口，批次被显式终止并记为transport hang，没有静默重跑或伪造第五题结果。因此该批次不是完整`5×1`验收，F5-F1/F1.1继续保持`LIVE 5x1 PENDING`。

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
