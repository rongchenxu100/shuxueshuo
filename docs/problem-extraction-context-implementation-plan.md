# Track F：图片到 Problem 领域模型实现计划

## 1. 目标与状态

Track F把题目来源转换为可追溯、可局部修复并可确定投影到Solver的领域对象：

```text
图片 / PDF
  -> F0 Gold corpus
  -> F1 Source identity + immutable Context
  -> F2 SourceObservation
  -> F3 problem-domain/v1 + ProblemDraft
  -> F4 validation + freeze + problem-repair/v1
  -> VerifiedProblem + Solver ProblemIR + projection manifest
  -> F5 scoped planning view + Solver cold path
```

当前状态：

| 阶段 | 状态 |
| --- | --- |
| F0 Gold corpus | `COMPLETE` |
| F1 Source fingerprint / Context基础 | `COMPLETE` |
| F2 SourceObservation / review pack | `COMPLETE` |
| F3 Domain extraction | `COMPLETE` |
| F4 Validation / patch retry authority | `COMPLETE` |
| F5-A Bundle authority | `COMPLETE` |
| F5-B Scope-native planning projection | `COMPLETE` |
| F5-C Goal-scoped typed binding | `COMPLETE` |
| F5-D Retry provenance / Goal-scoped retry | `COMPLETE` |
| F5-E Solver cold path | `COMPLETE` |
| F5-F Scope-derived FunctionalPlan / teaching placement | `NEXT` |

系统尚未上线。Extraction只支持当前schema，不保留旧candidate、整份ProblemIR retry或Context迁移链。

## 2. 当前架构

```text
F2 Context + 完整selection图片 + 精简OCR
  -> Doubao problem-domain/v1
  -> ProblemGraph
       source
       root_scope
         entities[]
         facts[]
         goals[]
         children[]
  -> ProblemDraft
  -> ProblemDomainValidator
  -> verification stamps + repair cone
  -> problem-repair/v1
  -> VerifiedProblem
  -> ProblemDomainProjector
  -> canonical Solver ProblemIR + provenance manifest
  -> ProblemExtractionContext v3
```

完整题图始终是语义权威。OCR只提供高可信印刷文字、可靠公式、聚合笔迹信息和遮挡定位，不替模型决定实体、关系、目标或family。

F5不会把扁平Solver ProblemIR重新提升为scope语义权威。accepted Context同时保存嵌套`VerifiedProblem`、扁平Solver ProblemIR和两者之间的projection manifest：前者服务Planner语义视图，后者服务ContextBuilder与runtime。

## 3. Problem Domain Contract

### 3.1 `problem-domain/v1`

Pass 1输出：

```text
schema_version
problem_id
family_id
source.question_number / score
root
  id / label / source_text
  entities[]
  facts[]
  goals[]
  children[]
```

规则：

- scope递归嵌套，不输出parent、scope_id或valid_scope；
- 引用按当前scope到祖先scope进行词法解析，禁止读取sibling；
- 禁止ancestor-chain同名id遮蔽；
- scope/entity local id由模型输出，fact/goal unit id由代码生成；
- Entity只保存身份、类型、label与必要角色；
- Fact是坐标、构造、成员关系、方程、约束和最值事实的唯一权威；
- 每个独立求值对象对应一个原子Goal；
- 不输出runtime handle、description、value_type、target_path、答案或解法。

进入validator前执行可审计的确定性规范化：

- 只有题面文字或其他Fact/Goal实际引用原点`O`时，才将其统一提升到根scope并保留唯一`point_construction(origin)`；只有孤立Entity和自述origin Fact时删除该无来源身份；
- 父子词法链上`kind + label`相同且身份属性兼容的Entity合并到最近祖先，所有结构引用同步改写；sibling之间不合并，类型或身份属性冲突时继续fail loud。
- `point_on_curve_with_x.x_range`只展开有限端的严格`symbol_constraint`，`n < +inf`等恒真约束会删除；同scope的`minimum_value_given`按目标语义展开等价`minimum_target`。
- `square_center`机械展开为中心位于两条对角线；“对称轴与x轴交点”的两个轴从属机械归一为`axis_x_intercept`。已有primitive不重复创建，所有变换记录canonicalization action。

合并的是语义身份，不是运行状态。各子问中的`symbol_value`、constraint、coordinate等Fact仍保留在原scope，投影后形成同一MathObject的不同scope-local StateVersion。

首版Entity：

```text
symbol | point | quadratic_function | named_line | named_ray
polygon | scalar_expression
```

首版值对象：

```text
SegmentTerm | RayTerm | AngleTerm | LengthSum | ScaledLengthTerm
```

首版Fact覆盖函数表达式、点构造、方程、Symbol约束和值、坐标、曲线/轴/线段/射线从属、象限、中点、直角、角和、等长、长度、正方形和最值。

### 3.2 Draft与Verified状态

```python
ProblemDraft
  graph
  revision_id
  parent_revision_id
  unit_registry
  validation_report
  verification_stamps
  repairable_unit_ids

VerifiedProblem
  graph
  revision_id
  semantic_hash
  family_id
  verification_proof
```

`revision_id`锁定精确wire和parent revision；`semantic_hash`解析局部引用并忽略一致的local-id重命名。`VerifiedProblem`只能由promotion service创建。

