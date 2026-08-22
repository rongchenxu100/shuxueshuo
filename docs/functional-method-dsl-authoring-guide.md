# Functional Method DSL 编写规范

本文规定新增或修改 Functional Method 时必须遵守的语义边界、代码契约、诊断协议和测试门禁。

核心判断是：**我们正在实现一门可验证的数学 DSL。**

```text
ProblemPlanningContext
→ LLM 输出 FunctionalPlan
→ 静态编译、类型绑定与 scope 校验
→ canonical call DAG / MethodInvocation
→ Method 运行
→ typed outputs / checks / proposed writes
→ transaction commit 或 rollback
→ typed diagnostic / retry
```

不过需要精确区分三层：

- LLM 直接选择的 `capability` 是 DSL 的公开源指令；
- `Function` 或 `Macro` 是源指令到执行 IR 的 lowering 规则；
- Python `Method` 是最终由运行时调用的确定性原语。

因此，“Method 就是代码”是对的，但它更准确地说是 DSL 的 runtime primitive，而不是全部 DSL，也不是直接暴露给 LLM 的任意 Python 函数。

## 1. DSL 对照表

| 编译语言概念 | Functional Solver 对应物 |
|---|---|
| 源程序 | `functional_plan/v2` |
| 公开指令 | `capability_id` |
| 词法作用域 | Problem/Plan scope tree |
| 源级引用 | `SourceRef`、`StepResultRef`、answer ref |
| 类型系统 | capability args/returns、typed binding、result form |
| 编译器前端 | schema、scope、authority、reference validation |
| lowering | Function adapter 或 Macro invocation graph |
| 执行 IR | canonical calls、typed DAG、`MethodInvocation` |
| runtime primitive | stateless Python Method |
| 对象与状态 | `MathObjectId`、`LogicalStateKey`、`StateVersionId` |
| 执行结果 | `StatelessMethodResult` |
| 编译/运行诊断 | `FunctionalDiagnosticAuthority` |
| 事务 | branch execution、validation、commit/rollback |

静态编译和运行都会“返回结果”，但结果含义不同：

- 静态编译成功返回可执行 IR、精确 binding、DAG 和 provenance；失败返回 typed diagnostic。
- Method 运行成功返回 typed values、checks 和 trace；失败返回 typed diagnostic。
- 只有事务验证通过后，运行结果才成为权威 StateVersion 或 answer evidence。

## 2. 各层职责

### 2.1 LLM

LLM 负责：

- 选择公开 capability；
- 组织 scope 内的数学步骤；
- 提供题面可见的数学实体与 Fact；
- 表达真正的步骤依赖；
- 在 retry 中根据结构化诊断改写失败 Goal。

LLM 不负责：

- 猜 `method_id`、runtime path 或内部 output key；
- 分配 `MathObjectId`、`StateVersionId`；
- 区分 `PointRef/Point`、Function identity/Parabola 或 Symbol/ParameterValue；
- 选择“最新版本”；
- 补 compiler selector、隐藏参数或 provenance；
- 根据异常字符串猜内部对象身份。

### 2.2 静态编译与 binding

静态阶段负责：

- 校验 FunctionalPlan schema 和 scope tree；
- 校验 capability 是否存在、参数名是否合法、必需参数是否齐全；
- 解析 `SourceRef` 和 `StepResultRef`；
- 校验 scope 可见性、类型、cardinality 和 answer authority；
- 选择精确对象身份和 StateVersion；
- 注入 resolver/compiler authority 的隐藏参数；
- 构造 Function 或 Macro 的 canonical call DAG；
- 降低为 `MethodInvocation`；
- 在运行前拒绝循环依赖、悬空引用和 contract drift。

静态阶段不得执行题目求解，也不得根据字符串、点名或数组顺序猜绑定。

### 2.3 Method runtime

Method 只负责一个确定性数学原语：

```python
run(resolved_typed_inputs, kernel) -> StatelessMethodResult
```

Method：

- 接收 compiler/executor 已解析的 typed values；
- 计算数学结果；
- 检查运行时前提和结果不变量；
- 返回 typed outputs、checks 和 trace fragments；
- 用 typed diagnostic 描述失败现场。

Method 不得：

- 读取或写入 `RuntimeContext`；
- 自行搜索 scope、handle、最新状态或替代输入；
- 读取 fixture、gold answer、网络、LLM 或全局可变状态；
- 直接提交 StateVersion；
- 决定 retry prompt 文案。

### 2.4 Transaction runtime

Transaction 负责：

- 在 branch context 中执行 Method；
- 审计实际输入与 F5-C binding sidecar；
- 校验 active returns、result form、checks 和 provenance；
- 用 runtime 数值/表达式等价判断重复 writer 是复用、收敛还是冲突；
- 成功时原子提交，失败时完整回滚；
- 把内部诊断投影为 prompt-safe retry issue。

## 3. 什么时候应该新增 Method

只有同时满足以下条件时才新增 Method：

1. 它表达一个可复用、确定性的数学关系或变换。
2. 输入与输出能用当前 typed runtime contract 明确描述。
3. 运行时可以机械验证主要前提或结果。
4. 它不是一道题的完整固定解法。
5. 现有 Method 不能通过合理扩展覆盖该机制。

优先选择：

- **复用已有 Method**：数学机制相同，只是题面对象名称不同。
- **扩展已有 Method**：新增输入仍属于同一数学关系，且不会造成互斥语义混在一个接口中。
- **新增 Method**：数学运算或判定机制确实不同。
- **新增 Function**：一个公开 capability 对应一次 Method 调用。
- **新增 Macro**：一个稳定公开动作需要多个内部 Method，且中间 wiring 不应交给 LLM。
- **新增 family-specific Macro**：不同 family 的整体降维机制不同，但内部仍复用通用 Method。

不要把“Planner 经常连错线”作为扩充 Method 的理由。先判断问题属于 prompt、capability contract、compiler binding，还是确实缺少 runtime primitive。

## 4. Method 设计原则

### 4.1 一个 Method 只表达一个稳定机制

好的边界示例：

- 由两个点计算距离；
- 由约束求二次函数；
- 由直角和等长关系生成候选点；
- 按象限条件从候选中选点。

不好的边界示例：

- “求某区一模第25题第二问”；
- 一次完成建系、求点、降维、取最值和反求参数；
- 根据 problem id 选择不同算法；
- 为了避免 Planner 连线而吞入所有可能对象。

Method 可以复杂，但复杂性必须来自一个可命名、可复用的数学机制。

### 4.2 纯函数、确定性、无状态

