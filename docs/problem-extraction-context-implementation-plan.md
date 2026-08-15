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
| F5-F1 Scoped FunctionalPlan v2 authority | `COMPLETE` |
| F5-F2 Incremental Goal execution | `COMPLETE` |
| F5-F3 Goal replacement retry | `IMPLEMENTED / LIVE 5x1 PENDING` |

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
planner-problem-view/v2
  family_id
  source
  root_scope
    id / text
    entities[]  # exact ref内嵌在Entity
    facts[]     # exact ref内嵌在Fact
    goals[]     # goal_ref / kind / target / answer_type
    children[]
```

scope嵌套本身定义词法可见性：Goal只能读取自身scope及祖先scope。Prompt不再输出`available_refs`、`semantic_reads`、`identity_only_reads`、`scope_path`或shared/local重复切片；每个可用SemanticRef只在对应Entity或Fact上出现一次，Goal直接位于owner scope。Prompt Goal与FunctionalPlan统一使用`goal_ref`，模型必须逐字复制；内部`answer_ref` authority保持不变。空的`entities/facts/goals/children`在prompt中省略。内部authority仍完整保留逐Goal allowlist、source unit、runtime node和typed identity，sibling隔离继续由代码验证。

Scope与Goal是两个正交概念。Scope是题面语义、词法可见性和教学分段的容器，拥有本地文字、Entity、Fact及child scope；Goal是挂在某个owner scope上的原子求值要求，只声明要得到什么答案及其类型，不拥有Entity、Fact或child scope。一个scope可以没有Goal，例如全题根scope或只提供公共条件的`(II)`；可以有一个Goal；也可以有多个Goal，例如同一小问“求P、A两点坐标”对应两个独立point-coordinate Goal。因此，“Goal是需要求解的scope”可以作为单Goal题目的直观说法，但不能作为wire或authority模型：更准确的表述是“带求解任务的scope拥有一个或多个Goal”。不能为了让每个Goal看起来像scope而生成没有题面语义的人工child scope。

F5-E切换默认入口时暂时继续使用`functional_plan/v1`和现有`SemanticRef`。F5-C只能通过`input_authorities_for_goal(goal_unit_id)`取得当前Goal的输入catalog，并通过`answer_authority_for_goal(goal_unit_id)`取得唯一return authority；禁止遍历全局`ref_authorities`后自行过滤。Planner response schema只暴露当前Goal视图允许的scope/ref。现有B2 placement根据typed dependencies和LCA计算实际`execution_scope_id`。

F5-F的LLM authoring wire使用`functional-plan-content/v2`，内部执行权威继续使用`functional_plan/v2`。Problem、Plan和Retry共享同一棵scope/Goal骨架，但骨架不再由模型复制：代码从PlanningContext派生`FunctionalPlanAuthorityFrame`，固定scope树、Goal owner、答案target/type及精确map key；模型为合法scope和Goal填写步骤列表，并为每个Goal输出局部`answer_from`表达答案producer意图。assembler验证全集后生成最多四层的canonical v2树，再按scope可见性、capability typed return、目标对象身份和StepResult DAG验证该指针；指针错误但合法候选唯一时由代码规范化，多个候选时由合法指针消歧，否则fail loud。普通scope步骤由该scope拥有，可服务一个或多个后代Goal；Goal步骤只服务对应原子Goal。公共性只由步骤所在scope表达，不使用`shared_steps`。

F5-F同时把“整份计划先全部编译，再开始执行”改为增量provisional执行。JSON必须完整可解析；服务端先验证scope/Goal骨架、step identity、capability、typed dependency shell、DAG无环和Goal/answer authority。随后对ready step逐个运行preparation、direct compile、sandbox method、result type/provenance和symbolic closure校验。内部执行记录保持step粒度，但冻结边界提升为`GoalExecutionCheckpoint`和`ScopeExecutionCheckpoint`：Goal只有在answer、runtime、closure和provenance全部通过后才成为`solved`；scope-level步骤块只有自身通过全部runtime/provenance门禁且consumer Goal集合稳定时才可独立冻结。失败Goal中此前成功的step只作为诊断证据，不成为模型不可修改的冻结单元。与失败Goal无依赖的sibling Goal继续执行。所有required Goal通过前不产生authoritative Context write，solved Goal结果通过当前solver run的checkpoint发布，而不是提前写入全局Context。

LLM本身无会话状态，F5-F retry显式发送三个相互对齐的输入：当前`planner-problem-view/v2`、去除内部答案指针的上一版完整Plan和`planner-goal-retry-context/v2`执行树。上一版Plan不按repair cone裁剪；执行树只引用`step_id`并提供逐步实际输入、输出、状态、typed error和blocked关系。`solved` Goal只读，`failed` Goal可完整重写steps；只有`published_results`拥有跨Goal绑定权威。

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

上述字段来自真实preparation/compiler/runtime/closure记录，不能由静态计划预测或错误文案反推；不得暴露MathObjectId、StateVersionId、source unit、runtime path或authority token。首轮使用authority-bound `functional-plan-content/v2` response schema，并要求每个Goal输出`answer_from`；建立可信canonical Plan后，retry切换到`functional-goal-repair/v4`，失败Goal完整替换`steps + answer_from`。repair以授权Goal和scope ref为精确map key；模型选择答案producer，代码验证并仅在唯一合法active return时兜底规范化。

三个阶段使用同一scope identity，但只有Problem View携带递归骨架：

```text
planner-problem-view/v2
  root_scope
    scope_ref / source semantics / goals / children