## 4. Validation、Freeze与局部Retry

`ProblemDomainValidator`一次运行全部独立门禁：

1. scope树、local id和source text；
2. lexical reference、typed reference与sibling隔离；
3. expression解析和自由Symbol可见性；
4. source literal与伪Symbol检测；
5. constructor、coordinate、symbol value、未使用纵坐标占位符和重复定义冲突；
6. Fact内部约束与Goal原子性；
7. printed OCR覆盖；
8. LLM所选family的source primitive与do-not-use contract；
9. 领域图到Solver ProblemIR的可构造性；
10. ContextBuilder与family pure runtime preflight。

Validator不调用LLM、Planner或完整Solver。每条issue携带`unit_ids`、依赖unit、repair action和可选F2 region。

每个unit获得：

```text
semantic_signature
validator_ids
dependency_signatures
status = verified | invalid | dependent
```

只有未变化且不在repair cone中的verified unit被冻结。改变一个依赖只使相关consumer失效，不解冻整棵scope树。

### `problem-repair/v1`

```text
base_revision_id
replacements[]
additions[]
removals[]
```

- Draft建立后只接受patch，不接受整题替换或JSON Patch；
- replacement保持unit kind、owner scope和unit id；
- addition只能写入repair cone授权scope；
- removal必须由blocking issue直接授权；
- frozen mutation、跨revision、隐式旁路修改和无语义进展均fail loud；
- retry继续发送完整题图；source/遮挡问题才附F2 authority zoom；
- Pass 1关闭thinking，semantic retry使用low thinking。

## 5. Projection与Context v3

`ProblemDomainProjector`只做确定性物理投影：

- 展平scope树并生成Solver scope id；
- 解析lexical reference并生成runtime handle；
- 物化Segment/Ray/Angle等scope-local值对象；
- 从FamilySpec投影唯一pattern/problem_type；
- 为每个runtime node记录source unit provenance。
- 将`curve_at_x`机械展开为runtime point definition与`point_on_curve` fact；二者共享同一source unit，不新增源语义。

投影器不得新增数学事实、改变family、跨sibling共享值对象或从family要求反推缺失语义。

`problem-extraction-context/v3`的projection状态为：

```text
pending
blocked:  last ProblemDraft + validation
accepted: VerifiedProblem + Solver ProblemIR + projection manifest + revision/hash/family/validation
```

accepted与blocked artifact互斥；每次attempt均进入不可变ledger并受共享budget约束。

## 6. Provider、Debug与Smoke

固定provider配置来自`server/.env`：

```text
DOUBAO_API_KEY
DOUBAO_BASE_URL
DOUBAO_MODEL=doubao-seed-2-1-turbo-260628
```

请求参数：

```text
temperature=0
response_format=json_schema(strict=true)
stream=true，首个完整顶层JSON结束时主动关闭响应流
max_tokens=4096
默认request_timeout=120s；smoke CLI默认300s，验收可显式放宽
timeout/429/5xx最多transport retry一次
pass1 thinking=disabled
retry thinking=enabled, reasoning_effort=low
```

主动截停可能早于provider最终usage chunk，因此metadata显式记录`usage_complete=false`，不得把缺失usage解释为零消耗。

每轮仍发送完整selection。长边超过1600像素时只做等比例降采样，不裁剪题面；原selection artifact与实际传输artifact都进入attempt ledger。

Debug按attempt保存完整题图/zoom、prompt、redacted request、raw response、ProblemDraft、validation、verification状态、repair cone、patch diff、projection、usage、latency和最终Context。

`problem_domain_smoke`只做domain extraction，不调用Planner或完整Solver。

单sample的严格门禁同时要求：成功promotion为`VerifiedProblem`、完整源输入、Draft建立后的semantic retry全部使用`problem-repair/v1`、family与authored domain gold一致、domain semantic hash零差异、Solver ProblemIR确定性投影semantic diff零差异。任一项失败时`ok=false`；该门禁不调用Planner或完整Solver。

### 最终验收证据（2026-08-10）

- F3/F4 authority联合门禁：`172 passed`。
- 全量Solver离线回归：`1557 passed, 12 skipped`；`git diff --check`通过。
- `problem-domain-final-5x1-20260810`中四题首轮严格通过；河西暴露无穷端约束死循环，修复后`problem-domain-hexi-final-fix-20260810`首轮严格通过。
- `problem-domain-final-acceptance-20260810`的15份真实响应全部首轮accepted，family和Solver ProblemIR投影均为15/15一致；其中两份南开使用“x轴从属+对称轴从属”表达`axis_x_intercept`，历史batch按旧Domain hash记录为13/15。
- 最终canonicalizer对上述15份live artifact确定性重放后domain semantic hash为15/15一致；`problem-domain-nankai-final-canonicalization-20260810`再以最新prompt和代码真实补跑，3/3首轮严格通过。
- 完整题图输入率100%，semantic retry协议门禁100%，配置错误和未分类错误为0，Planner与完整Solver调用数均为0。

历史batch summary保持原样；完成判定使用原始live artifact、最终代码确定性重放和定向live复验，不回写旧结果。

## 7. 测试与退出门禁

离线门禁：

