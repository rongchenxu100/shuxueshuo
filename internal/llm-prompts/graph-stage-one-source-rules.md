提取、复核、修复共用以下来源与字段约定。只表示题目，不执行数学推导；字段结构以 response_schema 和 math_expression_catalog 为准。

## 来源与完整性

- 只读本题题干及所属选项。相邻题目、印刷解析、答案、手写批注和勾选不是题设，不写入 original_text、public_content 或 root；无法确认所属关系时报告 uncertainty。
- 保留完整原式、全部条件和所求，包括函数调用、分支、参数限制、量词顺序、变量绑定、区间开闭及不等号严格性。根号与分式按横线的实际覆盖范围转录。无论某段或某参数是否看似与目标有关，都不能省略。选项按原标签、原顺序保留，不能推断正确项或选择模式。
- 不求解、不化简、不代入、不裁剪分支或区间，不把推导出的定义域、系数约束、单调性、最值或答案补成题设。结构识别、适用范围、条件推导、分支处理和结果验证由代码完成；不为适配已有能力改题，也不把能力缺口报成图片模糊。
- 共用定义与条件放父作用域；小问放有序 children，局部条件不泄漏到父节点或兄弟节点。同问多个所求保留平级 goals，不人为拆成小问；函数自变量、量词变量、求和索引及目标外层变量各自绑定。
- 编号不是数学依赖。当前可见小问条件齐全时按独立题保留，不要求补拍上一问。只有当前所求真正依赖的条件或明确引用的前问结果未出现时才报告缺失，不补造前问或答案。
- 只给函数关系而未给具体解析式时，没有解析式是这类题的正常题设；保留已知关系及目标，不补造函数规则。原文矛盾或无法辨认时记录实际问题，不自行修订题意。

## 数学表示与字段归属

- root 数学字符串用目录记法；乘法用 *，幂用 ^，根式用 sqrt，集合差用 ∖ 或 setminus。分段原式用 `piecewise(表达式,条件,表达式,条件,...)`，逐段保留原顺序、条件与端点归属。显示用的 original_text/public_content 保留原题排版，分段公式用标准 LaTeX cases。
- 对象命名放 definitions，条件放 facts；命名集合也须定义。嵌套量词保留顺序、各自范围和原引用，不转成最值比较或集合包含。题给某点取得最值的事实记 `max_{x}(f(x))=f(c)` 或 `min_{x}(f(x))=f(c)`；没有“唯一”不添加唯一性。
- y=原式需要函数引用时，可用不冲突的 f(x)=原式作为内部别名，原变量和原式不变；题面已有函数名则沿用。此规则也适用于 compare_functions 的 shared_functions 和各选项 functions。内部别名不写回原始或公开题面；量词中的 y 关系可引用其原式，不添加量词外的全局条件。
- 已知调用与所求调用分别记录。known_call 与 known_domain 必须对应同一句已知条件，known_domain 约束该调用的外层变量，known_range 只记它的题给完整值域。target_call 仍转录完整目标原式，不省略或约去分母，不改变根号覆盖范围。题面给所求表达式命名时，target_call 填完整右式；原命名可保留在转录中，不当成额外函数条件。
- 范围字段只转录题给范围：input_domain 是当前目标的额外输入限制；relation_domain 是恒等关系变量的范围；declared_domain 或 `Dom(f)=D` 是完整函数定义域；requested_domain 是要求恢复规则的范围。known_domain 不得填入推导范围。已知侧额外限域单独留在所属 facts，不能省略，也不能搬到目标的 input_domain。
- “定义域恰为”用 strength=exact；“在某范围上有定义／有意义”用 meaningful_only。保留有限集合、去点条件与开闭端点，不把局部范围当完整定义域。只有明确声明函数类型时才写 function_type=linear/quadratic，不从公式猜类型。
- 默认范围只采用目录约定：未另限变量的实数函数输入恒等关系按实数变量理解；“恒成立”未指明变量时取除待求量外唯一自由变量，未给范围取 ℝ；不能唯一确定时报告 uncertainty。这不授权反填计算所得的自然定义域。

## 目标字段

按原题所求选择目标，不把求值、求解集或证明改成求解析式。

