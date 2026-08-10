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
| F5-E Solver cold path | `NEXT` |

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
problem-planning-context/v1
  family_id
  source
  shared_context[]
  goal_views[]
    goal / scope_path / semantic_reads
    visible_shared_scope_ids[]
    local_context[]
```

每个Goal视图只能看到当前scope及祖先scope。可见性采用正向allowlist，不额外持久化`excluded_sibling_scope_ids`；Entity和Fact直接保存在对应scope切片中，不重复生成`visible_entity_units`/`visible_fact_units`数组。sibling中的Entity状态和Fact不会进入该Goal的prompt切片或binding catalog；共享根Entity可以被多个Goal引用，但各子问的`symbol_value`、coordinate和constraint仍生成不同scope-local `StateVersion`。

`FunctionalPlan`继续使用`functional_plan/v1`和现有`SemanticRef`。F5-C只能通过`input_authorities_for_goal(goal_unit_id)`取得当前Goal的输入catalog，并通过`answer_authority_for_goal(goal_unit_id)`取得唯一return authority；禁止遍历全局`ref_authorities`后自行过滤。Planner response schema只暴露当前Goal视图允许的scope/ref。LLM不决定scope promotion：call的声明scope由Goal视图锚定，现有B2 placement根据typed dependencies和LCA计算实际`execution_scope_id`。

### 8.3 分步实现

1. **F5-A Bundle authority（COMPLETE）**
   - accepted Context loader校验完整ancestor chain、三个authority artifact、revision、semantic hash、family和dependency闭包。
   - projection manifest覆盖每个scope/entity/fact/goal source unit和全部runtime node；折入Entity的function/point Fact仍保留source provenance。
   - blocked、pending和任一artifact漂移不得进入Planner。历史accepted Context是有效不可变快照；只有显式expected authority token不匹配时才判stale。
   - 五题bundle可确定重放，F0–F5-A联合回归`318 passed`；加载阶段OCR、LLM、domain projector、Planner和完整Solver调用数均为0。

2. **F5-B Scope-native planning projection（COMPLETE）**
   - 从VerifiedProblem建立一个全题`ProblemPlanningContext`、共享祖先scope和逐Goal可见视图；一道题仍只对应一次未来Planner调用。
   - 每个GoalView严格包含owner scope及祖先；跨sibling source/runtime mapping、漏Goal、漏scope或漏runtime node均fail loud。
   - 每个非scope runtime node恰有一个稳定SemanticRef；answer ref仅对自己的Goal可见，folded Fact仍保留在source视图，combined Fact保留一对多provenance。
   - GoalView的`semantic_reads`必须与可见scope中`available_refs`的并集完全一致；F5-C只能调用按Goal过滤的authority API。
   - prompt payload不暴露source unit、runtime handle、artifact、Bundle token、MathObjectId或StateVersionId；shared scope只序列化一次。
   - prompt形状由checked-in `problem-planning-context.schema.json`与Python schema双源门禁锁定；authority payload不作为外部wire。
   - 五题GoalView数量为`6/4/3/3/3`；F5-A/B定向联合门禁`81 passed`，全量Solver回归`1587 passed, 12 skipped`。
   - 本阶段未修改`StrategyPayloadBuilder`或生产Planner输入；默认切换留到F5-E。

3. **F5-C FunctionalPlan binding（COMPLETE）**
   - `ProblemPlanningBindingCatalog`只通过F5-B按Goal authority API，将`SemanticRef -> runtime node -> source unit -> canonical handle -> typed identity`确定绑定；不调用全局semantic catalog，不使用alias、label、handle尾部或模糊匹配。
   - answer producer反向传播得到call服务的Goal集合。单Goal call使用该Goal allowlist；共享call只能读取各Goal allowlist交集。跨sibling read、answer串线、无Goal call和placement后可见性漂移均在compile前失败。
   - source Entity、Fact与state snapshot绑定`MathObjectId`、`ConditionId`及精确`StateVersionId`；source ref不允许隐式选择latest，动态结果只能通过`CallResultRef`传递。
   - Catalog只从未演进的typed slot派生ordinal-0 source snapshot；若PlannerStateContext中的对应slot已有write或latest不再是ordinal 0，重建Catalog直接报`planner.problem_source_binding_drift`，后续阶段必须复用原Catalog中的pin。
   - reconciliation挂载`FunctionalProblemBindingContext`，逐arg/return记录Goal、runtime node、source unit与C3 identity；direct preparation再次对sidecar、C3 ledger、B1 answer allocation及exact version做一致性审计。
   - semantic elaboration的per-call allowlist只含input authority；answer authority只允许出现在显式return binding，不能成为C3 implicit source。多source Goal target不再取首项，必须唯一映射或fail loud。
   - Catalog authority与reconciliation sidecar分别由`problem-planning-binding-catalog/v1`和`functional-problem-binding-context/v1`锁定，并与checked-in JSON Schema做双源门禁。
   - 五份scope-native recorded FunctionalPlan均通过validation、reconciliation、direct compile、authoritative symbolic closure与transaction；旧扁平fixture仍独立通过且生产代码没有alias fallback。
   - F5-C专项`26 passed`，F5-B/C与C3/transaction/C0.5联合门禁`115 passed`，全量Solver回归`1613 passed, 12 skipped`。
   - 保留B1 allocation、B2 placement、B3 finalization、C3 binding ledger和C4/C5 symbolic closure。F5-C当前仍由显式`problem_binding_catalog`接线启用；缺参时旧Planner路径仍存在，默认Planner prompt与强制切换到F5-E完成。

4. **F5-D Retry与provenance（COMPLETE）**
   - `ProblemCallSourceProvenance`只能从F5-C sidecar派生，记录planning context、problem revision/hash、canonical call、Goal集合、call binding signature和该call直接读取的Problem source units。`CallResultRef`与compiler selector不计入直接source read，跨call来源由typed dependency DAG恢复。
   - direct compile后、method执行前为全部versioned、value-only、companion与answer-alias write/result统一盖章；commit前审计missing、revision和per-return drift，失败整call回滚。`PlannerStateContext` hydrate保留实际write authority，checkpoint不得补造或覆盖缺失字段。
   - retry契约升级为`functional-retry-graph-checkpoint/v2`。顶层`problem_authority`固定PlanningContext与Problem revision，`problem_call_authorities`覆盖所有F5-C canonical calls；committed call、verified version和value-only result均携带同一call provenance。v1及其他旧checkpoint版本硬拒绝，不提供hydrate迁移；缺legacy binding signature只允许降为不锁call的`runtime_verified`证据。
   - locked call恢复时Goal、直接source units及完整input/return sidecar形成的call signature必须完全一致；即使wire微调后C3选源相同，也采用刻意的fail-loud。repair call可重编排，但不得越出原repair Goal集合。revision/hash漂移报`planner.retry_problem_revision_drift`，Goal/source/signature漂移报`planner.retry_problem_source_binding_drift`，不从SemanticRef、handle或错误文本恢复identity。
   - `ProblemPlanningRetryProjector`按repair call的Goal并集从可信PlanningContext重新生成视图，只展示这些Goal、祖先scope和去重shared context。source unit仅进入内部authority payload和projection signature，不进入prompt；revision/hash、runtime node、StateVersion和Bundle token同样隐藏。prompt审计采用结构化字段遍历，题面`source_text`碰巧等于内部ID不会误报；稳定call结果仍由既有typed issue dependency选择器按需提供。
   - answer-check撤销commit后，runtime result及其Problem provenance保留为`runtime_verified` provisional evidence，但committed call为空。五题transaction、checkpoint与retry view可确定重放，F5-D专项`31 passed`，指定联合门禁`146 passed`，全量Solver回归`1644 passed, 12 skipped`。
   - F5-D不重新运行OCR、豆包、domain canonicalizer/projector、Planner或完整Solver，也不切回authored fixture。scope-native接线仍为内部显式参数，生产默认切换留到F5-E。

5. **F5-E Production cold path**
   - 默认`solve_problem`入口直接消费accepted bundle。
   - Planner使用ProblemPlanningContext；ContextBuilder与transactional runtime使用已保存的Solver ProblemIR。
   - 强制传入F5-C BindingCatalog和F5-D ProblemPlanningContext；不再接受`problem_authority=null`，也不迁移v1 retry checkpoint。
   - 删除Planner仅消费扁平ProblemIR并自行恢复scope的旧入口；保留ProblemIR作为runtime contract。

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
- retry只包含相关Goal repair cone和稳定call；
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

先用五份recorded accepted bundle跑离线Solver门禁，再运行图片到Solver冷路径`5x1`和`5x3`。F5退出条件：15/15在三轮内通过answer、protocol、runtime、binding、closure和provenance gate；scope/source/revision drift、提取模型重复调用和失败事务幽灵write均为0。