```bash
cd server
uv run pytest \
  tests/solver/test_problem_domain_schema.py \
  tests/solver/test_problem_domain_model.py \
  tests/solver/test_problem_domain_validation.py \
  tests/solver/test_problem_domain_projection.py \
  tests/solver/test_problem_domain_retry.py \
  tests/solver/test_problem_domain_context.py \
  tests/solver/test_problem_domain_debug.py \
  tests/solver/test_problem_extraction_observations.py \
  tests/solver/test_problem_extraction_context.py \
  tests/solver/test_problem_extraction_gold_corpus.py -q
uv run pytest tests/solver -q
git diff --check
```

真实验收：

```bash
RUN_LLM_INTEGRATION=1 uv run python -m \
  shuxueshuo_server.solver.extraction.problem_domain_smoke \
  --case all --samples-per-case 1 --max-attempts 3 \
  --concurrency 5 --provider doubao --request-timeout-seconds 600 \
  --batch-id problem-domain-contract

RUN_LLM_INTEGRATION=1 uv run python -m \
  shuxueshuo_server.solver.extraction.problem_domain_smoke \
  --case all --samples-per-case 3 --max-attempts 3 \
  --concurrency 5 --provider doubao --request-timeout-seconds 600 \
  --batch-id problem-domain-acceptance
```

完成条件：

- 15/15在三轮内accepted；
- family与authored domain gold一致；
- domain semantic diff和Solver projection semantic diff为0；
- frozen mutation、patch drift和unclassified error为0；
- 完整题图输入率100%，Draft建立后的retry均为patch；
- Planner和完整Solver调用数为0；
- recorded replay无hash drift；
- Pass 1 schema不超过20 KB；domain payload不超过旧Solver fixture的75%；repair patch不超过当前Draft compact payload的30%。

上述门禁已经满足，F3/F4标记`COMPLETE`，F5解锁。

## 8. 下一阶段：F5 Scoped Planning与Solver生命周期接线

### 8.1 权威边界

F5消费一个不可变bundle：

```text
VerifiedSolverProblemBundle
  extraction_context_id
  verified_problem_artifact_id
  solver_problem_projection_artifact_id
  validation_artifact_id
  problem_revision_id
  problem_semantic_hash
  family_id
  bundle_id
```

Context v3的JSON wire仍使用历史字段`solver_problem_ir_artifact_id`，但代码只通过
`solver_problem_projection_artifact_id`语义alias读取；该引用的artifact kind固定为
`solver_problem_projection`，内容必须是`solver-problem-projection/v1` envelope，绝不是裸ProblemIR JSON。

三份artifact职责不同：

- `VerifiedProblem`：题面scope树、Entity、Fact和Goal的语义权威；
- `solver-problem-projection/v1`：原子保存canonical Solver ProblemIR和projection manifest；前者供ContextBuilder、family admission和runtime使用，后者保存source unit、ProblemIR handle、goal answer handle和runtime identity之间的确定映射；
- validation report：必须为成功且与VerifiedProblem verification proof完全一致。

不建立独立manifest artifact，避免ProblemIR与manifest出现双份提交漂移。Solver ProblemIR schema保持不变。F5不要求把runtime wire改为嵌套结构，也不允许Planner从扁平数组、显示label或handle猜回scope。

### 8.2 Planner语义视图

从VerifiedProblem确定派生只读视图，不新增持久化语义：

```text
ProblemPlanningContext
  planning_context_id
  bundle_authority_token
  problem_revision_id / problem_semantic_hash（token只读投影）
  problem_id / family_id / source
  scopes[]
  goal_views[]
  ref_authorities{}

ProblemPlanningScope
  source_scope_unit_id（authority only）
  scope_id / parent_scope_id
  source_text[] / entities[] / facts[]
  available_refs[]
  visible_goal_unit_ids[]（authority only）

ProblemPlanningGoalView
  goal_unit_id（authority only）
  owner_scope_id / scope_path[] / visible_scope_ids[]
  answer_ref
  semantic_reads[]
  goal_payload

PlanningReadAuthority
  semantic_ref
  runtime_node_id / source_unit_ids[]（authority only）
  owner_scope_id / visible_goal_unit_ids[]
  usage = input | answer
```

`to_prompt_payload()`不直接序列化上述authority形状，而输出：

```text
planner-problem-view/v1
  family_id
  source
  root_scope
    id / text
    entities[]  # exact ref内嵌在Entity
    facts[]     # exact ref内嵌在Fact
    goals[]
    children[]
```

scope嵌套本身定义词法可见性：Goal只能读取自身scope及祖先scope。Prompt不再输出`available_refs`、`semantic_reads`、`identity_only_reads`、`scope_path`或shared/local重复切片；每个可用SemanticRef只在对应Entity或Fact上出现一次，Goal直接位于owner scope。空的`entities/facts/goals/children`在prompt中省略。内部authority仍完整保留逐Goal allowlist、source unit、runtime node和typed identity，sibling隔离继续由代码验证。

F5-E切换默认入口时暂时继续使用`functional_plan/v1`和现有`SemanticRef`。F5-C只能通过`input_authorities_for_goal(goal_unit_id)`取得当前Goal的输入catalog，并通过`answer_authority_for_goal(goal_unit_id)`取得唯一return authority；禁止遍历全局`ref_authorities`后自行过滤。Planner response schema只暴露当前Goal视图允许的scope/ref。现有B2 placement根据typed dependencies和LCA计算实际`execution_scope_id`。