functional-plan-content/v2   # LLM Pass 1输出步骤与答案producer意图
  scope_steps{scope_ref: steps[]}
  goal_plans{goal_ref: {steps?, answer_from}}

functional_plan/v2           # 代码组装的canonical内部结构
  root_scope                  # 来自authority frame，不由模型复制

planner-goal-retry-context/v2
functional-goal-repair/v4    # Retry输出Goal steps+answer与scope步骤替换
  base_plan_id
  root_scope
    scope_ref
    scope_step_executions?[]
      step_id / status / resolved_inputs / actual_outputs / typed_issue / blocked_by
    goals?[]
      goal_ref
      status = solved | failed | blocked | pending
      editable
      step_executions[]
      published_results[]
      issues[]
    children?[]
```

完整`previous_plan`在retry user prompt中独立出现且只出现一次；retry context只携带执行增量，禁止在每个step重复`authored_step`。Pass 1的空`scope_steps` entry与Goal空`steps`均省略；canonical Plan和retry tree中的空集合同样省略。scope与Goal全集由代码从authority frame对齐，不能依赖数组位置、label或LLM自由命名。一个scope拥有多少Goal与它拥有多少scope step互不绑定；scope-level步骤实际服务的Goal集合由typed dependency和answer producer反向推导。

为命中DeepSeek前缀缓存，retry prompt固定按`Problem Planning Context → Strategy Principles → Functional Capability Catalog → Output JSON Schema → Previous Canonical Plan → Goal Execution And Repair Authority`排列。Pass 1与retry使用独立模板和独立schema；动态schema、Plan和retry delta位于user message后部。解析层只允许移除一个可证明冗余的尾部`}`或`]`并记录normalization；多个尾符、第二个JSON、解释文字和未闭合JSON不得修复。

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

6. **F5-F Scope-derived FunctionalPlan与教学归属（F5-F1/F2 COMPLETE，分阶段）**
   - F5-F按`F1协议 -> F2增量执行 -> F3局部retry -> F4 family宏 -> F5教学归属/清理`顺序实施。每步单独跑离线门禁和5×1，不把五个authority边界绑定成一次大切换。
   - **F5-F1 Scoped Plan v2 authority（COMPLETE）**
   - 内部canonical plan保持严格`functional_plan/v2`与固定四层scope树；LLM Pass 1使用`functional-plan-content/v2`及独立content模板。`FunctionalPlanAuthorityFrame`固定scope/Goal骨架、答案target/type和exact-key schema，模型返回`scope_steps`与`goal_plans`两个map，不复制scope节点、children或Goal identity，但每个Goal必须携带`answer_from`意图。assembler逐key验证后生成canonical树，再由typed answer resolver验证该指针：合法候选可用于消歧，错误指针只在唯一候选时机械规范化；缺Goal、未知scope/Goal、零答案候选或未消歧的多个候选均fail loud。
   - scope-local裸answer key仅在owner scope、answer key和类型唯一时自动补全；跨scope、无候选或多候选稳定失败。该机械规范化不得读取call id、中文reason或模糊label。
   - answer ref反向传播得到每个call的Goal集合；SemanticRef按Goal allowlist交集验证；没有required Goal后代的call由现有liveness删除，保留后仍无Goal的call fail loud。
   - v2参数只允许两类来源：字符串`SourceRef`必须逐字复制当前scope或祖先scope可见的Problem View ref；Fact固定读取F5-C验证的source snapshot，稳定MathObject则读取该step之前最近可见的同对象状态。代码将可证明唯一的latest写入机械lower为exact`{step_id, return}`；没有写入时保留初始snapshot。匿名结果、非latest状态和producer消歧由模型显式使用`{step_id, return}`，且不得为匿名step结果自造字符串ref。
   - 服务端派生`FunctionalStepScopeAuthority`，至少记录`canonical_step_id`、`goal_unit_ids`、`plan_scope_id`、`semantic_owner_scope_id`、`execution_scope_id`和binding signature。Plan中的scope位置是LLM输出的讲解/思路组织，代码仍要验证它与Goal owner一致；真正execution placement不得由该位置覆盖。
   - v2 authority确定性lower到现有内部`FunctionalPlan/FunctionalCall`，继续复用B1/B2/B3/C3、direct compiler和transaction。五份fixture均通过完整离线replay；F5-F1/F5-C/transaction及policy专项最新联合回归`372 passed`，全量Solver回归`1770 passed, 12 skipped`。首轮递归schema真实批次schema-valid为`1/5`；四层展开schema的disabled-thinking批次为`2/5`，low-thinking单轮批次进一步达到`5/5 schema-valid`。identity/configuration/unclassified drift均为0，F5-F1仍为`LIVE 5x1 PENDING`，生产DeepSeek默认保持v1。
   - **F5-F1.1 和平二模泛化加固（COMPLETE）**：Function facade公开名固定为`quadratic_x_axis_intercept_point.parabola`和`square_adjacent_vertex_from_side.adjacent_vertex`，runtime Method slot/output仍为`quadratic`和`point`。Catalog启动时审计required runtime input、公开return及同类型多return role覆盖；v2参数只允许显式alias或唯一required类型一对一归一，optional与多候选不补齐，归一记录进入authority debug和semantic hash。中间题面对象只能经`output_targets`绑定，Goal答案只能经`answer_from`绑定；代码只有在capability声明source-fact selector且当前scope唯一解析到F5-C可见、类型兼容对象时才记录`infer_unique_output_target`，零候选或多候选均要求显式target。共享计算必须由模型放在consumer Goal的共同祖先`scope.steps`；lowering不再自动移动step或合并兄弟调用，B2只能在保持canonical step identity的前提下验证最终execution scope。authority analyzer稳定聚合独立参数、输出、scope和DAG问题。
   - **F5-F1.2 Goal identity同名化（COMPLETE）**：Prompt-facing Problem View升级为`planner-problem-view/v2`并把Goal字段从`answer_ref`改为`goal_ref`，与`functional_plan/v2`同名；内部GoalView/F5-C仍保留typed answer authority。Prompt和两份schema都明确禁止使用scope id、target或自造名称替代Goal ID。同scope恰有一个expected Goal、Plan也恰有一个未知Goal ID且scope树无漂移时，authority可执行`canonicalize_unique_goal_ref`；多Goal、数量不等、重复Goal及已知Goal跨scope移动继续fail loud。raw response不变，debug分别保存原始结构、归一记录、归一后Plan和最终结构报告。真实low-thinking `5x1`达到`5/5 schema-valid`、`5/5 scope/Goal tree`且五题Goal归一记录均为空，证明同名wire已让模型原生复制正确Goal；剩余`1/5`authority失败来自河西把answer ref当input ref，非Goal tree漂移。
   - **F5-F1.3 Goal target identity与MathObject安全归一（COMPLETE）**：Prompt Goal将答案authority与题面对象identity显式分成`goal_ref`和`target_ref`。`point_coordinate/quadratic_equation/parameter_value`必须输出`target_ref`，`minimum_value`继续输出结构化`expression`；旧`target`字段由strict Problem View schema直接拒绝。Capability参数新增`semantic_ref_role=value|object_identity`，`PointRef`自动是对象identity，普通`Point`必须由Function/Macro contract显式声明；catalog说明对象identity参数只能读取Goal的`target_ref`或可见Entity ref，不能读取`goal_ref`。当且仅当Goal私有step把自己的`goal_ref`用于单值对象identity参数，且F5-C证明answer authority与唯一可见、类型兼容input ref拥有完全相同`MathObjectId`时，authority记录`canonicalize_goal_target_input_ref`并改写为`target_ref`。computed value、跨Goal、scope step、零/多候选及仅字符串/类型相似均不修；answer ref继续作为输入时报`functional.answer_ref_used_as_input`。raw response保持不变，canonical Plan/hash使用归一结果，debug展示原始Plan、MathObject归一、canonical Plan和剩余issues。
   - F1.3后的首个真实单轮批次`f5f1-deepseek-v2-goal-target-identity-low-5x1-20260813`达到`5/5 schema-valid`、`5/5 scope/Goal tree`和`4/5 Plan authority`。西青唯一authority失败来自pure root step写入child-local `D`；修复既有LCA placement后，同一批次五份原始响应离线重放为`5/5 Plan authority`，且`find_D`被确定性记录为`plan_scope=problem / semantic_owner_scope=ii`。后续独立批次`f5f1-deepseek-v2-goal-target-scope-placement-low-5x1-20260813`仍为`5/5 schema-valid`和`5/5 tree`，但只有`1/5 Plan authority`：三题输出catalog未声明的可选`return_expectations`，和平二模没有显式区分同一`G`的两个前序producer。这些是F1.3以外的v2 authoring问题；两个批次configuration/unclassified/identity leak均为0，MathObject unsafe normalization为0，因此F1.3代码完成但live总门禁继续pending。
   - **F5-F1.4 Return expectation policy与安全归一（COMPLETE）**：每个Prompt-facing return确定性声明`return_expectation_policy=selectable|omit`；只有contract提供非空`possible_forms`时才是`selectable`并允许模型逐字选择，fixed-form return为`omit`且不携带`possible_forms`。v2 authority按Goal、参数名和MathObject ref归一后处理expectation：合法selectable form保留，非法form和未知return role继续fail loud；模型为omit return填写的多余form则记录`drop_fixed_form_return_expectation`并从canonical Plan删除。raw response保持不变，runtime form仍由自由符号、provenance和C5验证；该机械删除不进入semantic hash，因此与模型原生省略得到相同语义身份。Debug展示本Plan实际使用的return policy、原始/保留expectation及归一记录。
   - F1.4真实单轮批次`f5f1-deepseek-v2-return-expectation-policy-low-5x1-20260813`达到`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 Plan authority`，configuration/unclassified/identity leak均为0。五题模型均原生遵守policy，expectation删除数和相关authority issue均为0；唯一authority失败是和平一模引用不存在的`path_minimum_target/point_on_ray/point_on_segment` SemanticRef，与return expectation无关。河西完成transaction；其余authority已通过样本的后续reconciliation/transaction诊断继续属于F5-F2/F3，不作为F1.4门禁。F1.4完成，但F5-F1总live门禁仍因`4/5 Plan authority`保持pending。
   - `answer_from`优先归一仅在F5-C证明同return的`output_targets`与Goal answer是同一MathObject时删除冗余target并记录`drop_redundant_answer_output_target`，不同对象继续失败。真实批次`f5f1-deepseek-v2-f1-1-generalized-low-5x1-20260812`为`5/5 schema-valid`、`3/5 scope/Goal tree`、`3/5 authority`和`1/5 transaction`；和平二模两个参数化`E`身份已闭合并通过F5-F1 authority。selector Prompt术语最终统一为`axis_membership`后的批次`f5f1-deepseek-v2-f1-1-final-low-5x1-20260812`有四题落盘，其中西青全链通过，河西/和平一模漏Goal，南开空`goals`被schema拒绝；和平二模provider请求超过14分钟且未生成sample artifact，批次被显式终止、未静默重跑。当前专项`45 passed`、联合`119 passed`、全量Solver`1755 passed, 12 skipped`，live状态仍为`PENDING`。
   - **F5-F1.5 Scope-native step identity（IMPLEMENTED）**：`step_id`就是唯一`canonical_call_id`，v2 reconciliation出现任意call alias即报`functional.scoped_step_identity_drift`。同一scope或兄弟scope中即使capability和参数相同也不自动merge；真正共享的计算必须只 authored 一次并位于Goal的共同祖先scope。`canonicalize_unique_fact_ref`只在模型复制了参数名/Fact kind、当前Goal恰有一个kind/runtime/scope/cardinality均匹配且F5-C证明为problem source的Fact ref时机械改写；已存在但Fact kind错误、零候选、多候选、Entity和动态结果一律不修。raw/canonical Plan保留无效pure branch，effective execution plan只剪除不产answer/Condition/副作用且没有Goal、StepResult或source-state consumer的dead leaf closure。
   - **F5-F1.6 Scope-local SourceRef（COMPLETE）**：Prompt中的Entity/Fact ref改为scope-local裸名称，Goal ref仍保持全题唯一。内部使用`ScopedSourceRefKey(owner_scope_id, local_ref, kind)`，从当前scope沿祖先链解析；兄弟scope可拥有同名ref且分别绑定不同MathObject/StateVersion，父子链同名遮蔽稳定拒绝。同scope基础名冲突按semantic payload hash生成稳定本地后缀，不添加scope前缀。BindingCatalog authority payload改为有序复合键记录，Goal allowlist交集按完整复合键计算；v2 authority的args、output target、Goal target和Fact归一均禁止直接按全局字符串索引。Prompt明确只复制当前scope视图中的裸ref，不能自行添加`scope_ref.`前缀；旧前缀ref不提供alias或fallback。
   - **F5-F2 Incremental Goal run（COMPLETE）**
   - 新增`functional-goal-execution-checkpoint/v1`。候选建立后先保存每个step的结构、Goal、typed依赖和binding signature；每次preparation/compile/sandbox/result/closure尝试都记录prompt-safe resolved inputs、实际outputs、状态、typed diagnostic、closure signature和Problem provenance。pre-runtime verified与runtime verified是不同状态，二者都不等于Goal solved。
   - 增量执行器按topological ready set工作。step依赖全部runtime verified后才可prepare/compile；compile失败记录真实resolved inputs但没有伪造输出，method失败保存typed diagnostic，result/closure失败保存实际provisional result及残余自由元；未执行suffix记录直接`blocked_by`。失败step阻断其suffix，但同一失败Goal的所有成功step只作为下一轮证据，不做硬冻结。独立Goal继续执行；通过全部answer/runtime/closure/provenance gate的Goal整体冻结。
   - solved Goal的步骤和结果保存在solver-run checkpoint中，供其他Goal查看；只有显式`published_results`可被其他Goal绑定。全题仍采用原子Context commit，避免部分成功成为ghost state。
   - 增量服务只要求全局JSON/schema、Problem revision和scope/Goal骨架成立；随后把单step authority错误隔离为`authority_invalid`，沿显式typed DAG把suffix标成`blocked_by_dependency`，并继续执行其余topological-ready前缀和独立Goal。成功结果只进入attempt-local provisional state，不创建accepted extraction Context或authoritative跨run write。
   - `functional-goal-execution-checkpoint/v1`使用与Problem/Plan相同的四层scope树，逐step保存authored step、prompt-safe resolved inputs、actual outputs、typed issue和blocked roots；内部authority另存revision、planning context、binding/step signature、Goal/source units与provisional state signature。Prompt payload结构化移除source unit、runtime handle、MathObject/StateVersion和Bundle token。Smoke新增authority-valid/invalid、dead-pruned、provisional-executed、blocked、transaction-attempted/ok和blocked-stage独立指标，不再把“未进入事务”算成transaction失败。
   - **F5-F2.1 固定点增量执行（COMPLETE）**：v2所有step在preallocation、elaboration与placement阶段均保持pinned，`step_id == canonical_call_id`且alias必须为空。Replay拆为`reconcile_functional_plan()`与`execute_reconciled_functional_plan()`；v2必须先完成typed reconciliation和`finalize_reconciliation()`，finalization失败不得执行Method或写状态。增量服务在最多`step_count+1`轮内反复隔离可定位的binding错误，重算显式StepResult依赖及由`output_targets -> MathObjectId`认证出的对象状态依赖，再reconcile clean subset；每轮必须新增invalid step或新的dependency block，否则生成no-progress root issue。稳定对象的字符串SourceRef会绑定latest可见写入；仅在latest不唯一、历史读取或身份不可证明时保留`functional.dynamic_source_ref_requires_step_result`。checkpoint保存完整canonical Plan DAG的Goal closure，部分可执行authority只决定binding signature；共享scope失败时consumer Goal为blocked，repair只重写scope块。JSON/schema失败因无法建立可信scope树不生成checkpoint；一旦Plan可解析，authoring、reconciliation、placement和runtime失败都生成带stage、root issues及`all_required_goals_verified`的scope-shaped checkpoint。Bundle/revision等非retryable authority漂移仍直接fail loud。
   - **F5-F2.2 Step三层Scope authority（COMPLETE）**：`FunctionalStepScopeAuthority`分别保存`plan_scope_id`、`semantic_owner_scope_id`和`execution_scope_id`。前两者在lower阶段确定并在finalization中冻结；B2只填写execution scope。final binding signature显式包含三层scope与consumer Goal，重复finalize和payload round-trip零漂移。后续教学placement必须消费plan/semantic scope，禁止由execution scope反推讲解归属。
   - 最新离线基线为F5-F1/F2/PlanningContext/Binding/transaction联合`190 passed`、全量Solver`1793 passed, 12 skipped`；五份v2 fixture的step/canonical call alias均为0，和平一模坏Fact ref用例能执行9个独立有效step、隔离1个authority-invalid step并阻断其1个显式suffix。F5-F3已消费该checkpoint，历史数字仅保留为F2基线。
   - 真实DeepSeek low-thinking单轮批次`f5f1-step-identity-incremental-low-5x1-20260813`严格保持每题一个semantic attempt且不重跑：provider response、JSON schema和scope/Goal tree均为`5/5`，Plan authority为`4/5`，prompt identity leak、configuration error、unclassified error、unsafe normalization和call alias均为0。因此F5-F1继续保持`IMPLEMENTED / LIVE 5x1 PENDING`，不能标记`COMPLETE`。唯一F1失败为河西：Problem View在同一个`i` scope中输出`i.symbol_value_a`，却输出无scope前缀的`symbol_value_b/symbol_value_c`；模型把三者规则化为`i.symbol_value_a/b/c`，后两个因此触发`functional.semantic_ref_unresolved`。这是Prompt-facing ref命名不一致诱发的模型身份错误，下一轮应只做可证明的owner-prefix规范化或统一Prompt ref命名，再以新的独立`5x1`验收，不能把本批次离线改写为通过。
   - 同一批次的F5-F2 live诊断为：authority-valid `50`、authority-invalid `1`、blocked-by-dependency `1`、provisional runtime-verified `23`、dead-pruned `0`，transaction attempted/ok均为`2/2`。和平一模与西青分别`13/13`、`10/10` step及全部Goal通过；河西正确隔离`i_build_parabola`并阻断`i_vertex`，但另一个`iii_minimum_expression`仍用字符串`M`读取`iii_compute_M`产生的动态状态，reconciliation级`planner.problem_source_binding_drift`使其余9个ready step没有继续执行；南开的`apply_m_to_N_ii1`同样用字符串`N`读取`construct_N_ii`的动态结果，18个ready step均停在reconciliation；和平二模虽通过F1 authority，却在finalize时因`compute_A_ii`缺canonical placement抛出`functional.step_scope_authority_drift`，未生成checkpoint。失败样本均未进入authoritative transaction，未观察到ghost write；F5-F2因此继续保持`IMPLEMENTED / LIVE DIAGNOSTIC PENDING`。
   - F1.6/F2.1修复后的真实DeepSeek批次`f5f1-scope-local-return-types-fixed-point-low-5x1-20260813`每题只调用一次模型：provider response、schema和scope/Goal tree均为`5/5`，scope前缀、call alias、identity leak、configuration/unclassified error和unsafe normalization均为0。执行服务曾把F2 reconciliation/runtime issue并入F1 report，落盘摘要因此误记`3/5 authority`；修正分层后对完全相同的五份raw response确定性重放得到`5/5 authoring authority`，原始Plan与错误均未改写，F5-F1据此标记`COMPLETE`。
   - 同批F5-F2数据为authority-valid `63`、authority-invalid `3`、blocked-by-dependency `7`、provisional executed `60`、dead-pruned `3`、transaction attempted `5/5`、transaction clean `3/5`，且五题全部生成checkpoint。和平二模、西青完成全部Goal；和平一模和河西将动态SourceRef精确隔离到step并继续独立分支；南开完成`5/6` Goal后保留runtime失败。全题未完成时仍无authoritative partial write，下一阶段F5-F3直接消费checkpoint。
   - **F5-F3 Goal replacement retry（IMPLEMENTED / LIVE 5x1 PENDING）**
   - `planner-goal-retry-context/v2`与`functional-goal-repair/v4`使用独立retry prompt。每次retry输入包含保留答案指针的完整上一版Plan，并按Problem scope递归组织所有Goal执行状态。solved Goal保留但`editable=false`；failed Goal提供逐step实际输入、输出、错误和blocked suffix。模型只输出authority-bound `goal_replacements{goal_ref: {steps, answer_from}}`与`scope_step_replacements{scope_ref: {steps}}`，不重复Goal/scope ref。
   - 模型对每个开放Goal返回完整`steps`替换，可以删除、重排、替换和新增该Goal的任意step，从而真正更换思路；失败Goal内没有call级frozen mutation限制。代码原子替换Goal plan、重建该Goal DAG和typed binding，再执行。若scope-level步骤块失败，则所有consumer Goal组成同一repair group，模型通过`scope_step_replacements`重写该scope的完整步骤块；solved Goal及不相关scope步骤不可修改。
   - shared或solved结果发生authority漂移时，依赖Goal重新打开；共享根Entity本身不会扩大repair group。完整step结果仅供模型理解，跨Goal数据依赖仍必须来自`published_results`，禁止根据自然语言或显示值恢复runtime identity。
   - Pass 1和retry使用独立system/user模板、独立response schema及独立renderer；retry不携带Pass 1 few-shot，也不包含完整Plan生成指令。每个sample最多三次semantic attempt，Pass 1关闭thinking，Goal repair使用low thinking；timeout/429/5xx transport retry不消耗semantic budget。
   - `PublishedGoalResultRef`不会降级为普通跨Goal StepResultRef：repair service只允许引用solved Goal的精确`answer_from`，内部以typed publication edge保留authority；执行DAG仍保留producer依赖，但Goal consumer传播跳过该边，因此failed Goal不会污染solved Goal closure。普通v2/checkpoint wire继续使用标准StepResultRef，retry prompt和Plan authority hash则保留`published_goal_ref`。中间return、failed/blocked Goal及伪造publication均fail loud。
   - retry从初始PlannerStateContext重建运行环境，仅恢复solved Goal和冻结scope块的typed result/version/checkpoint；failed Goal上一轮成功前缀只作为诊断，全部provisional write丢弃。repair group内Goal provenance允许随新DAG确定性增减，solved Goal、source binding、revision及typed identity仍不可漂移。
   - no-progress只在相邻两轮的canonical Plan hash和typed issue signature同时不变时触发；Plan未变但执行诊断已前进时仍允许下一轮修复。compiler注入且不对Planner公开的对象身份统一显示为`same_compiler_selected_object`，避免catalog用`same_object_as:<hidden_arg>`诱导模型伪造参数。`quadratic_from_constraints`进一步明确只提交公开的新增约束，`quadratic/parabola/x/all_coefficients`由binder从当前scope权威注入。
   - 最新离线门禁为F5-F3专项`57 passed`、F5-C/D/transaction联合`117 passed`、capability与既有Planner契约`377 passed`、全量Solver`1844 passed, 12 skipped`，`git diff --check`通过。真实DeepSeek批次`f5f3-goal-replacement-5x1-20260813-final`为`2/5`：河西2轮通过并恢复7个solved call，西青3轮通过；总计7次Goal repair和`451293` tokens。configuration/unclassified error、repair authority drift、solved Goal实际重执行和failed transaction ghost write均为0。
   - 批次后修复了三项泛化缺陷：solved Goal语义比较不再把可选`intent`文案视为依赖漂移；smoke终态不再回报早期已修复的schema错误；函数身份由compiler注入时catalog不再泄露隐藏arg。南开两份历史raw response无模型重放后已无`functional.goal_repair_boundary_violation`且恢复1个solved checkpoint，但因没有第三份历史响应仍为blocked，不能改写为live通过。和平一模尚需验证角条件和函数状态能力；和平二模最终为`PathTransformation`对象身份错配，明确转入F5-F4。F5-F3继续保持`IMPLEMENTED / LIVE 5x1 PENDING`。
   - Pass 1不再要求模型输出scope/Goal空数组或递归骨架。动态content schema锁定精确scope/Goal key，assembler省略空scope步骤与Goal空steps；可证明为pure、且输入依赖和`output_targets`在consumer Goal最近公共祖先仍可见的跨Goal producer，仍由authority canonicalizer确定性提升到该scope，child-local authority无法证明时继续fail loud。安全JSON normalizer只处理一个多余尾部delimiter并留下审计记录；其余JSON/schema失败把全部typed issue和可解析的规范化content候选带入下一轮Pass 1 prompt，避免无反馈原样重试。Debug每轮分别保存raw response、content、content validation、normalizations及assembled canonical Plan。
   - 本次breaking wire切换的离线门禁为：content/schema/assembler/retry/replay/smoke `89 passed`，F5-C/D、scope authority、transaction与跨scope版本联合`258 passed`，全量Solver`1867 passed, 12 skipped`，`git diff --check`通过。旧Pass 1树形模板、旧repair wire与旧invalid-plan字段已从生产包和当前文档删除。真实DeepSeek批次`f5f3-content-authority-5x1-20260814`为`5/5 schema-valid`、`5/5 scope/Goal tree`、`4/5 plan authority`和`2/5 completion`；河西、西青均在第3轮通过，总计`361093 tokens`。configuration/unclassified error、repair authority drift与ghost write均为0；南开仍有2次solved Goal重执行。阶段状态继续为`IMPLEMENTED / LIVE 5x1 PENDING`。
   - **F5-F3.1 MathObject latest-state与完整Goal DAG（COMPLETE）**：稳定题面Entity可在Plan中始终使用同一个SourceRef。代码按canonical step顺序选择当前scope/Goal最近可见、同MathObject且类型兼容的写入，内部降为exact StepResultRef；首次读取仍使用F5-C source snapshot。匿名return、指定历史状态及producer消歧继续显式引用。checkpoint的step binding只覆盖本轮可执行subset，Goal closure则覆盖完整canonical Plan，并叠加reconciliation提供的condition、materialized-state和其他typed hidden dependency；恢复solved Goal时依赖闭包不再丢失。共享scope失败只让scope块editable，其consumer Goal均为blocked；retry仍展示这些Goal的旧Plan、逐step结果和错误，但不要求模型重复改写每个Goal。联合F5-C/D、transaction与跨scope回归`241 passed`。
   - **F5-F3.2 Runtime-result equivalence与Goal答案重绑定（IMPLEMENTED）**：静态capability、typed inputs、effect key、MathObject/StateVersion identity只生成runtime-equivalence candidate，不再生成call alias或删除step。每个候选在独立probe runtime path执行，transaction层比较双向runtime type、MathObject identity、自由Symbol MathObjectId集合和实际符号结果；全部相等才生成`FunctionalRuntimeEquivalentCallAlias`，随后从初始Context clean replay并省略重复write。候选同时是Goal答案producer时，只保留绑定canonical StateVersion的answer-alias provenance，不提交第二份对象状态；answer gate仍按精确版本、MathObject和Goal authority验真。任一项不等即产生`planner.runtime_state_equivalence_conflict`、回滚整个失败transaction并保留原step，禁止以字符串、输入JSON、step名称或wire顺序代替运行结果比较。显式StepResult依赖继续指向authored candidate；隐式latest状态依赖按exact StateVersion producer排序，但在runtime证明前不授予删除authority。
   - **F5-F3.3 Scope-local StateVersion authoring（IMPLEMENTED）**：Problem中的同一抛物线Entity在各小问共享MathObject identity，但兄弟scope的局部系数、点、方程和参数条件必须生成各自的StateVersion。只有producer的全部输入条件在共同祖先可见、且后代确实消费同一状态时，状态step才能放在共同祖先。Pass 1、repair prompt和`quadratic_from_constraints` catalog统一声明：`free_parameters`是应用当前step所在scope的全部可见约束后实际剩余的完整自由符号集合，不能根据下游Goal希望求哪个参数来提前收窄。代码已删除consumer/Goal驱动的basis补写与改写；当前约束缺失时由runtime fail loud，scope错置时反馈step scope与candidate owner scopes。LLM在repair authority允许的scope或Goal中完整重写步骤，代码不自动移动producer，也不把共享对象身份误当成共享状态。本轮F5-F3专项为`200 passed`，相关scope/prompt/reconciliation为`373 passed`，全量Solver为`1884 passed, 12 skipped`，`git diff --check`通过；真实DeepSeek smoke仍待重跑。
   - Pass 1和repair共享同一个typed answer resolver。它在每次组装后按Goal target/type、词法scope可见性、capability active return身份和StepResult DAG验证答案producer；因此同名step更换capability或return role不会沿用陈旧指针。两阶段的LLM authored指针命中任一合法候选时均优先保留模型选择，错误指针只在唯一合法候选时留下normalization后自动纠正；零候选或未被指针消歧的多个候选稳定失败，authored指针与候选清单通过typed feedback进入下一轮。retry同时展示上一版`answer_from`和`required_answer{target_ref, answer_type}`，允许模型有意识地更换producer。
   - 和平二模诊断后的泛化修复已经落地：空`output_targets`/`return_expectations`由content normalizer安全省略并留下typed记录；SourceRef只会自动选取当前Goal或可见祖先scope拥有的同对象最新answer result，不会跨sibling Goal；identity mismatch、动态source要求和公开return role会进入retry执行树；不服务任何未完成Goal的dead失败step不会重新开放已解Goal scope。最新本地门禁为FunctionalPlan契约`318 passed`，F5-F3/C/D、transaction与跨scope联合`150 passed`，全量Solver为`1876 passed, 12 skipped`。尚未用新代码重跑付费live，因此不改变F5-F3的`LIVE 5x1 PENDING`状态。
   - **F5-F3.4 Unified Method diagnostics（COMPLETE；原实现计划标题F5-F3.1）**：新增`functional-diagnostic-authority/v1`与`functional-prompt-diagnostic/v1`，Method、resolver、compiler和runtime check先形成内部authority，再由唯一Projector通过F5-C BindingCatalog投影为Goal可见SemanticRef。完整执行现场仅进入checkpoint/debug，Prompt只保留公开对象、角色、参数、expected/observed和固定repair action，不再使用`<internal-identity-omitted>`。P0 13个Method与`_common.py`已全部迁移为typed `StatelessMethodError`，直接`raise ValueError`为0；未迁移异常、返回契约错误和无法映射的内部身份统一归类为configuration，在Goal repair调用前fail loud，不消耗semantic retry。两份诊断schema及checkpoint快照由同一脚本生成；专项`13 passed`、诊断/Goal执行/transaction/Method联合`205 passed`、全量Solver`1912 passed, 12 skipped`，`git diff --check`通过。
   - **F5-F4 Family path macros**
   - 将`PathTransformation`从LLM协议、capability catalog prompt和领域模型中删除。公开能力不是一个带family分支的万能`two_moving_points_path_minimum`，而是由每个family声明自己的高层path-minimum macro。首批至少区分正方形中点/中心降维、射线等长替换、加权路径和linked auxiliary路径；各macro拥有独立的输入contract、`use_when/do_not_use_when`、source primitive selector和降维invocation graph。只有两个family的题面前提、降维证明和输出语义完全一致时才允许共享同一个公开macro。
   - family-specific macro的Planner显式输入原则上只有题面`path_minimum_target`；`square`、`midpoint_definition`、`square_center`、等长关系、固定端点及其精确Point state等由source authority和声明式selector注入。确实依赖前序动态结果时仍使用typed result dependency，不把内部角色重新暴露成字符串参数。
   - 各family的降维阶段统一生成仅在macro invocation graph内存活的私有`ReducedPathWitness`。它记录等价后的两段路径、真实moving object、固定端点、轨迹依据、精确版本和证明关系，但不写入PlannerStateContext，不生成SemanticRef/CallResultRef，也不成为public return。共享straightening core只消费该私有contract，并继续复用反射候选、候选选择和两点距离method。
   - 公开输出限于`minimum_expression`以及该数学机制自然产生的`optimal_moving_point_expression`或最优构型结果。根据给定最小值反求参数、代入参数和从最优动点恢复最终题面答案点默认继续使用独立通用capability；不得为了减少call数量把整个小问收进不可复用的超大macro。
   - macro内部phase必须保留method invocation、source unit、Goal和scope provenance。Explanation可以把family-specific的“建立约束→路径等价变换”与共享的“反射/拉直→得到最小表达式”展开为多个学生步骤；后续参数求解和答案点恢复使用各自provenance。Planner和Problem wire都不出现`path_transformation`或`ReducedPathWitness`。
   - **F5-F5 Teaching scope与v1退役**
   - 新增`TeachingStepPlacement`，将compiled step确定映射到学生讲解scope。Plan已按Problem scope/Goal组织，但该位置仍需由Goal authority验证；Goal步骤归入Goal owner scope，scope-level步骤若其输入对全部consumer Goal的共同祖先可见，则在最近公共祖先讲解一次，否则按Goal生成引用而不复制runtime计算。
   - `execution_scope_id`只回答状态和method在哪里执行，`teaching_scope_id`只回答步骤在哪个题干/小问下呈现，二者分别审计，禁止Explanation用runtime placement猜教学结构。
   - ExplanationSnapshot保存call、Goal、source unit和teaching scope provenance；G阶段直接消费该sidecar组织小问、动画和对话，不重新从扁平StepPlan或中文文案推断scope。
   - 先以F5-E的scope-native prompt + v1 response建立基线，再用相同模型/参数/样本切v2。验收后物理删除`functional_plan/v1` parser/schema、scope authored fixture和兼容路径，不形成长期双协议。
   - 增加静态门禁：Planner prompt/schema/catalog不得出现`PathTransformation`、`path_transformation`或`ReducedPathWitness`；production plan不得把内部macro phase当作外部SemanticRef/CallResultRef。每个启用路径最值机制的family必须通过自己的macro contract preflight；未知profile fail loud。共享straightening实现只保留一份，测试禁止family macro复制反射、候选选择或距离计算逻辑。系统尚未上线，不保留旧path transformation alias或兼容adapter。
   - 同步删除底层reconciler/replay中的`problem_binding_catalog=None`、全局`semantic_read_catalog()`fallback及v1的`replace_answer_ref_with_goal_target`/`bind_unique_condition_role`repair；裸`RuntimeOrchestrator.solve(ProblemIR)`改为私有debug实现，deterministic入口统一为`solve_problem_ir_debug()`。`planner-problem-view`、`functional_plan/v2`和retry schema按typed union收紧item字段，所有variant使用`additionalProperties: false`。
   - C0.5继续作为scope/version权威门禁，并新增三棵scope树对齐、`unique_prior_producer / explicit_call_result / ambiguous_producer / sibling_rejected`、scope-local answer canonicalization和Goal replacement维度；另增加“前缀成功、第k个step失败、suffix blocked”“独立sibling Goal继续并整体冻结”“ancestor-scope producer失败重开consumer Goal组”“失败Goal完整替换不修改solved Goal”“provisional ghost write为0”。v2 adapter必须真正经过PlanningContext、F5-C sidecar和Goal checkpoint。
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
