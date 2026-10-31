对照本次提供的原始题目图片，复核 candidate 的 root 数学题意与 original_text。不能只读转录，不能解题或判断题型。只输出 response_schema 指定的 JSON，顶层仅有 status 和 findings；不要返回 candidate、root、original_text 或任何修订后的题意。需要修改时，只在 findings 中指出问题，由后续修复阶段修改。

重点逐项检查 root：符号、量词及量词变量、定义域、严格性、所求变量、条件是否遗漏或擅自新增。有小问时还要检查作用域：每个小问是否是 root.children 中按题面顺序的独立节点，小问的局部条件是否只出现在该小问，整题共用条件是否放在 root。小问被压平或合并、局部条件泄漏到 root 或其他小问，或图像无法辨认时，不得 confirmed。

original_text 只用于展示。只有遗漏或改写了文字、公式时才报告 wrong_transcription（path=/original_text）；标点、空格、换行和公式排版差异不算错误。

发现问题时给出 candidate 中实际存在位置的 JSON Pointer、原图依据和具体原因；按共用题意表示规则判断允许的内部别名、目标表示和每类诊断的修复操作。confirmed 必须 findings=[]；有问题但无法确定修订方式时使用 uncertain。

### 值域作为中间结果的原题目标
- 题给值域并从选项选择定义域端点组合时，用 `select_range_domain`。保留 `object`、原区间 `domain_template`（如 `[a,b]`）、有序 `parameters`、题给 `expected_range`、`select_relation`（可能为 `matches`，不可能为 `differs`）、选择模式和完整 `options`；每项只抄 `label`、原 `text`、按参数顺序的 `values`。未知端点不是固定系数，不把 `[a,b]` 填成已知的 `Dom(f)`。选项原文、顺序和选择模式须与 public_content 一致；有缺项或遮挡则报告不确定，不补猜。
- 函数的提问方式通过 `find_range` 的 `answer_request` 保留，`object` 引用原函数，题给输入范围照录。`kind="extremum"` 指定 `quantity="minimum"/"maximum"`；最大值为 a、最小值为 b，求 a+b 时，用 `answer_request={"kind":"expression","bindings":[{"symbol":"a","quantity":"maximum"},{"symbol":"b","quantity":"minimum"}],"expression":"a+b"}`。只记录原题角色和运算，不计算结果。题目直接说“最大值与最小值的和/差/积/商”时，可用 a、b 作为这两个量的内部别名；运算及顺序严格对应原文。明确问上确界/下确界才用 supremum/infimum，不能替代最大/最小值。判断值域是否为题给集合时，用 `answer_request={"kind":"compare_set","relation":"equal","expected":"原题给定集合"}`；明确问不等于时 relation 为 not_equal。普通求值域省略 answer_request。兼容历史 find_extrema_expression，但新提取优先使用此统一表示。不能把命名最值当作解析式的自由参数，也不能把原题要求丢成仅求值域。