F5-F将LLM输出升级为`functional_plan/v2`，并让Problem、Plan和Retry共享同一棵scope/Goal骨架。Plan不复制题面Entity/Fact，但按同样的`scope_ref`递归组织：scope下可以有共享步骤，每个Goal拥有自己的完整步骤。scope与Goal identity必须逐项匹配VerifiedProblem，模型不能创建、删除或移动scope/Goal；步骤所在Goal是authoring边界，真正的语义owner scope、execution scope、typed binding和canonical return authority仍由F5-C/B2验证和派生。具名题面对象可继续使用同一个SemanticRef，服务端选择唯一、可见、类型兼容的最近前序状态；只有匿名内部结果、非最近版本或多producer歧义才需要显式CallResultRef。

F5-F同时把“整份计划先全部编译，再开始执行”改为增量provisional执行。JSON必须完整可解析；服务端先验证scope/Goal骨架、step identity、capability、typed dependency shell、DAG无环和Goal/answer authority。随后对ready step逐个运行preparation、direct compile、sandbox method、result type/provenance和symbolic closure校验。内部执行记录保持step粒度，但冻结边界提升为`GoalExecutionCheckpoint`和`SharedScopeExecutionCheckpoint`：Goal只有在answer、runtime、closure和provenance全部通过后才成为`solved`；失败Goal中此前成功的step只作为诊断证据，不成为模型不可修改的冻结单元。与失败Goal无依赖的sibling Goal继续执行。所有required Goal通过前不产生authoritative Context write，solved Goal结果通过当前solver run的checkpoint发布，而不是提前写入全局Context。

LLM本身无会话状态，F5-F retry必须显式发送三个相互对齐的完整输入：当前`planner-problem-view/v1`、上一版完整canonical `functional_plan/v2`和`planner-goal-retry-context/v1`执行树。上一版Plan不按repair cone裁剪，保留全部scope、shared steps、solved Goal与failed Goal，作为本轮思路基线；执行树只引用其中的`step_id`，不重复复制步骤定义。所有Goal同样保留在执行树中：`solved` Goal以`editable=false`提供每一步实际执行结果和可跨Goal绑定的`published_results`；`failed` Goal以`editable=true`提供每一步的实际输入、实际输出、状态、typed error、blocked suffix和Goal issues，允许模型理解失败现场并完整重写该Goal。完整step结果可以帮助推理，但只有`published_results`拥有跨Goal绑定权威。

每个`step_execution`至少包含：

```text
step_id
status = succeeded | compile_failed | runtime_failed |
         result_failed | closure_failed | blocked | not_run
resolved_inputs[]?     # SemanticRef/上一步return名称与prompt-safe实际值
actual_outputs[]?      # return名称、实际值/表达式、result form、free symbols
error?                 # code、path、message及结构化prompt-safe details
blocked_by[]?          # 直接失败step；不生成重复的次生root issue
```

上述字段来自真实preparation/compiler/runtime/closure记录，不能由静态计划预测或错误文案反推；不得暴露MathObjectId、StateVersionId、source unit、runtime path或authority token。首轮使用严格`functional_plan/v2` response schema；建立可信plan后，retry切换到`functional-goal-repair/v1`，只接受失败Goal的完整`goal_replacements`，以及失败shared block的完整`shared_scope_replacements`。call级replacement/addition/removal、返回整份Plan、修改solved Goal、错误`base_plan_id`或越出开放Goal集合全部fail loud。

三个LLM wire使用同一scope identity：

```text
planner-problem-view/v1
  root_scope
    scope_ref / source semantics / goals / children

functional_plan/v2
  root_scope
    scope_ref
    shared_steps?[]
    goal_plans?[]
      goal_ref
      steps[]
    children?[]

planner-goal-retry-context/v1
  base_plan_id
  previous_plan             # 完整canonical functional_plan/v2，只出现一次
  root_scope
    scope_ref
    shared_execution?
    goals?[]
      goal_ref
      status = solved | failed | blocked | pending
      editable
      step_executions[]
      published_results[]
      issues[]
    children?[]
```

空的`shared_steps/goal_plans/goals/children`均省略。三棵树的scope与Goal集合由代码逐项对齐，不能依赖数组位置、label或LLM自由命名。

### 8.3 分步实现

1. **F5-A Bundle authority（COMPLETE）**
   - accepted Context loader校验完整ancestor chain、三个authority artifact、revision、semantic hash、family和dependency闭包。
   - projection manifest覆盖每个scope/entity/fact/goal source unit和全部runtime node；折入Entity的function/point Fact仍保留source provenance。
   - blocked、pending和任一artifact漂移不得进入Planner。历史accepted Context是有效不可变快照；只有显式expected authority token不匹配时才判stale。
   - 五题bundle可确定重放，F0–F5-A联合回归`318 passed`；加载阶段OCR、LLM、domain projector、Planner和完整Solver调用数均为0。

