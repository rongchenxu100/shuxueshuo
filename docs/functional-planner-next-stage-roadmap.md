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
| F5：分域规划与Solver生命周期 | `IN PROGRESS` | F5-F3、F5-F4.2R、F5-F4.3A完成；原透明Macro方案已回滚，下一步进入F5-F4.3B原子边界与golden reference |
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

F5-E切换期间曾以`functional_plan/v1`和现有`SemanticRef`作为过渡执行协议；F5-F4.2后公开生产入口已经切到content/v2与Goal checkpoint v3，v1只保留为派生执行IR及显式debug入口。服务端catalog sidecar把每个ref绑定到source unit与runtime handle；LLM不能跨sibling引用。B2只规划已授权调用的物理执行，不再移动step、扩大状态可见性或重选semantic owner。同一个根Entity在不同子问中的Fact投影为独立scope-local `StateVersion`，不会因handle相同而合并状态。

F5-F不作为一个大改动一次落地，而是拆成协议、执行、retry、宏和教学归属五个可独立验收的子阶段。Problem、Plan与Retry统一使用同一棵scope/Goal树；scope骨架和Goal identity来自VerifiedProblem并由代码持有，LLM只提交scope/Goal对应的步骤内容映射。代码将内容映射组装为canonical `functional_plan/v2`。增量执行以Goal完成为冻结边界，失败Goal允许完整重写自己的思路；family-specific path macro独立替换`PathTransformation`；最后由同一scope权威生成教学结果并删除旧兼容。

Scope是本地题面、Entity、Fact、词法可见性和教学分段的容器；Goal是附着在scope上的原子答案要求。常见小问scope恰有一个Goal，但二者不等价：公共条件scope可以没有Goal，同一小问“求P、A两点”可以拥有两个Goal。Goal不再派生人工scope，也不拥有Entity、Fact或child scope。Plan中的`scope.steps`归该scope所有并可服务一个或多个后代Goal，`goal.steps`只服务对应Goal；服务集合由typed dependency推导，不增加`shared_steps`字段。

实现顺序：

