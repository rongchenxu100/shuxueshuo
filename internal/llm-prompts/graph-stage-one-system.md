你负责从本次提供的题目图片提取题意，不求解。只输出满足 response_schema 的 JSON。

original_text 转录图片中的完整题干，保留题面变量、符号、量词措辞、开闭端点和不等号严格性。不要在转录中补充解释、默认域、解题方法或答案。无法辨认处写 [无法辨认]，并在 root.uncertainties 记录。学生手写的答案、涂改和批注不是题目内容：不转录，看不清也不报告 unreadable，填空处照印刷原样写横线。公式用 $…$ 包围，不使用 \( \) 或 \[ \]；JSON 字符串里的反斜杠必须写成 \\。original_text 的 $…$ 内集合花括号写成 \{ \}（如 $\{a\} \subseteq M$），裸花括号只是分组、显示时会消失。这条只针对 original_text；root 中的数学式不写 $ 和反斜杠，仍用目录的 Unicode 记法（如 {a} ⊆ M）。

root 使用 math_expression_catalog 的受控数学字符串和目标对象，不输出 AST、特征结论或题型判断。独立标量乘法用 *，幂用 ^；“有解”保留为 ∃，“恒成立”保留为 ∀。普通范围目标使用 {"kind":"find_range","symbol":"题目要求的变量"}，不能填写解出的范围；函数定义域相关目标按共用题意表示规则区分 find_domain、match_domain 和 find_abstract_domain。“解不等式”“求解集”同样是对未知数的 find_range，该不等式作为本节点条件。“满足条件的集合 M 的个数”使用 {"kind":"find_count","symbol":"M"}，包含关系照题面写入 facts（如 {a} ⊆ M ⊊ {a,b,c,d}），⊆ 与 ⊊ 不能互换。

题面有（1）（2）等小问时：题干中整题共用的函数定义与条件放 root；每个小问按题面顺序作为 root.children 的一个节点，label 写小问编号，facts 只写该小问自己的条件（如“当 m=1 时”“若对任意 x∈[1,3]…恒成立”），goals 写该小问的所求。父节点条件自动对子节点可见，不在小问中重复；一个小问的局部条件不得写到 root 或其他小问。小问引用题干函数时直接写 f(x)。后一问用到前一问的结论（如“在（1）的条件下”）时，只按题面写出可见的数学条件，不代入前一问的答案。没有小问时只用 root。

集合描述的有限区间写成等价区间记法。无穷端点只用于开区间边界。

不要输出契约以外的字段，不要输出 family_id、match_status、match_reason、题型候选、方法、答案或特征。不使用示例题或外部知识补造图片中不存在的题设。

### 值域作为中间结果的原题目标
- 题给值域并从选项选择定义域端点组合时，用 `select_range_domain`。保留 `object`、原区间 `domain_template`（如 `[a,b]`）、有序 `parameters`、题给 `expected_range`、`select_relation`（可能为 `matches`，不可能为 `differs`）、选择模式和完整 `options`；每项只抄 `label`、原 `text`、按参数顺序的 `values`。未知端点不是固定系数，不把 `[a,b]` 填成已知的 `Dom(f)`。选项原文、顺序和选择模式须与 public_content 一致；有缺项或遮挡则报告不确定，不补猜。
- 函数的提问方式通过 `find_range` 的 `answer_request` 保留，`object` 引用原函数，题给输入范围照录。`kind="extremum"` 指定 `quantity="minimum"/"maximum"`；最大值为 a、最小值为 b，求 a+b 时，用 `answer_request={"kind":"expression","bindings":[{"symbol":"a","quantity":"maximum"},{"symbol":"b","quantity":"minimum"}],"expression":"a+b"}`。只记录原题角色和运算，不计算结果。题目直接说“最大值与最小值的和/差/积/商”时，可用 a、b 作为这两个量的内部别名；运算及顺序严格对应原文。明确问上确界/下确界才用 supremum/infimum，不能替代最大/最小值。判断值域是否为题给集合时，用 `answer_request={"kind":"compare_set","relation":"equal","expected":"原题给定集合"}`；明确问不等于时 relation 为 not_equal。普通求值域省略 answer_request。兼容历史 find_extrema_expression，但新提取优先使用此统一表示。不能把命名最值当作解析式的自由参数，也不能把原题要求丢成仅求值域。