2. **F5-B Scope-native planning projection（COMPLETE）**
   - 从VerifiedProblem建立一个全题`ProblemPlanningContext`及逐Goal可见authority；一道题仍只对应一次未来Planner调用。
   - 每个GoalView严格包含owner scope及祖先；跨sibling source/runtime mapping、漏Goal、漏scope或漏runtime node均fail loud。
   - 每个非scope runtime node恰有一个稳定SemanticRef；answer ref仅对自己的Goal可见，folded Fact仍保留在source视图，combined Fact保留一对多provenance。
   - 内部GoalView的read authority必须与可见scope refs完全一致；F5-C只能调用按Goal过滤的authority API。
   - prompt payload使用单棵嵌套scope树，每个ref只出现一次，并且不暴露source unit、runtime handle、artifact、Bundle token、MathObjectId或StateVersionId。
   - prompt形状由checked-in `planner-problem-view.schema.json`与Python schema双源门禁锁定；authority payload不作为外部wire。
   - 五题GoalView数量为`6/4/3/3/3`；F5-A/B定向联合门禁`81 passed`，全量Solver回归`1587 passed, 12 skipped`。
   - 本阶段未修改`StrategyPayloadBuilder`或生产Planner输入；默认切换留到F5-E。

3. **F5-C FunctionalPlan binding（COMPLETE）**
   - `ProblemPlanningBindingCatalog`只通过F5-B按Goal authority API，将`SemanticRef -> runtime node -> source unit -> canonical handle -> typed identity`确定绑定；不调用全局semantic catalog，不使用alias、label、handle尾部或模糊匹配。
   - answer producer反向传播得到call服务的Goal集合。单Goal call使用该Goal allowlist；共享call只能读取各Goal allowlist交集。跨sibling read、answer串线、无Goal call和placement后可见性漂移均在compile前失败。
   - source Entity、Fact与初始state snapshot绑定`MathObjectId`、`ConditionId`及精确`StateVersionId`，禁止从演进中的Context隐式选择global latest。若同一个具名对象已有唯一、可见、类型兼容的前序call state，SemanticRef可确定性降为该精确CallResult；匿名结果、非最近版本或歧义仍必须显式使用`CallResultRef`。
   - Catalog只从未演进的typed slot派生ordinal-0 source snapshot；若PlannerStateContext中的对应slot已有write或latest不再是ordinal 0，重建Catalog直接报`planner.problem_source_binding_drift`，后续阶段必须复用原Catalog中的pin。
   - reconciliation挂载`FunctionalProblemBindingContext`，逐arg/return记录Goal、runtime node、source unit与C3 identity；direct preparation再次对sidecar、C3 ledger、B1 answer allocation及exact version做一致性审计。
   - semantic elaboration的per-call allowlist只含input authority；answer authority只允许出现在显式return binding，不能成为C3 implicit source。多source Goal target不再取首项，必须唯一映射或fail loud。
   - Catalog authority与reconciliation sidecar分别由`problem-planning-binding-catalog/v1`和`functional-problem-binding-context/v1`锁定，并与checked-in JSON Schema做双源门禁。
   - 五份scope-native recorded FunctionalPlan均通过validation、reconciliation、direct compile、authoritative symbolic closure与transaction；旧扁平fixture仍独立通过且生产代码没有alias fallback。
   - F5-C专项`26 passed`，F5-B/C与C3/transaction/C0.5联合门禁`115 passed`，全量Solver回归`1613 passed, 12 skipped`。
   - 保留B1 allocation、B2 placement、B3 finalization、C3 binding ledger和C4/C5 symbolic closure。F5-E后生产Strategy会在构造、payload和replay三处强制携带`problem_binding_catalog`；底层reconciler的nullable参数与全局`semantic_read_catalog()`分支仅服务尚未迁移的deterministic/debug测试，并在F5-F5随v1一起物理删除。

4. **F5-D Retry与provenance（COMPLETE）**
   - `ProblemCallSourceProvenance`只能从F5-C sidecar派生，记录planning context、problem revision/hash、canonical call、Goal集合、call binding signature和该call直接读取的Problem source units。`CallResultRef`与compiler selector不计入直接source read，跨call来源由typed dependency DAG恢复。
   - direct compile后、method执行前为全部versioned、value-only、companion与answer-alias write/result统一盖章；commit前审计missing、revision和per-return drift，失败整call回滚。`PlannerStateContext` hydrate保留实际write authority，checkpoint不得补造或覆盖缺失字段。
   - retry契约升级为`functional-retry-graph-checkpoint/v2`。顶层`problem_authority`固定PlanningContext与Problem revision，`problem_call_authorities`覆盖所有F5-C canonical calls；committed call、verified version和value-only result均携带同一call provenance。v1及其他旧checkpoint版本硬拒绝，不提供hydrate迁移；缺legacy binding signature只允许降为不锁call的`runtime_verified`证据。
   - locked call恢复时Goal、直接source units及完整input/return sidecar形成的call signature必须完全一致；即使wire微调后C3选源相同，也采用刻意的fail-loud。repair call可重编排，但不得越出原repair Goal集合。revision/hash漂移报`planner.retry_problem_revision_drift`，Goal/source/signature漂移报`planner.retry_problem_source_binding_drift`，不从SemanticRef、handle或错误文本恢复identity。
   - `ProblemPlanningRetryProjector`按repair call的Goal并集从可信PlanningContext重新生成视图，只展示这些Goal、祖先scope和去重shared context。source unit仅进入内部authority payload和projection signature，不进入prompt；revision/hash、runtime node、StateVersion和Bundle token同样隐藏。prompt审计采用结构化字段遍历，题面`source_text`碰巧等于内部ID不会误报；稳定call结果仍由既有typed issue dependency选择器按需提供。
   - answer-check撤销commit后，runtime result及其Problem provenance保留为`runtime_verified` provisional evidence，但committed call为空。五题transaction、checkpoint与retry view可确定重放，F5-D专项`31 passed`，指定联合门禁`146 passed`，全量Solver回归`1644 passed, 12 skipped`。
   - F5-D不重新运行OCR、豆包、domain canonicalizer/projector、Planner或完整Solver，也不切回authored fixture。scope-native接线仍为内部显式参数，生产默认切换留到F5-E。

