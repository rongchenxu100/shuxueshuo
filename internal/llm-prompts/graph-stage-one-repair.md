根据原始题目图片、当前候选和程序或原图复核诊断修复候选。只输出满足 response_schema 的完整 JSON；不得根据金标、解法、特征差异或预期答案修订。

遵守给定的授权修改范围与共用题意表示规则，保留没有错误的题意。root 数学字符串依然遵循 math_expression_catalog。repair_feedback 表示上一版修复未被采用；继续以 base_candidate 为修复基础，不重复执行被拒绝的越权删除。无法确认的内容保留 uncertainty，不能求解后倒推题设。
