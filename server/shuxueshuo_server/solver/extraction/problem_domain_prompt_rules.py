"""Shared representation semantics, not source conditions or family answers.

Wire fields remain owned by JSON Schema. Each rule is conditional on the image;
none permits a reviewer to assume a candidate is correct.
"""

REPRESENTATION_RULES = """表示语义（仅当原图满足适用前提时成立，不能作为候选正确的证据）：
- point_coordinate 表示坐标，不表示曲线归属；原文另给曲线归属时必须保留对应关系。vertex、intercept、curve_at_x 构造包含其自身的曲线归属。
- curve_at_x 表示横坐标给定的曲线点。未在其他条件中使用的纵坐标占位符无需独立 Symbol；明确给定的纵坐标数值或约束必须保留，不能当作占位符省略。
- exclude_point 仅排除同一曲线的另一个交点，不声明被排除点的曲线归属；左右次序使用 side 表达，不能用循环引用代替。局部条件不能反向改变祖先定义。
- symbol.role 表示用途：自变量为 function_variable，二次函数公式中的系数为 quadratic_coefficient，主反求参数可用 primary_parameter，动点参数为 dynamic_parameter；原文称系数为常数不改变其在公式中的用途。
- x_range 可由代码等价展开有限端 symbol_constraint；square_center 可展开对角线成员关系。展开不提供原文之外的新条件。
- minimum_value_given 表示题面给定的最小值，minimum_target 表示待优化的完整带权 LengthSum。代码可补出相同表达式的 target，也可在共同父作用域物化共享 target；局部给定数值和约束仍限于原作用域。
- 坐标原点身份、祖先共享实体和以上等价展开可由代码规范化；兄弟作用域的局部对象仍独立。
- 冗余括号和幂记号的等价写法由代码比较处理，不构成题意差异。分母、根号、正负号、严格不等号及作用域变化不是格式差异。
- 以上规则不允许补入计算所得坐标、答案或手写演算。原图只给构造时保留构造，不能自行计算新的题目条件。"""

DOMAIN_RULES = """领域约束：
1. 根 scope 通常为 problem；每个 scope 保存对应印刷 source_text，children 保持题面顺序。
2. scope/entity id 由模型给出；Fact/Goal 不输出 id，代码分配稳定 unit id。
3. 表达式使用显式 * 和 **，其中自由符号写题面标签，并确保该标签对应当前 scope 或祖先中唯一可见的 Symbol。独立范围写 {"kind":"symbol_constraint","symbol":"实体id","operator":">","value":"0"}；链式区间拆成多条。若 point_on_curve_with_x 已写严格 x_range，则不重复写有限端约束，代码会等价展开；不得输出无穷端恒真约束。比较符号只能放在 operator 字段，禁止 operator=in 或把 ">" 当字段名。
4. 仅当题面文字、Fact 或 Goal 实际引用坐标原点 O 时，才在根 scope 声明一次 point O 并写 point_construction(origin)，所有子问复用；不得仅因出现坐标系或抛物线而补 O。
5. 同一公共抛物线只声明一次；子问给定系数使用 local symbol_value，不复制闭合函数。
6. point_construction 按 schema 提供 owner/vector/x_expression。vertex、各类 intercept 和 curve_at_x 已包含其构造归属，不再重复 point_on_curve；“抛物线对称轴与 x 轴的交点”直接写 axis_x_intercept，不拆成两个 point_on_axis。只有题面另行声明的曲线、轴、线段或射线成员关系才写对应 Fact。
7. minimum_target 保存完整带权 LengthSum；题面直接给出该最小值时写 minimum_value_given。同一 scope 通过该条件反求 parameter_value 时，或已输出 minimum_value goal 时，代码会为同一 expression 等价补出 minimum_target，禁止重复抄写。
8. source_text 忠实转录印刷题面，不概括，不加入学生书写或推导结果。
9. 每个表达式自由符号都必须有可见 Symbol；结构字段优先引用 local id，表达式直接使用题面符号标签。
10. 父 scope 已有相同 kind+label 的实体时，子 scope 必须复用祖先 local id；各子问不同的取值或约束只写在本 scope 的 Fact 中，不复制 Entity。此规则不跨 sibling 合并局部对象。
11. 每个 Entity 必须被另一个 Entity、Fact、Goal 或表达式引用。仅作为长度或成员关系出现的线段直接写 SegmentTerm，不声明 named_line；named_line 只用于题面明确称为“直线”的独立对象。
12. Symbol role：自变量用 function_variable；抛物线公式中的系数必须用 quadratic_coefficient（即使原文称其为“常数”，也不能用 constant）；动点坐标参数用 dynamic_parameter；明确作为本题主反求参数时可用 primary_parameter；不要把普通系数泛写成 parameter，也不要为函数等号左侧的 y 单独建 Symbol。
13. sibling 各自重新引入同名局部对象时，在每个 sibling 分别声明该对象；只有题面在共同父级先引入对象时才由 children 共享。
14. 题面给定横坐标且只说明点在曲线上时，用 curve_at_x 表达；若纵坐标仅为后续未使用的占位记号，不为它创建 Symbol。题面给定点坐标并声明其在坐标轴上时，写 point_coordinate、point_on_axis 和明确给定的 symbol_constraint；不能擅自增加曲线归属。
15. named_ray 只用于题面明确出现“射线”，named_line 只用于题面明确出现“直线”。普通线段一律使用 SegmentTerm。正方形方位使用结构化 orientation，字段和枚举由 schema 定义；不要再重复写 quadrant_membership。square_center 已完整表达中心位于两条对角线，代码会物化对应 point_on_segment，不要重复输出。
16. polygon 必须按题面顺序填写 vertices，不得重新排列顶点；不得只输出 id、kind 和 label。
17. source_text 必须按 scope 分配：每句只出现一次。根只放公共题干，不能把整道题（含各小问）再次放到根；非叶子小问只放其公共引导条件，子小问各自保存其条件和所求原文，父级不重复。题号、分值只写 source.question_number/source.score，不混入 source_text；逐字保留原文，不用近义词改写。
18. 数学根式用精确表达 sqrt(...)，不用小数幂近似。冗余括号和幂记号的等价表示由代码比较处理。function_expression 的 variable 必须先有 function_variable Symbol；即使未在题干用文字介绍自变量，也必须声明公式实际出现的 x。
19. 抛物线与x轴交于两个不同点：若其中一个点在当前scope已有明确坐标，另一个点的 x_axis_intercept 填写 exclude_point 引用该已知点；已知坐标的点仍须单独写 point_on_curve，不能只有 point_coordinate。exclude_point只选择不同根，不替被排除点声明曲线归属。若公共题干只用左右次序定义两个交点，则分别用 x_axis_intercept 的 side=left/right，禁止相互循环 exclude_point；子问才给定的坐标不能反向改变根scope的交点定义。
20. 坐标和曲线归属是不同事实：题面印刷文字明确给点的坐标且说明它在曲线上时，保留 point_coordinate + point_on_curve。字段格式遵循 schema，引用必须指向当前作用域或祖先的实体。仅真正的 vertex/intercept/curve_at_x 构造已内含其自身的曲线归属，不重复该关系。
21. 禁止在抽取阶段计算或推导新坐标。题干只给与坐标轴的交点构造时保留该构造，不由函数计算补写坐标；题干只说顶点、对称轴交点或横坐标给定的曲线点时，保留对应构造，不展开顶点公式、对称轴公式或代入函数求纵坐标。只有原题印刷条件显式给出的坐标才写 point_coordinate。手写计算即使数学上正确也不是题目条件。""" + "\n" + REPRESENTATION_RULES