5. **F5-E Production cold path（COMPLETE）**
   - 公开`solve_problem()`只接收`VerifiedSolverProblemBundle`；Strategy传入裸ProblemIR稳定报`planner.problem_bundle_required`。deterministic测试使用独立`solve_problem_ir_debug()`。
   - `RuntimeOrchestrator.solve_verified()`从Bundle派生唯一`VerifiedPlannerProblemAuthority`。每轮从同一Bundle重新构造ProblemIR、RuntimeContext和初始PlannerStateContext，再构建PlanningContext与BindingCatalog；accepted Problem revision/hash在所有Planner attempt中固定。
   - recorded与DeepSeek Strategy均强制消费scope-native fixture、PlanningContext和BindingCatalog。Planner payload只包含`problem_planning_context`，不包含`problem_ir`；retry有checkpoint v2时只发送repair Goal视图，尚未形成checkpoint时发送完整PlanningContext。
   - Strategy生产路径不再调用全局`semantic_read_catalog()`，不接受`problem_authority=null`，也不迁移v1 retry checkpoint。内部canonical Solver ProblemIR只用于HandleRegistry、ContextBuilder和runtime identity，不进入LLM prompt。
   - `RuntimeSuccessArtifacts`保存Bundle token、PlanningContext、BindingCatalog、最终PlannerStateContext和Problem provenance，供Explanation/G继续消费。
   - 新增`ProblemColdPathService`：先运行一次Domain extraction；blocked时Planner调用数为0；accepted后从artifact store重新加载Bundle再调用Solver。Solver retry只复用accepted Bundle，不重新调用OCR、豆包、canonicalizer、validator或domain projector。
   - 新增cold-path batch，记录提取与Planner两阶段usage/latency、scope-native prompt、answer/runtime/provenance gate。默认CI继续使用recorded F2/Bundle，不加载Paddle或调用付费模型。
   - 离线证据：五题默认recorded Bundle入口全部通过，当前全量Solver回归`1707 passed, 12 skipped`。真实Planner-only v1基线为`11/15`。真实图片统一`5x1`批次中五题提取均一次accepted，domain/projection diff、完整图片输入、scope-native prompt及configuration/unclassified gate全绿，Solver为`3/5`；五题在历史定向批次中均已有完整cold-path成功样本。剩余失败集中于F5-F要替换的PathTransformation、整图pre-runtime、call级冻结和完整plan retry。因此F5-E不再为旧协议追求统一`5/5`；过渡代码清理与离线退出审计已经完成。

