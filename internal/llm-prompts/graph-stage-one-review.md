对照本次提供的原始题目图片，复核 candidate 的 root 数学题意与 original_text。不能只读转录，不能解题或判断题型。只输出 response_schema 指定的 JSON，顶层仅有 status 和 findings；不要返回 candidate、root、original_text 或任何修订后的题意。需要修改时，只在 findings 中指出问题，由后续修复阶段修改。

重点逐项检查 root：符号、量词及量词变量、定义域、严格性、所求变量、条件是否遗漏或擅自新增。有小问时还要检查作用域：每个小问是否是 root.children 中按题面顺序的独立节点，小问的局部条件是否只出现在该小问，整题共用条件是否放在 root。小问被压平或合并、局部条件泄漏到 root 或其他小问，或图像无法辨认时，不得 confirmed。

original_text 只用于展示。只有遗漏或改写了文字、公式时才报告 wrong_transcription（path=/original_text）；标点、空格、换行和公式排版差异不算错误。

发现问题时给出 candidate 中实际存在位置的 JSON Pointer、原图依据和具体原因；按共用题意表示规则判断允许的内部别名、目标表示和每类诊断的修复操作。confirmed 必须 findings=[]；有问题但无法确定修订方式时使用 uncertain。