相同 typed inputs 和 kernel 语义必须产生相同 outputs、checks 和 trace。Method 不得依赖：

- 调用顺序；
- 当前 wall clock；
- 随机数；
- 外部服务；
- 前一轮 LLM 响应；
- RuntimeContext 中未显式传入的值。

`MethodSpecSource.is_pure` 对新 Method 默认应保持 `True`。若未来确有 stateful primitive，必须建立独立执行契约，不能偷偷在 stateless Method 中引入副作用。

### 4.3 身份与数值分离

Method 接收的是当前调用已绑定的值，不拥有对象身份和版本选择权。

- `MathObjectId` 表示同一个数学对象；
- `StateVersionId` 表示该对象的一个精确状态；
- Method 只消费 executor 解析后的数值或符号表达式；
- “取当前最新可见参数状态”属于 binding/runtime state resolution；
- 跨 step 的动态对象结果使用 canonical dependency，不由 Method 搜索。

同一个点或函数在不同 scope 中可共享对象身份，同时拥有不同局部 StateVersion。Method 不得因为 label 相同就合并，也不得因为表达式字符串不同就认定对象不同。

### 4.4 runtime 等价是合并结果的语义依据

跨调用去重、复用或收敛必须比较实际 runtime value：

- SymPy 表达式做规范化后等价；
- Point 比较坐标表达式；
- 结构对象按其 typed value contract 比较；
- 同对象的严格收敛形成新 StateVersion；
- 等价重复 writer 复用既有版本；
- 不等价 writer 才是冲突。

当两个`create`位于祖先/后代scope且静态阶段无法安全判重时，必须先隔离执行并
比较实际结果。比较通过不只是“允许两个writer存在”：后代版本必须显式记录最近
已验证祖先版本为`source_version_id`，并同步进入state write、semantic lineage与
checkpoint。后代scope的`latest_state`选择后代版本；需要原始系数身份等ordinal-0
数据时，沿同一version lineage选择唯一根。多个不可比较根必须fail loud。

step id、输入 JSON、字符串展示、capability 名称或 scope 位置只能用于定位，不能作为数学等价证明。

## 5. 输入契约

每个输入必须同时声明领域类型、runtime 类型和唯一 view。推荐使用
`declare_input_views(...)`，由生成器把契约写入 `MethodSpec`：

```python
"fixed_point": {
    "type": "Point",
    "required": True,
},
"quadratic": {
    "type": "Expression",
    "required": True,
    "functional_exposed": False,
},

input_views=declare_input_views(
    identity=("fixed_point",),
    latest_state=("quadratic",),
),
```

规则：

1. 参数名表达数学角色，不使用具体点名或题号。
2. 同类型参数必须靠 role 区分，不能靠位置或名称猜测。
3. `required=True` 的输入应尽量在静态编译期发现缺失；Method 仍需 fail closed。
4. `functional_exposed=False` 表示由typed read authority或声明式derivation注入，
   LLM不应填写；普通recipe/compiler path不得再次提供该输入。
5. 可选参数必须有明确的启用条件，成对参数必须同时出现或同时省略。
6. 不要用一个含义模糊的 `data`、`context` 或任意 mapping 承载多个数学角色。
7. 输入集合若有顺序语义必须使用有序类型；若无顺序语义，Method 应 canonicalize 后处理。
8. Method 不得把错误类型静默转成“看起来能算”的类型。

### 5.1 输入来源与机械派生

`MethodInputSpec`只描述一个Method输入需要的领域类型、runtime类型和view；本次
调用究竟从哪里取得该输入，必须由独立的`MethodInputBindingSpec`声明：

```python
MethodInputBindingSpec(
    input_name="quadratic",
    source=LatestStateSourceSpec(entity_arg="quadratic"),
)

MethodInputBindingSpec(
    input_name="coefficients",
    derivation=CoefficientExtractionDerivationSpec(
        source_input="quadratic",
    ),
)
```

严格绑定必须且只能选择以下一类：

- `source`：选择已经具有数学权威的公开参数、Entity identity、latest state、
  Condition、exact CallResult、producer-linked source或Macro prepared role；
- `derivation`：从已绑定输入机械生成canonical symbol、系数、ordinal-0模板、
  previous output identity、source object identity或free-symbol basis。

`source`负责“本次读取哪个数学对象或状态”，`derivation`只负责“不改变数学对象
选择的机械转换”。二者不能同时出现，也不能缺省。新的Function、Method和Macro
lowering不得声明字符串selector；typed binding尚未有lowerer时必须以
`planner.method_input_binding_lowerer_missing`作为configuration error中止，不能
回退到`FunctionAdapterRegistry._select()`。

F5-F4.2R迁移期间，既有selector只能通过显式
`LegacySelectorInputBindingSpec`存在。它的payload与运行行为保持原样，并由固定
基线禁止新增。`LegacyExpansionSelectorSpec`同样只标记旧expansion边界。新协议
`method-input-binding/v1`只接受typed binding，不接受Legacy selector。后续迁移应
逐项减少Legacy基线，不能用新名字包装一次context扫描。

公共二次函数竖切已经完成该迁移：Function latest state、canonical `x`、系数提取、
ordinal-0模板和公共二次函数parameter symbol均使用strict binding。具名Function在Plan中仍写
SourceRef；F5-C负责把其latest StateVersion与唯一可见的上游call result对账，
derivation再消费同一个exact pin。Method或compiler不得因为需要系数、模板或Symbol
而重新扫描Context，也不得把derived runtime path当成新的数学source authority。
C3几何输出与transition迁移也已完成。输出对象身份必须由
`PreviousOutputIdentityDerivationSpec(output_name)`指向当前call的canonical return
allocation；不得再按Point名称、类型、created entity或物理path猜目标。同一Method若同时
需要对象身份与旧状态，必须声明两个input：identity input读取allocation的
`MathObjectId`，latest-state input读取同一allocation的`previous_version_id`。无旧版本且
input可选时省略；对象、scope或version不一致时fail loud。不得用free-symbol basis替换
一个由输出身份契约明确指定的参数语义。

匿名几何结果使用`ExactCallResultSourceSpec`，并保留独立producer、return和
`item_index`。若输入只接受特定公开return角色，必须在source spec的
`semantic_roles`中声明；例如两个拉直端点分别接受
`straightened_endpoint_1/2`，不能依赖已退役selector补充角色。interchangeable group
只允许在完整typed authority确定后交换槽位，不允许按runtime type重新搜索。由ParameterValue恢复其Symbol身份时使用
`ProducerLinkedSourceSpec(source_arg="parameter_value", producer_arg="parameter")`，只跟
该exact result的producer，不扫描当前call的其他producer或全局Context。