6. **F5-F Scope-derived FunctionalPlan与教学归属（分阶段）**
   - F5-F按`F1协议 -> F2增量执行 -> F3局部retry -> F4 family宏 -> F5教学归属/清理`顺序实施。每步单独跑离线门禁和5×1，不把五个authority边界绑定成一次大切换。
   - **F5-F1 Scoped Plan v2 authority**
   - 新增严格`functional_plan/v2`：使用与Problem一致的递归scope骨架，scope内只放`shared_steps`和逐Goal的`steps`，不复制题面Entity/Fact。scope/Goal key必须来自PlanningContext且全集一致；模型不能创建或移动scope/Goal。step保留`step_id/capability_id/args`，不再输出运行时`execution_scope_id`，也不构造完整typed return binding。需要外部对象身份的return只输出按return role组织的最小target；代码结合capability contract、Goal和返回类型生成canonical binding。
   - scope-local裸answer key仅在owner scope、answer key和类型唯一时自动补全；跨scope、无候选或多候选稳定失败。该机械规范化不得读取call id、中文reason或模糊label。
   - answer ref反向传播得到每个call的Goal集合；SemanticRef按Goal allowlist交集验证；没有required Goal后代的call由现有liveness删除，保留后仍无Goal的call fail loud。
   - 具名题面对象的SemanticRef默认消费唯一、可见、类型兼容的最近前序状态，并在C3 sidecar中固化为精确producer/return；不同对象、跨sibling、forward reference和多producer歧义全部fail loud。显式CallResultRef只保留给匿名内部结果、非最近版本和必要消歧。
   - 服务端派生`FunctionalStepScopeAuthority`，至少记录`canonical_step_id`、`goal_unit_ids`、`plan_scope_id`、`semantic_owner_scope_id`、`execution_scope_id`和binding signature。Plan中的scope位置是LLM输出的讲解/思路组织，代码仍要验证它与Goal owner一致；真正execution placement不得由该位置覆盖。
   - **F5-F2 Incremental Goal run**
   - 新增`functional-goal-execution-checkpoint/v1`。候选建立后先保存每个step的结构、Goal、typed依赖和binding signature；每次preparation/compile/sandbox/result/closure尝试都记录prompt-safe resolved inputs、实际outputs、状态、typed diagnostic、closure signature和Problem provenance。pre-runtime verified与runtime verified是不同状态，二者都不等于Goal solved。
   - 增量执行器按topological ready set工作。step依赖全部runtime verified后才可prepare/compile；compile失败记录真实resolved inputs但没有伪造输出，method失败保存typed diagnostic，result/closure失败保存实际provisional result及残余自由元；未执行suffix记录直接`blocked_by`。失败step阻断其suffix，但同一失败Goal的所有成功step只作为下一轮证据，不做硬冻结。独立Goal继续执行；通过全部answer/runtime/closure/provenance gate的Goal整体冻结。
   - solved Goal的步骤和结果保存在solver-run checkpoint中，供其他Goal查看；只有显式`published_results`可被其他Goal绑定。全题仍采用原子Context commit，避免部分成功成为ghost state。
   - **F5-F3 Goal replacement retry**
   - 新增`planner-goal-retry-context/v1`和`functional-goal-repair/v1`。每次retry输入包含上一版完整canonical Plan，并按同一Problem scope递归组织所有Goal的执行状态，而不是输出平面的`repair_call_ids/validated_call_ids/locked_call_ids`。上一版Plan只出现一次，执行树以`step_id`关联，避免重复payload。solved Goal完整保留但`editable=false`；failed Goal完整提供逐step实际输入、输出、错误、blocked suffix与Goal issue并`editable=true`；blocked/pending Goal保留其归属和阻塞原因。
   - 模型对每个开放Goal返回完整`steps`替换，可以删除、重排、替换和新增该Goal的任意step，从而真正更换思路；失败Goal内没有call级frozen mutation限制。代码原子替换Goal plan、重建该Goal DAG和typed binding，再执行。若shared block失败，则所有consumer Goal组成同一repair group，模型通过`shared_scope_replacements`重写完整shared block；solved Goal及不相关shared block不可修改。
   - shared或solved结果发生authority漂移时，依赖Goal重新打开；共享根Entity本身不会扩大repair group。完整step结果仅供模型理解，跨Goal数据依赖仍必须来自`published_results`，禁止根据自然语言或显示值恢复runtime identity。
   - **F5-F4 Family path macros**
   - 将`PathTransformation`从LLM协议、capability catalog prompt和领域模型中删除。公开能力不是一个带family分支的万能`two_moving_points_path_minimum`，而是由每个family声明自己的高层path-minimum macro。首批至少区分正方形中点/中心降维、射线等长替换、加权路径和linked auxiliary路径；各macro拥有独立的输入contract、`use_when/do_not_use_when`、source primitive selector和降维invocation graph。只有两个family的题面前提、降维证明和输出语义完全一致时才允许共享同一个公开macro。
   - family-specific macro的Planner显式输入原则上只有题面`path_minimum_target`；`square`、`midpoint_definition`、`square_center`、等长关系、固定端点及其精确Point state等由source authority和声明式selector注入。确实依赖前序动态结果时仍使用typed result dependency，不把内部角色重新暴露成字符串参数。
   - 各family的降维阶段统一生成仅在macro invocation graph内存活的私有`ReducedPathWitness`。它记录等价后的两段路径、真实moving object、固定端点、轨迹依据、精确版本和证明关系，但不写入PlannerStateContext，不生成SemanticRef/CallResultRef，也不成为public return。共享straightening core只消费该私有contract，并继续复用反射候选、候选选择和两点距离method。
   - 公开输出限于`minimum_expression`以及该数学机制自然产生的`optimal_moving_point_expression`或最优构型结果。根据给定最小值反求参数、代入参数和从最优动点恢复最终题面答案点默认继续使用独立通用capability；不得为了减少call数量把整个小问收进不可复用的超大macro。
   - macro内部phase必须保留method invocation、source unit、Goal和scope provenance。Explanation可以把family-specific的“建立约束→路径等价变换”与共享的“反射/拉直→得到最小表达式”展开为多个学生步骤；后续参数求解和答案点恢复使用各自provenance。Planner和Problem wire都不出现`path_transformation`或`ReducedPathWitness`。
   - **F5-F5 Teaching scope与v1退役**
   - 新增`TeachingStepPlacement`，将compiled step确定映射到学生讲解scope。Plan已按Problem scope/Goal组织，但该位置仍需由Goal authority验证；单Goal step归入Goal owner scope，共享step若其输入对共同祖先可见则在最近共同祖先讲解一次，否则按Goal生成引用而不复制runtime计算。
   - `execution_scope_id`只回答状态和method在哪里执行，`teaching_scope_id`只回答步骤在哪个题干/小问下呈现，二者分别审计，禁止Explanation用runtime placement猜教学结构。
   - ExplanationSnapshot保存call、Goal、source unit和teaching scope provenance；G阶段直接消费该sidecar组织小问、动画和对话，不重新从扁平StepPlan或中文文案推断scope。
   - 先以F5-E的scope-native prompt + v1 response建立基线，再用相同模型/参数/样本切v2。验收后物理删除`functional_plan/v1` parser/schema、scope authored fixture和兼容路径，不形成长期双协议。
   - 增加静态门禁：Planner prompt/schema/catalog不得出现`PathTransformation`、`path_transformation`或`ReducedPathWitness`；production plan不得把内部macro phase当作外部SemanticRef/CallResultRef。每个启用路径最值机制的family必须通过自己的macro contract preflight；未知profile fail loud。共享straightening实现只保留一份，测试禁止family macro复制反射、候选选择或距离计算逻辑。系统尚未上线，不保留旧path transformation alias或兼容adapter。
   - 同步删除底层reconciler/replay中的`problem_binding_catalog=None`、全局`semantic_read_catalog()`fallback及v1的`replace_answer_ref_with_goal_target`/`bind_unique_condition_role`repair；裸`RuntimeOrchestrator.solve(ProblemIR)`改为私有debug实现，deterministic入口统一为`solve_problem_ir_debug()`。`planner-problem-view`、`functional_plan/v2`和retry schema按typed union收紧item字段，所有variant使用`additionalProperties: false`。
   - C0.5继续作为scope/version权威门禁，并新增三棵scope树对齐、`unique_prior_producer / explicit_call_result / ambiguous_producer / sibling_rejected`、scope-local answer canonicalization和Goal replacement维度；另增加“前缀成功、第k个step失败、suffix blocked”“独立sibling Goal继续并整体冻结”“shared producer失败重开consumer Goal组”“失败Goal完整替换不修改solved Goal”“provisional ghost write为0”。v2 adapter必须真正经过PlanningContext、F5-C sidecar和Goal checkpoint。
   - C5 symbolic closure继续保留；除macro内部closure、parameter identity、Goal/source provenance和“PathTransformation不泄漏”外，增加“method有实际输出但closure失败时把残余自由元写入Goal retry”“独立Goal closure冻结”“Goal replacement恢复solved Goal checkpoint”。原有unique/ambiguous/inconsistent/underdetermined数学门禁不得缩减。
   - 预期最终成功率提升可能小于Pass 1提升，因为F5-C/D当前已能拒绝scope错误；主要收益应体现在首轮成功率、retry次数、prompt/output token、scope错误归零、内部状态不再污染LLM协议，以及Explanation归属成为单一权威。