| 原题所求 | 表示约定 |
| --- | --- |
| 解析式 | find_function_formula：function、variable、relation 保留原函数、变量及恒等式；同一未知函数的其他等式放 additional_relations。relation_variables 只记原题全称量化的变量，不把绑定变量当参数。 |
| 函数值或表达式的值 | find_value.expression 保留原调用。未知规则只有恒等关系时，使用含 function、variable、relation 的关系形式，其他条件字段与求解析式共用。 |
| 是否定值、有限和 | check_constant.expression；finite_sum.terms 按出现次序保留单列 expression 或附 index/lower/upper 的闭区间整数索引块，不去重、不补项。 |
| 具体函数定义域 | find_domain.object 引用原函数；已知完整定义域求参数用 match_domain.object/domain/symbol。 |
| 抽象调用的定义域或值域 | find_abstract_domain 或 find_abstract_range，保留 known_call、known_domain、strength、target_call 及题给 known_range。同题问两者时保留两个目标。 |
| 抽象调用有意义时的参数范围 | find_abstract_domain_parameter 保留完整 target_call、外层 variable、parameter；quantifier=exists 表示原题要求存在合法输入，不得把全称条件改成存在条件。 |
| 未知数或参数范围、解集 | find_range.symbol；原不等式或量词条件放所属 facts。只有通过未知函数关系表达所求时才使用关系形式的 function、variable、relation、expression 等字段。 |
| 具体函数值域及关于值域的提问 | find_range.object 引用函数，与 symbol 互斥。answer_request 按原文记录 extremum、expression 或 compare_set，普通求完整值域省略；命名最值及运算放 bindings/expression，不填结果。仅明确问上确界／下确界才用 supremum/infimum。 |
| 根据题给值域选择定义域端点 | select_range_domain 保留 object、domain_template、有序 parameters、expected_range、select_relation、selection_mode 和完整 options。未知端点不是已知定义域；选项 values 按参数顺序转录。 |
| 根据周期关系求另一输入区间的值域 | find_translation_range：原 function_relation、periodic_function/period/periodic_domain、known_domain/known_range、input_domain。周期条件归属原周期函数，不推导目标函数的平移关系，不重复记录同一条件。 |
| 单调区间或给定区间上的增减性证明 | find_monotonic_intervals 或 prove_monotonicity_on_interval，保留 expression、variable、direction 和题给 input_domain；domain_role 区分 declared 与 restriction。统问增减区间用 both。 |

函数输入恒等关系保留完整函数调用，不把复合输入改成裸自变量；求具体函数值域时可按原式放 definitions。求解析式、关系形式的求值或解集使用 relation/additional_relations，不重复当成具体函数定义。递推、周期等关系只转录，不先延拓或改写。

### 单调性来源字段

- `find_range.function_monotonicity` 表示原题给定的已知单调事实：function、domain、direction、strict；basis 只填 given。完整定义域明确给出时才加 function_domain；单调区间不等于完整定义域。
- `find_range.required_monotonicity` 表示待求参数必须满足的单调要求：expression、variable、direction、strict、input_domain，函数已命名时可填 function。可选 basis 保留要求的原始来源 kind/statement；差商或差积条件保留原式、量词及不同两点的限制，程序核验其方向。
- 两个字段互斥。都不允许填入模型求出的单调性，不添加复合输入必须落在某段的派生条件，也不据此选择求解方法。

### 比较与选择字段

compare_functions 的 mode=groups/shared_baseline/pair 分别表示选项内局部比较、共同基准比较、直接比较两函数。各 options 保留 id、label、text、functions 和 left/right 引用；公共基准只定义在 shared_functions。引用用 local:id 或 shared:id，共同基准模式每项各有一侧；左右互换不改变源函数身份。同名局部函数不跨选项合并，domain 只填原题显式范围。

select_relation 保留题目问相同还是不同；selection_mode 按明确文字记 single/multiple，否则 unspecified，不凭正确项数量反推单选或多选。直接比较 pair 使用一个条目、selection_mode=none、select_relation=null。选项残缺记 completeness=incomplete；未注明选择模式本身不表示缺题。original_text、public_content.choices 与 options 的内容、标签、顺序及选择模式须一致。

## 复核与修复权限

findings 必须指向 candidate 实际字段的 JSON Pointer，source_excerpt 写原图依据。分别读取 original_text、public_content 和 root，不把一个字段的内容误报到另一个字段；排版差异或允许的内部别名不是题意错误。修改多处时分别给出诊断。

wrong_expression，以及指向已有目标条目或其字段的 wrong_goal，只授权原位置修正。目标遗漏时，wrong_goal 应指向所在作用域（如 /root）或已有 goals 数组（如 /root/goals），仅授权在该作用域追加遗漏目标，不能改写已有目标或其他条件。条件遗漏时，missing_condition 应指向所在作用域或已有 facts/definitions 数组；目标内缺条件字段时可指向目标，仅补缺失字段。wrong_scope 仅授权在所指范围内整理分问层次、顺序和移动已有内容，不改数学内容。只有原图无依据的新增条目才用 unsupported_addition 授权删除；修正不授权删除，追加不授权替换。无法确定时用 uncertain，不给矛盾建议。修复后重新对照原图复核完整候选。