通用Entity/State竖切也已经完成：公开参数中由Plan明确指定的Point/Function使用
`PublicArgSourceSpec`，F5-C再根据Method view生成纯identity或exact latest-state
authority；匿名Expression、MinimumExpression、Line和PathTransformation使用
`ExactCallResultSourceSpec`，必须保留精确producer与return。生产family中不再声明
`read_type:*`。仍需从题面关系、提取preflight或context closure推导的几何角色不属于
PublicArg，必须留到对应typed resolver迁移，不能为了减少selector而伪装成显式输入。

Fact/Condition与语义角色竖切也已经完成。所有题面Fact和运行期Condition先注册到
不可变`ConditionBindingAuthorityIndex`，索引保存exact `ConditionId`、公开
SourceRef、canonical kind、owner/valid scope、对象角色和source units。Method binding
只允许两种选择方式：

```python
# Planner明确选择一个公开Fact。
MethodInputBindingSpec(
    input_name="condition",
    source=ConditionSourceSpec(arg_name="minimum_value"),
)

# 公开实体已经确定，代码匹配唯一可见关系。
MethodInputBindingSpec(
    input_name="parameter_constraint",
    required=False,
    source=ConditionSourceSpec(
        condition_kinds=("symbol_constraint",),
        related_args=("parameter",),
    ),
)
```

第二种写法按related args的canonical `MathObjectId`匹配，只查看当前scope及祖先。
零候选、多候选、sibling/descendant候选或角色身份不一致都不得按名称、runtime path、
插入顺序或描述文本猜测。Condition唯一选定后，Point/Symbol角色可以通过
`LatestStateSourceSpec`、`EntityIdentitySourceSpec`、`ProducerLinkedSourceSpec`或
纯机械derivation进入同一per-call F5-C ledger；context resolver不能手工构造一条
绕过binding spec的运行输入。

Checkpoint保存exact `ConditionId`及角色绑定，restore只验证revision、scope、角色和
runtime type后复用，不再次调用Condition resolver。缺失、不可见和歧义分别使用
`functional.method_input_condition_missing`、
`functional.method_input_condition_not_visible`、
`functional.method_input_condition_ambiguous`；F5-C选择完成后的任何ConditionId、角色、
scope、producer或类型变化统一为`planner.method_input_view_authority_drift`。

### 5.1 Method input view

每个内部 input 必须且只能声明一种 view：

| view | 运行时含义 | LLM wire |
|---|---|---|
| `identity` | 稳定 MathObject 身份 | 具名数学实体 ref |
| `latest_state` | 当前 scope 最近可见、已验证的对象状态 | 同一个具名实体 ref |
| `immutable_value` | 不可变 Fact、Constraint 或 source 常量 | Fact/entity ref |
| `exact_result` | 某个匿名 call return 的精确结果 | `StepResultRef` |

Method 不读取 Context，也不自己寻找 latest。Typed execution graph先证明唯一、
scope-safe的producer；call preparation再为每个input和每个聚合元素创建严格的
`MethodInputReadAuthority`，pin住Entity identity、exact StateVersion、Condition或
CallResult。`MethodInputViewResolver`只消费这份authority，将同一个公开实体lower成
Method所需的runtime表示；物理runtime path只是执行地址，不能参与选源。一个Method
如果同时需要对象身份和状态，Function/Macro应把同一公开实体lower为两个内部input。

固定不变量：

1. `identity`只返回纯MathObject身份，不得注入当前坐标、表达式或其他状态。
2. `latest_state`在首次执行前解析一次并pin exact StateVersion；checkpoint restore直接
   复用该pin，不重新查询latest。
3. `immutable_value`只能来自明确的Entity/Fact/Condition authority。
4. `exact_result`只能来自明确的CallResult或InvocationResult，不能成为具名Entity读取
   最新状态的旁路。
5. tuple/list输入逐项拥有独立read authority；compiler按稳定`item_index`逐项lower，
   executor逐项resolve。两层都不得对聚合值直接`context.read_path`，缺号、重复source
   或重新排序必须报`planner.method_input_view_authority_drift`。
6. Strategy生产调用缺少read authority，或scope、type、version与authority不一致时
   必须fail loud；按参数名、`*_ref`后缀或runtime type猜测只允许独立debug adapter。

`quadratic_template`是典型的code-owned隐藏输入。Method声明它为
`functional_exposed=False`和`immutable_value`；family binding与recipe均不得写入。
call preparation根据同一`QuadraticFunction`的exact latest-state authority，沿已验证
version lineage选择唯一ordinal-0根并注入。compiler supplied path、零个根或多个根
都属于configuration/authority错误，不能被执行层静默覆盖。

具名实体不能通过 `StepResultRef`指定普通状态。即使某个 return 的 runtime 类型
适合 `exact_result`，只要它已通过`output_targets`绑定到题面实体，后续就必须使用
实体 ref。`StepResultRef`只用于没有稳定题面身份的候选集、路径见证、最小值表达式
等匿名中间结果。

`view`与Planner wire允许的来源形式是两个正交契约。`view`决定一个具名
`SourceRef`在调用边界被解析成identity、latest state、immutable value还是精确值；
`allows_anonymous_result=True`只表示同一个公开参数还可以接收匿名
`StepResultRef`。不得因为内部Method使用`latest_state`就自动开放
`StepResultRef`，也不得因为参数允许匿名结果就跳过具名MathObject的SourceRef规则。

典型例子：

- `quadratic_vertex_point.parabola`只接受具名函数ref，resolver读取该函数的最新状态；
- `parameter_from_expression_value.expression`可接受匿名表达式return，因此显式声明
  `allows_anonymous_result=True`；
- 一个参数同时接受具名Point的最新状态和匿名候选Point时，仍声明
  `latest_state + allows_anonymous_result=True`，两条路径最终都必须通过相同runtime
  type、scope和provenance校验。

新增或修改Method时，生成spec与测试必须分别断言`view`和
`allows_anonymous_result`。这两个字段不能根据参数名、runtime type或`*_ref`后缀推断。

`latest_state`必须满足词法 scope 可见性。sibling 私有状态、多个不可比较 writer
或不存在可见状态都必须 fail loud；不得按 label 或生成顺序猜测。

#### 5.1.1 实体关系权威

两个实体分别可见，不等于它们之间的数学关系可见。凡是 Method 的计算前提依赖
`点在曲线上`、`点在线段上`、`两线垂直`等题面关系，`MethodSpec`必须声明结构化
`input_relations`，静态 binding 必须把每一组实体输入解析到一个精确 Condition：