首批typed错误：

```text
planner.problem_bundle_invalid
planner.problem_projection_manifest_drift
planner.problem_planning_context_invalid
planner.problem_planning_projection_drift
planner.problem_planning_ref_ambiguous
planner.problem_scope_visibility_drift
planner.problem_revision_drift
planner.problem_source_binding_unresolved
planner.problem_source_binding_drift
planner.runtime_problem_provenance_missing
planner.runtime_problem_provenance_drift
planner.retry_problem_revision_drift
planner.retry_problem_source_binding_drift
functional.semantic_ref_not_visible_for_goal
functional.answer_ref_goal_mismatch
functional.call_goal_unresolved
```

### 8.4 测试与退出门禁

离线测试必须覆盖：

- VerifiedProblem、ProblemIR或manifest任一hash漂移均fail loud；
- ancestor可见、sibling不可见，跨sibling SemanticRef在编译前失败；
- 同一根Symbol在两个子问中的赋值形成不同StateVersion；
- 共享依赖的call仍由B2按LCA放置，不由LLM发明promotion；
- goal view顺序、hash和prompt确定重放；
- 五份authored FunctionalPlan在新视图下保持相同answer/runtime结果；
- retry携带上一版完整canonical Plan，并按Problem scope树保留全部Goal；每个已尝试step的实际输入、输出、状态和错误均可追溯，solved Goal只读，failed Goal可完整替换；
- `functional_plan/v2`的scope/Goal骨架与Problem/Retry逐项一致，step-to-Goal与execution scope可由同一plan确定重放；
- 每个学生可见Step恰有一个教学scope策略，shared step不会在多个小问中无依据重复；
- ContextBuilder继续消费未改schema的扁平ProblemIR；
- 所有verified write均可追溯到Context、revision/hash和source units；
- Planner与Solver阶段的OCR、豆包和domain projector调用数均为0。

实现期回归：

```bash
cd server
uv run pytest \
  tests/solver/test_problem_planning_context.py \
  tests/solver/test_problem_solver_bundle.py \
  tests/solver/test_functional_binding_context.py \
  tests/solver/test_functional_transaction_execution.py \
  tests/solver/test_strategy_planner_retry_state.py \
  tests/solver/test_cross_scope_version_generated_gate.py -q
uv run pytest tests/solver -q
git diff --check
```

五份recorded accepted Bundle的离线Solver门禁已经通过，F5-E的v1 Planner-only `5×3=11/15`与图片cold-path统一批次`3/5`固定为对照基线。图片批次五题提取均一次accepted，domain/projection、完整图片、scope-native prompt及configuration/unclassified gate无漂移；所有五题也均有历史定向cold-path成功证据。当前全量Solver回归为`1707 passed, 12 skipped`，F5-E已经`COMPLETE`，不再为即将删除的完整plan retry和call级冻结继续消耗模型成本。F5-F随后以相同模型、参数和五题先跑Planner-only `5×3`，再跑v2图片cold path `5×1`和`5×3`。F5最终退出条件：两组`5×3`均15/15在三轮内通过answer、protocol、runtime、binding、closure和provenance gate；Problem/Plan/Retry scope树零漂移，solved Goal不可变、failed Goal可完整替换，execution/teaching scope可确定重放，提取模型重复调用和失败事务ghost write均为0。