1. **F5-A Bundle authority（COMPLETE）**：从accepted Context加载VerifiedProblem、内嵌manifest的Solver projection envelope和validation report；交叉校验artifact、revision、semantic hash、family与完整source/runtime映射。pending、blocked或authority token漂移全部fail loud。
2. **F5-B Scoped planning view（COMPLETE）**：内部从嵌套scope树生成一个全题PlanningContext与逐Goal authority；Prompt投影为单棵`planner-problem-view/v2` scope树，每个Entity/Fact直接携带唯一ref，Goal位于owner scope，空集合省略。Prompt Goal使用与Plan相同的`goal_ref`，内部F5-C answer authority保持不变。F5-C通过按Goal authority API消费内部allowlist；source/runtime覆盖与跨sibling来源在投影时fail loud。
3. **F5-C Planner binding（COMPLETE）**：从F5-B的按Goal authority确定映射SemanticRef、runtime node、source unit与typed Context identity；call按answer producer和typed dependency绑定Goal，共享call只读取Goal allowlist交集。Catalog中的source snapshot固定为未演进typed slot的ordinal 0，不从mid-planning Context重建；执行中的稳定MathObject SourceRef则由scope-native canonicalizer按step顺序绑定到最近可见的同对象写入，并在C3中落成exact CallResult identity。无前序写入时读取初始snapshot；匿名结果、非最新历史状态和多producer消歧仍要求显式StepResultRef。answer authority不能作为C3 input。跨sibling、answer串线、多Goal target、未知source unit、sidecar/C3版本或revision漂移均在direct compile前失败。Catalog与sidecar各有strict schema snapshot。
4. **F5-D Retry/provenance（COMPLETE）**：`ProblemCallSourceProvenance`把每个call的Goal、revision/hash、binding signature和直接Problem source reads写入runtime write/result与PlannerStateContext。跨call传递统一保存为typed result DAG，不复制上游source unit。当前生产restore只有`functional-goal-execution-checkpoint/v3`一个owner；StateVersion、CallResult、Condition、per-call F5-C binding和Macro winner均是其私有typed restore state。retry prompt只投影Goal可见的修复信息，不暴露source unit、runtime node、StateVersion或私有restore state。旧checkpoint版本不可hydrate，Solver retry不重新运行OCR、豆包、domain projector或完整Solver。
5. **F5-E Cold path（COMPLETE）**：公开`solve_problem()`只接收authenticated Bundle；裸ProblemIR仅可走deterministic `solve_problem_ir_debug()`。Strategy每轮从同一Bundle重建ProblemIR、RuntimeContext和初始PlannerStateContext，强制派生PlanningContext与BindingCatalog。Planner只接收`planner-problem-view/v2`：一棵嵌套scope树，exact SemanticRef直接内嵌于Entity/Fact，Goal位于owner scope；不再发送`available_refs`、逐Goal reads、scope path或shared/local重复切片。recorded与DeepSeek均使用scope-native fixture/authority，旧扁平ProblemIR prompt和全局SemanticRef fallback已删除。`ProblemColdPathService`只运行一次提取，accepted后重新加载Bundle再求解；Planner retry复用同一revision，不重复调用OCR或豆包。F5-E的退出责任是证明默认入口和authority冷路径真实贯通，不要求即将删除的v1完整计划重写达到稳定`5x3`。过渡retry清理与全量离线门禁已完成，不再为v1追加付费smoke。
6. **F5-F Scope-derived FunctionalPlan（F5-F1/F2 COMPLETE，分五步）**
   - **F5-F1 Scoped Plan authority（COMPLETE）**：内部canonical结构保持`functional_plan/v2`，LLM authoring wire升级为严格`functional-plan-content/v2`。代码从`planner-problem-view/v2`派生唯一`FunctionalPlanAuthorityFrame`，固定全部scope、父子关系、Goal owner、答案target/type和精确map key；模型输出`scope_steps{scope_ref: steps}`与`goal_plans{goal_ref: {steps?, answer_from}}`。Pass 1的`answer_from`只表达求解意图，不是权威：assembler独立枚举Goal可见scope、capability typed return、目标对象身份和StepResult DAG中的合法候选；指针命中合法候选时用于消歧，指针错误但仅有一个合法候选时由代码规范化并记录，零候选或未被指针消歧的多候选fail loud。空scope步骤和空Goal步骤由代码省略，父scope步骤可服务一个或多个后代Goal，不定义`shared_steps`。
   - **F5-F1.1 和平二模泛化加固（COMPLETE）**：Function facade统一公开`quadratic_x_axis_intercept_point.parabola`和`square_adjacent_vertex_from_side.adjacent_vertex`，底层Method仍使用`quadratic`和`point`；catalog对required runtime input、公开return、同类型多return role执行完整覆盖审计。v2 authority只允许显式alias或“唯一未知输入→唯一缺失required参数”的类型归一，optional与多候选不参与，并把`canonicalize_capability_arg_name`纳入authority和semantic hash。Goal答案统一由`answer_from`绑定，中间题面对象统一由`output_targets`绑定；capability只有声明了结构化source-fact target selector且当前scope恰好得到一个F5-C可见、类型兼容对象时，代码才可补target，并记录`infer_unique_output_target`；零候选和多候选均fail loud，正方形顶点仍必须显式绑定。共享计算必须直接 authored 在consumer Goal的共同祖先`scope.steps`，lowering不自动移动step或合并兄弟调用；B2只验证最终execution scope。authority analyzer聚合独立参数、输出身份、scope和DAG root issues。
   - **F5-F1.2 Goal identity同名化（COMPLETE）**：Prompt-facing Problem View升级为`planner-problem-view/v2`，Goal与Plan统一使用`goal_ref`；模型必须逐字复制，不能用scope id、target或自造名称。内部`ProblemPlanningGoalView.answer_ref`及F5-C typed answer authority不变。scope树完全一致、owner scope恰有一个expected Goal且Plan也恰有一个未知Goal id时，authority可记录`canonicalize_unique_goal_ref`并机械改为expected id；多Goal、数量不等、重复Goal及把已知Goal放到错误scope一律不猜。Debug同时保存raw结构、归一记录、canonical Plan和归一后结构报告。真实low-thinking批次`f5f1-deepseek-v2-goal-ref-v2-low-5x1-20260813`达到`5/5 schema-valid`与`5/5 scope/Goal tree`，五题均原生逐字输出正确`goal_ref`，Goal归一触发数为0；`4/5 plan authority`和`2/5 transaction`的剩余错误已推进到SemanticRef、Goal closure和runtime层，不属于Goal identity契约。
   - **F5-F1.3 Goal target identity与MathObject安全归一（COMPLETE）**：Prompt Goal明确分离`goal_ref`（Goal/answer authority）与`target_ref`（被回答的题面MathObject），并从Prompt wire删除旧`target`。Capability参数通过`semantic_ref_role`声明普通值或对象identity；对象identity只能使用可见Entity/Goal `target_ref`，不能使用`goal_ref`。若Goal私有step误用自己的answer ref，代码只在F5-C证明answer与唯一可见input ref拥有相同`MathObjectId`、scope与类型均匹配时记录`canonicalize_goal_target_input_ref`并机械改写；跨Goal、scope step、computed value、零/多候选和无typed identity全部fail loud。未能安全归一的answer输入使用专用`functional.answer_ref_used_as_input`诊断，原始模型响应不变。
   - F1.3首轮真实批次`f5f1-deepseek-v2-goal-target-identity-low-5x1-20260813`为`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 Plan authority`。西青失败暴露既有scope placement只支持向祖先提升；补成对称且authority受限的LCA placement后，五份原始响应离线重放`5/5 Plan authority`，child-local `D`的producer从authored root确定性收窄到`ii`。第二个独立批次`f5f1-deepseek-v2-goal-target-scope-placement-low-5x1-20260813`继续保持`5/5 schema/tree`，但one-shot authority为`1/5`，剩余root issues是未声明的可选`return_expectations`和同一对象多producer未显式选取，均不属于Goal/target MathObject转换。两个批次unsafe normalization、identity leak、configuration和unclassified error均为0；F1.3实现完成，F5-F1 live门禁仍pending。
   - **F5-F1.4 Return expectation policy与安全归一（COMPLETE）**：Capability catalog的每个return显式声明`return_expectation_policy`。有非空`possible_forms`的开放/闭合return为`selectable`，模型可以在`return_expectations`中逐字选择；fixed-form return为`omit`且catalog不输出`possible_forms`。authority保留合法selectable expectation，非法form和未知role继续fail loud；仅对已存在且policy为omit的return确定性删除多余expectation并记录`drop_fixed_form_return_expectation`。删除不改变raw response、runtime form验证或semantic hash，重复归一零漂移；review展示policy、原始expectation、删除记录和canonical Plan。
   - F1.4真实DeepSeek low-thinking单轮批次`f5f1-deepseek-v2-return-expectation-policy-low-5x1-20260813`为`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 Plan authority`，五题均原生遵守policy，omit删除数、expectation authority issue、unsafe normalization、identity leak、configuration和unclassified error均为0。唯一authority失败为和平一模使用三个不存在的SemanticRef，不属于return contract；F1.4硬门禁通过，F5-F1整体仍等待`5/5 Plan authority`。
   - **F5-F1.5 Scope-native step identity（IMPLEMENTED）**：v2固定`step_id == canonical_call_id`，任意call alias稳定失败；同scope/兄弟scope的相同调用不再merge，scope树是唯一共享机制。字符串SourceRef逐字引用Problem View：Fact读取验证快照，稳定Entity读取当前step最近可见状态；canonicalizer只在MathObject、scope、Goal与runtime type均一致时机械改写为exact StepResultRef。无前序写入时保留source snapshot；匿名结果、非latest历史读取和最新producer本身不唯一时必须显式StepResultRef。仅对“参数名或Fact kind占位符→当前Goal唯一、可见、kind/runtime/cardinality完全匹配的F5-C Fact authority”执行`canonicalize_unique_fact_ref`；已知错误ref与多候选不修。raw Plan保留dead pure branch，effective plan确定性剪除不影响Goal closure、provenance、Condition或外部状态的无消费者pure closure。
   - **F5-F1.6 Scope-local SourceRef（COMPLETE）**：Problem View中的Entity/Fact ref统一为scope-local裸名称，Goal ref继续全题唯一。内部authority key固定为`(owner_scope_id, local_ref, kind)`并按当前scope到祖先词法解析；兄弟同名合法且身份隔离，父子同名遮蔽失败，同scope冲突只生成稳定本地后缀。BindingCatalog、Goal allowlist、semantic index和v2 authority均使用复合键，不再按全局ref字符串索引。Prompt要求复制当前scope视图显示的裸ref且不得添加scope前缀，旧prefix wire不兼容。
   - **F5-F2 Incremental Goal run（COMPLETE）**：建立`functional-goal-execution-checkpoint/v1`。在全局schema、revision和scope/Goal骨架通过后，服务逐step隔离authority错误；坏step不执行，显式依赖suffix标记`blocked_by_dependency`，其余ready前缀和独立Goal继续`prepare -> compile -> sandbox method -> result/closure`。成功write/result只进入attempt-local provisional state，所有Goal通过前不写authoritative Context。scope-shaped checkpoint逐step保存authored wire、prompt-safe实际输入/输出、状态和typed issue；内部另存revision、Goal/source unit和binding/provisional signatures并fail closed。Smoke分别统计authority-valid/invalid、dead-pruned、provisional-executed、blocked、transaction-attempted/ok与blocked-stage。
   - **F5-F2.1 固定点执行边界（COMPLETE）**：v2 pinned step禁止进入任何preallocated alias/merge。Replay拆成reconcile-only与finalized-authority execute两阶段，placement/Goal closure/sidecar错误先形成typed report，未通过不得执行Method。增量服务以`step_count+1`为上界反复隔离localizable reconciliation issue并重算依赖；显式StepResult DAG与由MathObject/output target认证的最新状态依赖共同阻断suffix，clean subset继续provisional transaction。checkpoint的binding signature只覆盖实际可执行子图，但Goal closure始终来自完整canonical Plan DAG；共享scope失败会打开scope replacement并把consumer Goal标为blocked，而不会因answer暂未绑定把每个Goal误判成editable failure。可解析Plan在authoring、reconciliation、placement或runtime失败时都生成scope-shaped checkpoint，记录stage、root issues与`all_required_goals_verified`；invalid JSON/schema不伪造scope checkpoint，revision/source authority漂移继续nonretryable fail loud。
   - **F5-F2.2 Step三层Scope authority（COMPLETE）**：每个step分别保存模型authoring位置`plan_scope_id`、lowering验证后的数学归属`semantic_owner_scope_id`和B2运行位置`execution_scope_id`。v2 replay把显式`semantic_owner_scope_id` sidecar传入B2；凡capability声明会写MathObject状态的step，即使B1冲突而没有成功allocation，其execution、storage和StateVersion可见scope也固定为semantic owner。B2只可对value-only纯计算做受依赖约束的LCA placement，不能提升state writer，也不能借return publication扩大StateVersion可见性。`finalize_reconciliation()`只能填写execution scope，不得覆盖前两者；final binding signature显式覆盖scope三元组和最终consumer Goal。重复finalize零漂移，authority payload可确定round-trip。F5-F5只能将plan/semantic scope作为教学placement输入，禁止从execution scope反推语义或讲解归属。
   - 最新离线基线为F5-F1/F2/PlanningContext/Binding/transaction联合`190 passed`、全量Solver`1793 passed, 12 skipped`。五份recorded v2 Plan均保持`step_id == canonical_call_id`且call alias为0；坏Fact ref、动态SourceRef误用、dead pure branch、suffix阻断、checkpoint round-trip/authority drift、实际StepResult输入与prompt identity卫生均有定向覆盖。
   - 最终真实DeepSeek low-thinking单轮批次`f5f1-step-identity-incremental-low-5x1-20260813`未静默重跑：provider response、schema和scope/Goal tree均为`5/5`，Plan authority为`4/5`；identity leak、configuration/unclassified error、unsafe normalization和call alias均为0。河西是唯一F1失败：同一`i` scope的Prompt ref使用`i.symbol_value_a`与无前缀`symbol_value_b/c`两种命名，模型一致化为`i.symbol_value_a/b/c`后，后两个成为未知SourceRef。该问题优先归类为Prompt-facing identity不一致诱发的模型错误，F5-F1仍为`IMPLEMENTED / LIVE 5x1 PENDING`，需修复后用新批次重新达到真实`5/5 Plan authority`才可关闭。
   - 该批次F5-F2诊断为authority-valid `50`、invalid `1`、blocked suffix `1`、provisional executed `23`、dead-pruned `0`、transaction `2/2`。和平一模与西青完整执行；河西和南开分别因动态`M/N`仍以SourceRef而非StepResultRef读取，在reconciliation层整体停住，暴露“reconciliation issue尚未降为局部step issue并继续独立DAG”的缺口；和平二模因`compute_A_ii` placement缺失在authority finalize抛错，未生成checkpoint。失败样本没有authoritative transaction write，F5-F2继续保持`IMPLEMENTED / LIVE DIAGNOSTIC PENDING`。
   - F1.6/F2.1修复后的真实批次`f5f1-scope-local-return-types-fixed-point-low-5x1-20260813`仍严格为每题一个semantic attempt：provider response、schema和scope/Goal tree均为`5/5`，scope前缀、call alias、identity leak、configuration/unclassified error和unsafe normalization均为0。执行服务此前把F2 reconciliation/runtime issue合并进F1 report，导致落盘摘要误记`3/5 Plan authority`；分离authoring report与scope-shaped execution checkpoint后，对同一批五份原始响应进行确定性重放得到`5/5 Plan authority`，因此F5-F1关闭为`COMPLETE`。原始响应、normalization和执行错误未被改写。
   - 同批F5-F2诊断为authority-valid `63`、authority-invalid `3`、blocked suffix `7`、provisional executed `60`、dead-pruned `3`、transaction attempted `5/5`、transaction clean `3/5`，五题均生成checkpoint。和平二模与西青全部Goal通过；和平一模和河西的动态SourceRef被定位到具体step并继续执行独立分支；南开完成`5/6` Goal后保留runtime错误。F2问题不再污染F1 authoring gate，partial execution仍无authoritative ghost write；下一阶段由F5-F3消费这些checkpoint执行Goal replacement retry。
   - **F5-F3 Goal replacement retry（COMPLETE）**：retry wire升级为`functional-goal-repair/v4`，执行视图保持`planner-goal-retry-context/v2`。每次retry发送保留`answer_from`的完整上一版Plan和同构scope/Goal执行树；solved Goal只读，failed Goal完整替换`steps + answer_from`，scope级失败完整替换授权scope步骤。模型依据`required_answer{target_ref, answer_type}`显式选择答案producer；resolver验证return存在、Goal可见性、active runtime type和目标身份。模型指针失效时仅允许在唯一合法候选下审计式规范化，零候选或多个未被指针消歧的候选保存在`previous_repair_issue.details`并进入下一轮prompt。
   - solved Goal只有在runtime closure、answer、symbolic closure、provenance和typed checkpoint五项全部通过后才冻结。一个scope只服务失败Goal时仍整块开放；同一scope同时服务solved与failed Goal时，retry context在该scope显式列出`editable_step_ids`与`frozen_step_ids`，模型只完整替换editable子集，代码按原顺序保留并合并frozen producer。若失败Goal必须修改frozen producer，必须先显式扩大repair group，不能由replacement静默删除solved closure。retry从初始PlannerStateContext重建，只恢复solved Goal与冻结scope的typed checkpoint；恢复种子保存完整`FunctionalCallReconciliation`，resolved args、精确StateVersion和return allocation逐项复用，不重新解析latest state。failed Goal的成功前缀不冻结，上一轮provisional write全部丢弃。`PublishedGoalResultRef`只能解析到solved Goal的精确`answer_from`，在执行DAG中保留依赖但不反向扩张producer Goal集合；中间return和显示值不能恢复runtime identity。no-progress仅在相邻两轮的canonical Plan hash与typed issue signature同时不变时触发；同一Plan遇到新的执行诊断仍可继续修复。
   - 最新离线门禁为F5-F3专项`57 passed`、F5-C/D/transaction联合`117 passed`、capability与既有Planner契约`377 passed`、全量Solver`1844 passed, 12 skipped`，`git diff --check`通过。真实DeepSeek low-thinking批次`f5f3-goal-replacement-5x1-20260813-final`为`2/5`：河西在2轮内通过并恢复7个solved call，西青在3轮内通过；五题共7次Goal repair、`451293` tokens，configuration/unclassified error、repair authority drift和failed transaction ghost write均为0，所有样本solved Goal实际重执行为0。
   - 该批次后已泛化关闭三项代码问题：solved closure比较忽略不影响执行的可选`intent`；smoke终态诊断只取最后一轮错误；compiler注入的函数身份在catalog中显示为`same_compiler_selected_object`，`quadratic_from_constraints`明确禁止模型添加隐藏的`quadratic/parabola/x/all_coefficients`参数。南开两份原始响应无模型重放后不再出现`functional.goal_repair_boundary_violation`，两轮均无protocol error且恢复1个solved checkpoint；因历史批次没有第三份响应，该批次当时不能记为live通过。和平一模仍需验证角条件与函数状态能力，和平二模最终停在`PathTransformation`对象身份错配，后者按阶段边界转入F5-F4。这是F5-F3关闭前的阶段性证据；最终`COMPLETE`状态以20260818的`15/15`批次为准。
   - Pass 1不再要求模型复制scope树，但每个Goal必须输出一个局部`answer_from{step_id, return}`作为答案producer意图。`functional-plan-content/v2`动态schema锁定合法scope/Goal key；assembler生成完整树并省略空集合，再用代码验证或唯一规范化该指针后写入内部canonical答案binding。解析器只吸收一个可证明无歧义的冗余尾部`}`或`]`，其他JSON错误仍fail loud。无法验证或唯一绑定答案时，下一轮同时收到typed validation feedback、authored指针、候选return清单和上一份规范化content候选。
   - content/repair wire切换后的离线证据：content schema/assembler/JSON normalization、独立repair prompt、replay与smoke联合`89 passed`；F5-C/D、scope authority、transaction与跨scope版本联合`258 passed`；全量Solver`1867 passed, 12 skipped`，`git diff --check`通过。生产代码与当前文档中的旧树形authoring模板、旧repair协议和旧invalid-plan字段引用为0。真实DeepSeek批次`f5f3-content-authority-5x1-20260814`为`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 plan authority`、`2/5 completion`；河西和西青在第3轮通过。configuration/unclassified error、repair authority drift和failed transaction ghost write均为0，但南开出现2次solved Goal重执行。该记录描述的是关闭前的阶段性状态；最终`COMPLETE`状态以20260818的`15/15`批次为准。
   - **F5-F3.1 MathObject latest-state与完整Goal DAG（COMPLETE）**：稳定Entity SourceRef不再要求LLM静态管理每一版状态；无前序写入时读取Problem snapshot，有写入时canonicalizer选择当前scope/Goal内最近可见且类型兼容的同MathObject return并降为exact StepResultRef。显式StepResultRef仅用于匿名值、历史非latest读取和producer消歧。checkpoint将可执行子图的binding signature与完整canonical Plan的Goal closure分开保存，并用reconciliation typed dependency graph补齐condition/materialized-state隐藏边；solved restore因此包含全部真实依赖。共享scope step失败时只开放对应scope replacement，consumer Goal标为blocked并保留完整执行树，不再因answer暂未绑定而被误标成多个editable failure。Retry prompt以Previous Canonical Plan作为唯一authored wire，执行树只发送`step_id/status/resolved_inputs/actual_outputs/typed_issue/blocked_by`增量；稳定Problem/原则/catalog位于动态schema、Plan和retry delta之前，system不再嵌入每轮变化的authority schema，从而形成DeepSeek可复用前缀。联合F5-C/D、transaction与跨scope门禁`241 passed`。
   - **F5-F3.2 Runtime-result equivalence与Goal答案重绑定（IMPLEMENTED）**：capability、typed input、effect key、MathObject和StateVersion identity只用于发现“可能重复”的step，不能据此合并或删除。候选step必须在隔离的runtime probe路径真实执行；只有runtime type双向兼容、MathObject identity、自由Symbol identity和实际符号结果全部相等时，transaction层才生成带审计的call/return alias，并从初始Context做一次clean replay后删除重复write。若候选step同时是Goal答案producer，代码保留只指向已提交canonical StateVersion的answer-alias provenance，不提交第二份对象状态；answer gate继续校验精确版本、MathObject和Goal authority。结果不等时产生`planner.runtime_state_equivalence_conflict`并完整回滚，字符串、step名称、输入JSON或wire顺序均不得作为等价证明。隐式latest读取可以按typed StateVersion authority排序，显式StepResultRef仍指向模型选择的候选并等待实际比较。
   - **F5-F3.3 Scope-local StateVersion authoring（IMPLEMENTED）**：题面中的抛物线等Entity在全题共享一个MathObject identity，但兄弟scope使用不同局部系数、点或方程时必须分别生成scope-local StateVersion；共享identity不构成把状态producer提升到祖先scope的依据。Pass 1与repair prompt以及`quadratic_from_constraints` capability都显式区分这两层，并要求开放状态的`free_parameters`填写当前scope约束后的一组完整非空独立基底，闭合状态允许`[]`或省略；runtime可证明等价的基底均合法。删除按下游Goal或consumer反推、补写或收窄free-parameter basis的确定性repair；代数分析只验证当前step真实约束。step放错scope时，typed feedback同时给出step scope、同名ref的candidate owner scopes，并解释“共享MathObject不共享局部StateVersion”；由LLM在授权scope/Goal replacement中移动或重建producer，代码不自动搬step。本轮F5-F3专项为`200 passed`，相关scope/prompt/reconciliation为`373 passed`，全量Solver为`1884 passed, 12 skipped`，`git diff --check`通过；尚未用新prompt重跑付费live smoke。
   - Pass 1与repair都接受LLM authored `answer_from`作为答案producer选择；两者都不采用“最后一个step”、step名称或字符串相似度作为权威。代码独立建立目标身份、active return type、词法scope和DAG合法候选集：显式指针命中任一合法候选时优先保留模型选择，错误指针只在唯一候选时被审计式规范化，多候选且指针无效时fail loud。solved Goal保留已验证binding；failed Goal可在repair中同时改写steps和答案producer。真正的重复step合并仍只依据runtime结果等价，不由答案resolver猜测。
   - 和平二模批次后又关闭四项通用边界：content parser在严格schema校验前仅省略空的可选step map并记录normalization；稳定SourceRef可确定解析到当前Goal或可见祖先scope中同一题面对象的最近answer result，但不会隐式跨入sibling Goal；retry checkpoint保留prompt-safe的typed identity差异、动态读取要求和公开return role；与任何未完成Goal无关的dead diagnostic branch不再重新打开已解Goal scope。最新本地门禁为FunctionalPlan契约`318 passed`，F5-F3/C/D、transaction与跨scope联合`150 passed`，全量Solver为`1876 passed, 12 skipped`。该结果是最终付费live批次前的阶段性证据；最终`COMPLETE`状态以20260818的`15/15`批次为准。
   - **F5-F3.4 Unified Method diagnostics（COMPLETE；原实现计划标题F5-F3.1）**：新增`functional-diagnostic-authority/v1`与`functional-prompt-diagnostic/v1`，Method、resolver、compiler和runtime check先形成内部authority，再由唯一Projector通过F5-C BindingCatalog投影为Goal可见SemanticRef。完整执行现场仅进入checkpoint/debug，Prompt只保留公开对象、角色、参数、expected/observed和固定repair action，不再使用`<internal-identity-omitted>`。P0 13个Method与`_common.py`已全部迁移为typed `StatelessMethodError`，直接`raise ValueError`为0；未迁移异常、返回契约错误和无法映射的内部身份统一归类为configuration，在Goal repair调用前fail loud，不消耗semantic retry。两份诊断schema及checkpoint快照由同一脚本生成；专项`13 passed`、诊断/Goal执行/transaction/Method联合`205 passed`、全量Solver`1912 passed, 12 skipped`，`git diff --check`通过。
   - F5-F3最终live证据为`f5f4-version-authority-fix-5x3-20260818`：DeepSeek low thinking、并发15、五题各三份全部在三轮内完成。批次共`20`次semantic attempt、`5`次Goal repair、`27`个solved call恢复；`15/15`通过protocol、Plan authority、reconciliation、compile、transaction和completion gate，且solved Goal重执行、repair authority drift、failed transaction ghost write、configuration/unclassified error与prompt identity leak均为`0`。F5-F3据此关闭，不再运行额外付费验收；Macro bounded runtime-search继续属于F5-F4。
   - **F5-F3 restore/publication authority加固（IMPLEMENTED）**：Pass 1 content与scoped reconciliation统一使用`ReturnObjectAuthorityResolver`，按显式`output_targets`、Goal answer、identity constraint、公开identity arg和compiler selector的固定优先级解析具名return，不再维护两套猜测规则。完整canonical scope树只派生一份轻量`authored return consumers` sidecar，局部不可执行consumer不会复活，但producer仍会分配完整DAG已引用的匿名return。checkpoint restore不新增pre-authority，而把原混合signature拆为严格的`source_read`、严格的`runtime_write`和可重建的`answer_publication`；普通consumer closure及非答案public return从完整DAG和canonical allocation重建，solved Goal的显式答案发布仍严格校验。恢复索引对`StateVersionId`、`CallResultId`和`ConditionId`分开注册：CallResult记录producer、return、scope、runtime type、exact value与provenance，Condition记录可信PlannerStateContext中的不可变事实；匿名`MinimumExpression`、候选集、Path witness可在开放Goal中继续以exact result消费，诊断按CallResultId还原为prompt-safe StepResultRef。若editable scope更换了blocked Goal的答案producer，`functional-goal-repair/v4`仅开放`answer_binding_replacements`更新`answer_from`，Goal-local steps仍只读，solved Goal仍禁止修改。专项retry/transaction/diagnostic联合`152 passed`；全量Solver回归`2076 passed, 12 skipped`。
   - **F5-F4.1 Equal-length ray unique-role reference path（COMPLETE，受限范围）**：entity-only Plan、transaction、PathMinimumWitness、Goal checkpoint与Verified execution竖切已经完成，但只覆盖四个结构化Fact恰好确定一个角色组合的路径。当前production仍在compiler拒绝多结构候选，并在成功执行后为单个候选生成runtime-search报告，不能宣称通用pre-binding search已经落地。
   - **F5-F4.2 Runtime Authority Convergence（COMPLETE）**：v2 scoped authority、typed graph、Macro preparation、F5-C、Method view、Goal checkpoint和Verified execution已经收敛为单向owner链；v1只保留为派生执行IR和显式debug入口。仅`equal_length_ray_path_reduction`声明`runtime_search`，其winner在per-call F5-C finalization之前由隔离shadow执行选定并clean replay；其余未迁Macro暂时降为`direct`。Goal checkpoint v3是唯一生产restore协议，公开`solve_problem()/solve_verified()`只走`run_scoped()`，不会调用legacy v1 planner。复审同时关闭mixed-scope增删step时的frozen区间、content identity constraint、shadow异常分类、Registry builder/evidence ownership、lowering真实call-count tie-break、canonical search签名、debug Entity handle及debug selector回流recipe compiler等残留。核心组合门禁`172 passed`，离线全量Solver回归`2183 passed, 12 skipped`；最终DeepSeek low-thinking并发15批次`f5f42-authority-convergence-final-live-5x3`为`15/15`，17次semantic attempt、2次Goal repair、12个solved restore；solved Goal重执行、ghost write、repair drift、identity leak、configuration及unclassified error均为0。具体owner与验收证据见[Track F整体实现计划的F5-F4.2章节](problem-extraction-context-implementation-plan.md#f5-f4-2-runtime-authority-convergence)。
   - **F5-F4.2R Binding Selector Retirement（COMPLETE）**：Method spec只声明domain/runtime type与`identity | latest_state | immutable_value | exact_result`视图，per-call F5-C/`MethodInputReadAuthority`唯一确定实际Entity、Condition、StateVersion或CallResult。A-D已迁移全部生产input：Entity/State、Fact/Condition、几何output/transition、Macro prepared role、free-parameter basis和exact parameter substitution均使用strict source或typed derivation；生产Legacy input/expansion、`FunctionAdapterRegistry._select/_expand`、selector registry、prefix grammar、`SelectorSemantics`、`compiler_selector` read source及空ledger行已删除。optional零证据允许明确省略，任何多候选或跨证据冲突在F5-C fail loud。显式debug authority adapter与debug-only等长射线provider不进入公开Solver。定向门禁`220 passed`，L0 affected为`1204 passed, 27 deselected`，L2 contract为`2330 passed`，L3 full为`2384 passed`；生产旧input selector静态引用为0。补充live批次`f5f42r-selector-retirement-live-5x3-20260823`为`15/15`，共17次semantic attempt、2次Goal repair和16个solved restore，configuration、unclassified、ghost write、repair drift、identity leak及solved Goal重执行均为0。详细契约与门禁见[Track F整体实现计划的F5-F4.2R章节](problem-extraction-context-implementation-plan.md#f5-f4-2r-binding-selector-retirement)。
   - **F5-F4.3 原子路径Macro迁移（IN PROGRESS，分段实施）**：A已完成，4类Method companion output由MethodSpec声明固有materialization，`MethodOutputWriteAuthority`从唯一`FunctionalReturnAllocation`钉住对象、scope、version、目标路径和注册别名；family重复声明、字符串selector、专用handle推断及standalone等长射线debug角色provider均已删除，checkpoint v3保存精确output authority。2026-08-27已将透明Macro展开实现回滚到`56500bb`；新设计固定“一个Macro = 一个canonical Plan step = 一个原子transaction = 一个公开根诊断”，内部Method、candidate、winner与witness不进入Plan/Retry wire。下一步B固化原子边界、固定角色公开规则并以`equal_length_ray_path_reduction`建立golden门禁；C优先迁移和平二模正方形路径；D迁移南开标准及两动点路径；E合并加权路径两步公开链；F物理删除公开Path内部类型、旧能力及Explanation/Visual回退后运行L3和并发15的`5×3`。每段独立提交，Macro只有在Registry、shadow验证、clean replay、witness与restore全部接通后才能从`direct`切为`runtime_search`。完整输入输出、门禁和提交边界见[路径最值原子Macro设计](path-minimum-macro-redesign.md#10-分阶段实施)。
   - **F5-F5 Teaching scope与退役**：根据call-to-Goal authority生成`TeachingStepPlacement`和按Problem scope嵌套的学生步骤结果。教学placement消费不可变的`plan_scope_id`与`semantic_owner_scope_id`，并与`execution_scope_id`分别审计；不得从运行位置反推语义或讲解归属。通过两组5×3后删除`functional_plan/v1`、authored scope fixture和兼容分支。物理清理同时删除底层reconciler/replay的`problem_binding_catalog=None`与全局`semantic_read_catalog()`回退、v1的`replace_answer_ref_with_goal_target`/`bind_unique_condition_role`确定性repair，并将裸`RuntimeOrchestrator.solve(ProblemIR)`私有化；deterministic测试统一通过`solve_problem_ir_debug()`。`planner-problem-view`及v2 Plan/Retry schema对每个typed variant使用`additionalProperties: false`，不再依赖Python projector兜底宽松item字段。

F5-A/B/C/D当前证据：五题accepted Context可确定加载并各生成一个`problem-planning-context/v1`；南开/和平二模分别生成6/4个GoalView，其余三题各3个。五份scope-native recorded FunctionalPlan已通过validation、reconciliation、direct compile、authoritative closure、transaction、Goal checkpoint v3和Goal-scoped retry projection，SemanticRef到runtime/source/typed identity及write/result/checkpoint provenance覆盖缺口为0。missing、revision、Goal、source unit与call signature mutation及repair foreign-Goal mutation均fail loud；answer-check撤销commit后只保留带authority的provisional runtime evidence，不产生locked checkpoint；失败事务ghost write为0。

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