```python
input_relations=(
    MethodInputRelationSpec(
        relation_kind="point_on_curve",
        point_arg="curve_points",
        curve_arg="quadratic",
        cardinality="for_each",
        accepted_condition_kinds=(
            "point_on_curve",
            "point_on_curve_with_x_coordinate",
        ),
    ),
),
```

固定规则：

1. Planner wire仍只填写公开数学实体，不额外填写隐藏 Fact 参数。
2. resolver只读取结构化Condition角色；禁止按点名、label、坐标相等、handle后缀或描述文本推断关系。
3. 列表输入逐项绑定Condition，并在诊断中保留`arg_name + item_index`。
4. Condition必须同时匹配Point与curve的MathObject身份，并在调用scope中词法可见。
5. sibling私有Condition不得进入semantic index、producer DAG或retry cone，也不得在错误信息中泄漏其scope。
6. 成功绑定的ConditionId、owner scope和source unit必须进入F5-C sidecar、binding signature及provenance。
7. 缺关系或关系不可见属于planner-repairable；Method契约本身无法解析属于configuration，不消耗semantic retry。
8. 关系校验发生在Method运行及state write之前；Method不得收到未经证明的实体组合。

当前首批迁移的Method为：

- `quadratic_from_constraints`
- `parameter_from_curve_point_on_quadratic`
- `point_candidates_from_curve_point_condition`

例如根scope可使用`A∈parabola`构造开放二次函数；子问`i`中的
`D∈parabola`只能在`i`及其后代调用中消费。即使D实体定义在根scope、坐标也已经
算出，根scope仍不能借用子问Condition闭合抛物线。

#### 5.1.2 可交换输入组

当多个输入槽位只表示一个无序数学集合，交换它们不改变结果时，Method必须用
结构化字段声明，而不能只在`summary`、`role`或注释中写“顺序可交换”：

```python
interchangeable_arg_groups=(
    ("line_p1", "line_p2"),
),
```

`interchangeable_arg_groups`是代码执行的唯一依据。描述文本只负责帮助LLM和维护者
理解，不得被parser、compiler或canonicalizer读取并恢复语义。

固定规则：

1. 组内输入必须具有完全一致的`domain_type`、`runtime_type`、view、required、
   exposure、cardinality和`allows_anonymous_result`；spec生成与加载阶段均fail loud。
2. `interchangeable_arg_groups`与`distinct_arg_groups`正交。直线的两个端点既可交换，
   又必须是不同对象，应同时声明两项。
3. Planner可按任意合法顺序填写。wire canonicalizer根据结构化spec稳定排列输入来源：
   具名Entity SourceRef优先，随后是published Goal result和匿名StepResultRef；同类来源
   保持原顺序，并记录`functional.interchangeable_args_permuted` normalization。
4. canonicalizer的换位不是数学证明。换位后的调用仍必须执行Method checks、result
   form、对象身份、runtime等价/收敛和transaction门禁。
5. 只声明真正具有置换不变性的角色。`known_point/target`、有方向的起点/终点、旋转
   左右侧、射线端点等即使类型相同，也不得为了容错而加入可交换组。
6. 若组内任一槽位允许匿名结果，所有槽位必须一致允许；不得再出现“同一条无向直线
   的第一个端点只能SourceRef、第二个端点却允许StepResultRef”的非对称schema。
7. 新增或修改可交换组时，必须用真实Method `run()`逐组交换输入并比较typed outputs与
   checks。spec合同一致只证明两个槽位可以使用同一种source形态；canonicalizer也只做
   确定性容错，它们都不能证明Method实现具有数学置换不变性。具名Entity默认保持LLM
   原顺序，只有runtime执行结果才能作为正确性的最终依据。

典型适用项包括距离两端点、中点两端点、每条无向直线的两个确定点、线段长度的
两个端点及正方形对顶构造中的两个相邻点。Function/Macro可声明更高层的候选搜索，
但不能用搜索结果绕过Method输入组的typed contract。

#### 5.1.3 Planner 公开类型词汇

LLM 看到的输入与返回值不是同一种投影：

- capability input 的 `domain_type`描述模型可选择的数学实体或 Fact；
- capability return 的 `type`描述执行后产生的 canonical 值；
- Goal `answer_type`与 return `type`使用完全相同的词汇，必须逐字匹配。

例如：

| 输入实体 `domain_type` | 产生值 `type` |
|---|---|
| `QuadraticFunction` | `Parabola` |
| `Symbol` | `ParameterValue` |
| `Point` | `Point`或`PointList`，由 Method 输出决定 |

因此不得把 return 的 `Parabola`重命名为`QuadraticFunction`、把
`ParameterValue`重命名为`Symbol`，或把`PointList`重命名为
`PointCandidates`。Function、Macro 和最终 Capability Catalog 必须统一使用
`planner_public_types.py`投影，禁止各自维护别名表。描述文本也不得引入与
`type`冲突的第二套返回值名称。

### 5.2 Optional input 的门禁

只有在以下两种情况下使用 optional input：

- 它真正控制同一数学机制的可选求值，例如对已得表达式代入一个参数；
- 它是历史/特殊消歧所需，但启用条件能由 contract 精确说明。

若 optional input 会改变主要算法、输出类型或数学含义，应拆成不同 Method 或不同公开 Function。避免一个 capability 声明多个互斥输入组合，让 Planner 猜实际模式。

### 5.3 题面表达式与 Symbol identity

题面 JSON 中的 `x`、`vector`、`x_range`、condition `value`、relation `scale` 等数学字符串只能在 `RuntimeContext` 构建边界解析一次。解析时必须使用该题唯一的 canonical symbol environment：

```text
Problem JSON string
→ RuntimeContext.symbols
→ canonical SymPy Expr
→ state binding / latest visible parameter closure
→ Method typed input
```

Method 不得对这些字段再次调用 `sympify()` 或 `kernel.expr()` 并临时构造 locals。SymPy 中显示名相同的 Symbol 可能具有不同 assumptions；反过来，数学上相等、assumptions 相同的 Symbol 在 artifact round-trip 后也不保证是同一个 Python 实例。`MathObjectId`/registry 才是运行时身份权威，Python 的 `is` 不是契约。二次解析会导致：

- F5-C 无法把自由参数绑定到 canonical `MathObjectId`；
- 最新可见 `ParameterValue` 无法代入 PointRef 或 Condition；
- 表达式看似含 `b`，实际绕过 state/provenance authority；
- Method 在错误的开放状态上继续计算，最终表现为 configuration error。

新 Method 只允许两类表达式输入：

1. 已绑定 canonical Symbol 的 `sp.Expr`；
2. 没有自由 Symbol 的纯常量字面量。

从 `PointRef.definition`、`Condition` 或 `Constraint` 读取标量时，使用 `_require_canonical_runtime_expression(...)` 做边界断言。若含自由变量的字符串到达 Method，必须报 `planner.method_contract_invalid`，不得在 Method 内补 locals。参数约束可使用 `_canonicalize_runtime_constraint(...)`。

Method 可以创建算法内部 dummy Symbol，但必须满足：

- 名称使用内部命名空间；
- identity 由该 Method 的 typed return 显式发布；
- 不冒充题面 Symbol；
- 不通过名称与题面 Symbol 合并。

最新参数状态的选择和代入由 transaction/runtime 在 Method 调用前完成，并递归覆盖 `PointRef.definition`、mapping、tuple 和 list。Method 看到的是当前 scope 下已闭合或仍合法开放的真实状态，不负责搜索 latest。

测试至少应断言：表达式中的每个自由 Symbol 都能唯一解析到题目 registry 中的 `MathObjectId`。必须覆盖一个“数学相等但 Python `is` 为假”的 artifact round-trip Symbol，以及一个最新 `ParameterValue` 自动闭合 PointRef 表达式的用例。

### 5.4 等价符号基底的 Method 输入视图

同一个函数状态可以有多个等价表示。例如题面函数为：

```text
y = x² - bx + c
```

在局部约束 `b+c=-1` 下，当前状态既可以写成：

```text
x² - bx - b - 1
```

也可以写成：

```text
x² + (c+1)x + c
```

这两种表示属于同一个 Function MathObject，不应要求 Planner 为下游每个结构化输入手工选择同一字母。例如题面点 `M.x=b+1/2` 在当前 `c` 基底状态下，应由代码为本次调用投影成 `-c-1/2`。

负责产生开放或闭合符号状态的 Method 必须把 authored basis 与 runtime state 分开处理。以 `quadratic_from_constraints.free_parameters` 为例：

- 开放状态必须由 Planner 填写一组非空、完整、线性独立的参数基底；缺失或 `[]` 是 `planner_repairable` 输入错误。
- 闭合状态允许 `free_parameters: []`，也允许省略该参数；两种 wire 写法 canonicalize 为相同语义，均不得报错。
- `[b]` 与 `[c]` 是否等价不能由名字、输入顺序或下游 Goal 决定，必须由 runtime 对同一组约束逐个证明。
- `[b,c]` 不是一维状态的完整独立基底；“包含了所有出现过的字母”不等于正确基底。
- JSON Schema 只负责接收 `[]`；状态是开放还是闭合只能在实际约束分析后判定。因此 wire 可以宽容，runtime 语义必须严格。

若一个 optional collection 在 wire 上需要接受 `[]`，在 Method input source 中显式声明：

```python
"free_parameters": {
    "type": "SymbolList",
    "required": False,
    "allows_empty_collection": True,
}
```

该声明只控制 wire Schema，不得绕过 Method analyzer 的开放状态门禁。

需要这种能力的 Method 在 `SPEC.inputs` 中声明：

```python
inputs={
    "parabola": {
        "type": "Parabola",
        "required": True,
        "symbolic_basis_role": "state_anchor",
    },
    "x": {"type": "Symbol", "required": True},
    "target": {
        "type": "PointRef",
        "required": True,
        "symbolic_basis_role": "align_to_anchor",
    },
}
```

规则：

1. 一个 invocation 最多有一个 active `state_anchor`。
2. anchor 必须是同一 canonical Function MathObject 的已验证运行时状态。
3. `align_to_anchor` 可用于 `PointRef`、Point/PointList、Condition、Constraint 等携带表达式的结构值。
4. InvocationExecutor 从 canonical source function 与当前状态的多项式系数差确定关系，只在关系唯一时生成临时输入视图。
5. 投影只修改本次 Method 调用的 ephemeral view，不修改 Problem、PointRef、已提交 StateVersion 或 provenance。
6. 零个证明分支或多个证明分支都 fail loud；禁止按名称、字符串相似度或“常见正根”猜测。
7. Method 本身只消费投影后的 typed input，不得再次实现 `b→c`、`c→b` 等题型转换。

新增函数状态消费者时，应先判断它是否读取题面结构中可能携带系数表达式的值。若是，应接入上述通用角色；不要在 Method 文件里增加题目点名或参数名特判。

## 6. 输出契约

Method 输出必须是稳定的 typed mapping：

```python
outputs = {
    "point": TypedValue("Point", point, source=self.method_id),
    "distance": TypedValue(
        "MinimumExpression",
        distance,
        source=self.method_id,
    ),
}
```

规则：

1. output key 是 Method contract，不随题目或数值改变。
2. output type 必须与 `SPEC.outputs` 完全一致。
3. Method 不写 runtime path；compiler 决定 output destination。
4. Method 不分配对象身份或 answer identity；Function/Macro contract 和 B1/B3 负责。
5. invocation 声明为 active 的 output 必须实际返回，否则是 `configuration` error。
6. optional output 必须由 compiler 的 active-return contract 决定，不能靠 runtime 静默缺失。
7. 多种 result form 使用 `scalar_result_forms` 描述，不要伪装成多个无条件候选 return。
8. 运行值应尽量 canonicalize，便于后续做可靠的 runtime equivalence。

### 6.1 Result form

`open_expression`、`closed_value`、`open_state` 和 `closed_state` 描述的是实际结果状态，不是 LLM 的主观标签。

- Method 返回数学值；
- runtime 根据自由符号和类型 contract 判定实际 form；
- Planner 可声明需要的 form；
- compiler/runtime 校验期望与实际是否一致；
- 不能仅因 return 名称叫 `evaluated_*` 就认定它已经闭合。

## 7. Preconditions、Checks 与异常

三类失败必须分开：

| 场景 | 表达方式 | 例子 |
|---|---|---|
| 运行前提不成立 | 抛 `StatelessMethodError` | 缺点、输入状态未物化、线退化 |
| 运算无结果/多解/矛盾 | 抛 typed result error | 候选为空、候选不唯一、约束冲突 |
| 已产生结果但后置验算失败 | failed `CheckResult` | 点不在曲线上、长度不相等 |

### 7.1 前提失败

使用 `_common.py` 提供的 typed helper：

- `method_input_missing`
- `method_input_invalid`
- `method_input_state_unavailable`
- `method_precondition_failed`
- `method_result_empty`
- `method_result_ambiguous`
- `method_result_inconsistent`

新增或修改 Method 不得直接 `raise ValueError`。未迁移的旧异常会被包装为 `planner.method_contract_invalid`，属于代码配置错误，不会让 LLM 盲目 retry。

该门禁扫描整个 `runtime/methods` 目录，不使用 P0/P1 白名单。Method 调用共享数学 helper 时也必须在 Method 边界完成分类：symbolic closure 统一经过 `_require_unique_symbolic_closure`；外部 profile/geometry helper 的预期失败必须捕获并转换为 typed diagnostic。只有注册缺失、Spec 漂移和实现未知异常可以保留为 `configuration`。

### 7.2 后置检查

使用 `_check(...)` 返回机器可读的 `CheckResult`。失败检查应尽量包含：

- 稳定 `code`；
- `expected` 与 `observed`；
- 涉及的 subject role/arg；
- `retryability`；
- 固定 `repair_action`。

`detail` 服务 debug 和展示，不是下游恢复身份或分类错误的权威。

### 7.3 Contract bug

以下错误必须归为 `configuration`，直接 fail loud，不消耗 semantic retry：

- SPEC 与实现的输入/输出不一致；
- Method 报成功但缺失 active output；
- 未知异常；
- compiler adapter 或 Macro output mapping 错误；
- runtime type、identity、destination 或 provenance contract 漂移。

不要把代码 bug 包装成“Planner 选错步骤”。

## 8. 统一诊断契约

所有可执行失败最终进入：

```text
FunctionalDiagnosticAuthority
→ FunctionalPromptDiagnosticProjector
→ FunctionalPromptDiagnostic
```

Method 应报告执行现场，不直接写 LLM 文案。至少提供：

```text
code
category
retryability
subject.role
subject.arg_name
subject.internal_ref（若存在）
expected
observed
repair_action
```

运行层会补充 `method_id`、`capability_id`、`scope_id` 和 `step_id`。Projector 再通过 BindingCatalog 将内部身份映射成 Goal 可见的 `SemanticRef`。

### 8.1 Retryability

| retryability | 含义 | 行为 |
|---|---|---|
| `planner_repairable` | 修改 Plan 可以修复 | 进入失败 Goal 的 repair prompt |
| `problem_semantics` | 题面语义矛盾或提取错误 | 返回 Problem/extraction 边界处理 |
| `configuration` | 代码、Spec 或 compiler contract 错误 | 立即 fail loud，不调用 Planner retry |

`original_message` 只用于完整 debug。Prompt 不得解析自然语言恢复对象身份，也不得出现 `<internal-identity-omitted>` 这类失去实际修复信息的占位符。

### 8.2 诊断示例

```python
raise method_input_missing(
    "fixed endpoint is not materialized",
    arg_name="fixed_point",
    role="fixed_endpoint",
    expected={"type": "Point", "state": "materialized"},
    observed={"state": "missing"},
    repair_action="provide_visible_point_producer",
)
```

Method 只陈述“缺少哪个角色、期待什么、实际是什么”。若执行现场持有已绑定的内部对象身份，再通过 `internal_ref` 一并报告；是否展示为 `M`、`A` 或其他 prompt ref，仍由唯一诊断 projector 决定。

## 9. SPEC 是事实源

每个 Method 的实现和 `SPEC = MethodSpecSource(...)` 必须在同一 Python 文件中。`internal/method-specs/*.json` 是生成资产，不是第二份手工权威。

至少认真填写：

- `title`：稳定、通用的数学动作名称；
- `summary`：Planner 选择能力所需的短说明；
- `description`：完整适用语义；
- `solves`：能力解决的机制标签；
- `inputs` / `outputs`：runtime contract；
- `preconditions` / `postconditions`：声明式条件；
- `do_not_use_when`：相邻能力的明确排除条件；
- `scalar_result_forms`：符号开放态/闭合态；
- `symbolic_closure`：参数反求与代入闭包；
- `explanation` / `visual`：稳定角色映射，而非具体点名。

注意：SPEC 文案不能替代 runtime 校验。凡是代码可确定检查的条件，都必须由 compiler、Method 或 transaction 执行。

更新后生成资产：

```bash
cd server
uv run python -m shuxueshuo_server.solver.runtime.methods.generate_specs
```

并将 Method class、`SPEC` 和实例同时注册到 `runtime/methods/__init__.py`。

## 10. 推荐代码骨架

```python
from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ExampleMethod:
    """由两个已物化点计算一个可验证的几何量。"""

    method_id = "example_method"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        p1: Point = inputs["p1"]
        p2: Point = inputs["p2"]

        if p1 == p2:
            raise method_precondition_failed(
                "the two points must be distinct",
                arg_name="p2",
                role="second_endpoint",
                expected={"state": "distinct_from_p1"},
                observed={"state": "coincident"},
                repair_action="repair_input_binding",
            )

        value = sp.simplify(kernel.distance(p1, p2))
        checks = [
            _check(
                "result_nonnegative",
                bool(value.is_nonnegative),
                "结果应为非负数。",
                code="functional.method_check_failed",
                expected={"relation": ">= 0"},
                observed={"value": str(value)},
                repair_action="repair_failed_step",
            )
        ]
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "value": TypedValue(
                    "Expression",
                    value,
                    source=self.method_id,
                )
            },
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "计算目标量",
                    "得到后续步骤所需的表达式",
                    "使用已声明的数学关系直接计算。",
                    f"value={value}",
                    f"目标量为 {value}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=ExampleMethod,
    title="计算示例目标量",
    summary="由两个不同的已物化点计算目标表达式。",
    description="适用于两个端点均已确定且不重合的场景。",
    solves=("derive_example_value",),
    inputs={
        "p1": {"type": "Point", "required": True},
        "p2": {"type": "Point", "required": True},
    },
    input_views=declare_input_views(latest_state=("p1", "p2")),
    outputs={"value": "Expression"},
    preconditions=("两个输入点均已物化且不重合。",),
    postconditions=("输出表达式满足该几何关系。",),
    do_not_use_when=("题目需要候选枚举或分支选择。",),
)
```

骨架不是复制模板。每个 Method 必须根据真实数学机制定义类型、检查、diagnostic 和 result form。

## 11. Function、Macro 与 Method 的边界

### Function

当一个公开 capability 可以直接映射为一次 Method invocation 时使用 Function。FunctionSpec 负责：

- 公开参数名与 Method input 的 adapter；
- 声明式typed input source与机械derivation；
- binding authority、role、cardinality；
- active return 与 public return；
- identity/write/result-form policy。

新Function/Method不得增加binding selector。历史`selector`是Method spec尚未声明
input view、scope与exact source时的v1 adapter分发键；它会扫描context并返回
runtime path，已不是生产authority。Method spec只声明所需domain/runtime type
与`identity | latest_state | immutable_value | exact_result`视图，per-call F5-C
和`MethodInputReadAuthority`唯一决定本次实际读取的Entity、Condition、
StateVersion或CallResult。

在selector物理删除前，过渡投影必须遵守：

- `projection_source_arg`、`projection_source_return`、
  `projection_source_producer_arg`、return identity、literal symbol、
  `projection_entity_roles`和`projection_free_symbol_basis`都是并列证据通道，
  不存在“第一个命中即返回”的优先级。
- 当同一selector同时声明`projection_source_arg`和
  `projection_source_producer_arg`时，producer证据只能沿前者实际值的
  `source_call_id`读取；当前call消费的其他producer不得进入该证据桶。
- 对required或已被消费的input，每个非空通道必须恰好指向一个
  `FunctionalArgSourceIdentity`，所有通道必须一致；否则报
  `planner.method_input_view_authority_drift`。未被消费的optional input零候选或
  多候选、或通道互相冲突时表示“未选择”，不形成binding。这是等待F4.2R
  删除selector的过渡行为，不代表typed authority验证成功。
- `projection_entity_roles`确实会在当前scope及祖先中搜索角色与类型
  兼容的Entity；这是明确的过渡契约，不得跨sibling，零个或多个候选
  都不得猜测。
- `projection_free_symbol_basis`只在全部可见自由Symbol唯一时形成证据；
  禁止按出现次数、coverage、参数名或排序选择winner。
- 可选或机械input没有typed selected source时，不得写入仅含selector id的
  F5-C ledger记录。过渡期v1 adapter可在派生execution IR中完成机械lowering，
  但不得伪装为typed source authority。

### Macro

当一个稳定动作需要多个内部 Method 时使用 Macro。Macro 负责：

- 声明内部 invocation graph；
- 隐藏中间 output；
- 定义typed input derivations、aliases 和 public returns；
- 保证多个内部步骤作为一个事务提交或回滚。

Macro 不应固定整道题路线。family-specific path reduction 可以是 Macro；通用的距离、反射、候选筛选仍应是复用 Method。

每个 Macro 必须声明执行模式：

- `direct`：唯一确定的内部调用图，不声明 search spec；
- `runtime_search`：声明可搜索数学角色、candidate builder、validation policy 和
  `max_candidates <= 32`。

声明`runtime_search`还必须在`MacroImplementationRegistry`中完整注册candidate
builder、validation policy、lowerer、postcondition和evidence builder；缺少任一项都
是`planner.macro_contract_invalid`，不能退化为结构选择或执行后补报告。尚未完成
pre-binding实现的Macro必须明确声明`direct`。

`runtime_search` Macro的内部Method wiring由Registry-owned
`MacroMethodInputBindingSpec`声明。可选来源仅为`MacroPreparedRoleSourceSpec`、内部
`ExactCallResultSourceSpec`或`PreviousOutputIdentityDerivationSpec`。winner确定前这些
角色不形成最终F5-C binding；winner确定后chosen对象与exact state pin一次性写入read
authority，clean replay不得重新搜索。authored hint只保存在search report。transaction
可把canonical path临时改写到隔离snapshot执行，但checkpoint、witness和最终replay必须
保存canonical source及同一个authority signature。

Runtime-search Macro 可以把 LLM 声明的策略角色作为首选提示，但必须在隔离 branch
中执行有限候选并通过 Method checks、Macro postcondition、active return、identity、
Goal 与 provenance 门禁。唯一成功候选可以纠正提示；多个成功候选只有在实际 runtime
输出等价时才能按调用数、符号复杂度和稳定 candidate id 确定选择；非等价歧义必须
返回给 LLM。winner 必须从干净 Context 重放后再提交，shadow 结果永不复制进事务。
winner确定前只能持有pending F5-C draft；只有winner选择完成后才能finalize该call的
input/relation/return binding和provenance。authored错误hint只进入search report，不能
进入chosen对象的source binding。

Function/Macro 必须区分“策略提示”和“证明 lowering”：

- LLM 引用动点、映射点、反射对象、候选分支或拉直方向等数学实体；
- compiler/resolver 恢复 canonical identity、固定端点和证明所需事实；
- Macro 选择内部调用图并可执行有界 runtime search；
- Method 只验证每个候选中的确定性原语；
- output role authority 保存经过 runtime 验证的最终选择，不从点序或名称直接创造语义。

因此 `vertex_4 -> moving_object` 这类位置规则不能直接成为权威。LLM 可以提示
`moving_point=G`；Macro 必须验证 G，或在唯一 runtime-valid 替代项存在时记录
`authored=G/chosen=...`的纠正证明。多个非等价替代项不能静默选择。

### 不要跨层补洞

- LLM 选错策略：改 capability 文案、family catalog 或 retry 诊断。
- 公开参数设计错：改 Function/Macro contract。
- static binding 错：改 compiler/resolver。
- 数学原语不完整：改 Method。
- 状态复用/冲突错：改 transaction/runtime equivalence。
- prompt 中错误信息缺失：改 diagnostic authority/projector。

不要为了修复上一层问题，把下层 Method 变成会搜索、猜测和自动改 Plan 的万能函数。
有界候选搜索只能由显式声明`runtime_search`的 Macro 执行。

## 12. 明确禁止的反模式

- 在 Method 中按 `problem_id`、考试名称、具体点名或答案值分支。
- 直接抛 `ValueError`、`AssertionError` 或未分类异常表达可预期数学失败。
- 从 message 文本解析对象身份、候选数量或 retryability。
- 读取 RuntimeContext 并自行选择 latest state。
- 在 Method 内重新解析 PointRef/Condition/Constraint 的题面数学字符串，或按名称临时创建 Symbol locals。
- 依靠 step id、handle 后缀、数组顺序或字符串相似度绑定输入。
- 用静态输入 JSON 相同判断两个步骤结果等价。
- 在 Method 中为避免 retry 而静默补事实、替换参数或选择候选。
- Macro 搜索没有候选预算、隔离执行或歧义门禁。
- 在 Method 内写 StateVersion、answer binding 或 provenance。
- 声明多个潜在 return，却没有 active-return 规则。
- output type 随实际分支变化但 SPEC 不表达 union/分支。
- 把 failed check 当 warning 后继续提交。
- 用 trace 文本作为 runtime authority。
- 把 expected answer、gold fixture 或 planner few-shot 放进 Method。

## 13. 新增 Method 的实施顺序

1. **先证明需要新原语**：检查已有 Method、Function 和 Macro。
2. **写数学 contract**：输入角色、输出、前提、后置条件、空/多解/矛盾语义。
3. **确定层次**：哪些参数由 LLM 提供，哪些由 resolver/compiler 注入。
4. **先写 Method 单测**：正常、边界、空结果、歧义、冲突。
5. **实现 Method 与 typed diagnostic**。
6. **在同文件写 SPEC**，生成 `internal/method-specs`。
7. **注册 Method**：class、SPEC source 和默认实例三处一致。
8. **定义 Function 或 Macro**：补 typed adapter、returns、identity/write policy。
9. **补静态编译测试**：错误参数、错类型、错 scope、active returns。
10. **补 transaction 测试**：runtime result、checks、rollback、版本和 provenance。
11. **补 retry diagnostic 测试**：prompt-safe ref、repairability、无内部身份泄漏。
12. **补 Explanation/Visual 角色测试**，若该能力进入教学链。
13. **运行全量回归与真实 smoke**，确认不是单 fixture 特判。

## 14. 分层测试矩阵

### Method 单元测试

- 正常输入得到确定 outputs；
- 输入排列在无顺序语义时不改变结果；
- 所有 runtime precondition 都有 typed code；
- 空、歧义、矛盾分别产生不同诊断；
- failed check 包含 expected/observed；
- 相同输入重复运行 hash/数学值不漂移；
- 不读 fixture、Context、LLM 或网络。
- 题面表达式中的自由 Symbol 可唯一解析到 canonical registry identity，含自由变量的原始字符串在 Method 边界 fail loud。
- 等价函数基底的结构化输入由 invocation view 投影；零分支和多分支均 fail loud，且不改写 source/state authority。
- 最新参数状态能在 Method 前闭合 PointRef/Condition，且不会跨 sibling scope 泄漏。

### SPEC 与生成资产

- Python `SPEC` 可加载；
- inputs/outputs 与实现一致；
- scalar result forms 只引用已声明 output；
- 生成 JSON 与代码源零漂移；
- catalog 文案不包含题目特判或内部身份。

### Static compiler

- public args 精确映射到 Method inputs；
- missing/unknown/wrong-type arg 在执行前失败；
- resolver/compiler 参数不能被 LLM 覆盖；
- scope/sibling visibility fail loud；
- active return 集合与 invocation outputs 一致；
- Function lowering 不做候选搜索；Macro 仅按显式 execution/search contract 搜索。
- Macro role 的 authored/chosen 值及 runtime checks 进入 provenance/checkpoint。

### Runtime transaction

- 每个 active output 均被返回；
- check failure 完整回滚；
- 等价重复结果复用，严格收敛建新版本，冲突拒绝；
- failed call 无 ghost write；
- exact input version 和 provenance 不漂移；
- companion writes/results 共享同一 call authority。

### Retry diagnostic

- Method 执行现场映射成正确的 prompt SemanticRef；
- role、arg、expected/observed 和 repair action 保留；
- configuration error 不触发 semantic retry；
- prompt 不泄漏 `MathObjectId`、`StateVersionId`、source unit 或 runtime path；
- 下一轮能定位失败 Goal，而不打开无关 sibling scope。

## 15. 常用命令

```bash
cd server

uv run python -m \
  shuxueshuo_server.solver.runtime.methods.generate_specs

uv run pytest \
  tests/solver/test_runtime_stateless_methods.py \
  tests/solver/test_method_spec_loader.py \
  tests/solver/test_functional_diagnostics.py -q

uv run pytest \
  tests/solver/test_functional_direct_compiler.py \
  tests/solver/test_functional_transaction_execution.py \
  tests/solver/test_functional_goal_retry_execution.py -q

uv run pytest tests/solver -q
git diff --check
```

## 16. Review checklist

- [ ] Method 表达通用数学原语，而非单题路线。
- [ ] LLM 只接触 public capability，不需要知道内部 method wiring。
- [ ] 每个 input 有唯一 domain/runtime 类型、view、角色和 required/exposed 语义。
- [ ] 每个 output 有稳定 key、类型和 active-return 规则。
- [ ] open/closed result form 由 runtime value 决定。
- [ ] Method 不读取 Context、不选 latest、不写 StateVersion。
- [ ] 题面表达式只在 RuntimeContext 解析一次，Method 不重建同名 Symbol。
- [ ] 测试验证 Symbol 可唯一解析到 canonical registry identity，并覆盖 `is` 为假的 artifact round-trip。
- [ ] 携带函数系数表达式的结构输入声明 `state_anchor/align_to_anchor`，并覆盖唯一投影与歧义拒绝。
- [ ] 合并/复用依据 runtime 等价，不依据字符串或输入形状。
- [ ] 所有可预期失败都有 typed diagnostic。
- [ ] configuration error 不会进入 Planner retry。
- [ ] failed checks 会阻止 commit 并完整回滚。
- [ ] SPEC 与实现同文件，生成 JSON 无漂移。
- [ ] Function 不搜索；Macro 搜索有显式模式、预算、隔离运行和歧义门禁。
- [ ] 动点等角色只保存 LLM authored 值和 runtime 验证后的 chosen 值，不由位置规则创造。
- [ ] method/compiler/transaction/retry/provenance 均有测试。
- [ ] 没有 problem id、具体答案、gold fixture 或点名特判。

## 17. Definition of Done

一个新 Method 只有在以下条件全部满足后才算完成：

```text
数学机制边界明确
typed input/output contract 完整
Python SPEC 与生成资产零漂移
所有预期失败均为 typed diagnostic
未知/配置错误 semantic retry 次数为 0
active output 缺失数为 0
failed transaction ghost write 为 0
runtime equivalence 与 StateVersion 语义通过
scope/source/provenance drift 为 0
Method、compiler、transaction、retry 测试全部通过
全量 Solver 回归通过
```

相关文档：

- `docs/method-solver-architecture.md`：DSL 从 Problem 到 SolverResult 的整体生产链。
- `docs/capability-authoring-guide.md`：Function、Macro、binding、return 和 closure 的公开能力规范。
- `docs/functional-planner-next-stage-roadmap.md`：当前 Functional Planner 演进路线。
- `docs/llm-sample-failure-review-guide.md`：真实sample中定位Method、Macro、runtime和retry问题的逐轮证据与图示规范。
