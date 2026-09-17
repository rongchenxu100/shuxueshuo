# 新旧数学对象树对照

本报告是离线语义审计。对象或表达式一致不能代替原图正确性验证，也不表示新输入已经接通 Solver 运行时。

|题目|旧/新命名对象|规范化对象与作用域|有界条件/目标等价|限定项差异|结论|
|---|---|---|---|---|---|
|[tj-2026-nankai-yimo-25](tj-2026-nankai-yimo-25/README.md)|12/12|一致|未证明|1 组|needs_review|
|[tj-2026-heping-ermo-25](tj-2026-heping-ermo-25/README.md)|13/13|一致|未证明|1 组|needs_review|
|[tj-2026-heping-yimo-25](tj-2026-heping-yimo-25/README.md)|12/12|一致|未证明|1 组|needs_review|
|[tj-2026-hexi-yimo-25](tj-2026-hexi-yimo-25/README.md)|12/12|一致|已证明|1 组|needs_review|
|[tj-2026-xiqing-yimo-25](tj-2026-xiqing-yimo-25/README.md)|10/9|一致|未证明|1 组|needs_review|

## 如何阅读

先检查对象和作用域，再检查条件/目标及限定项。有界语义比较会规范化部分表示差异；限定项单独保留，避免最值变量、at、答案参数在规范化中丢失。`needs_review` 不等于数学错误，也不允许视作迁移通过。

现有运行时对象包含匿名几何对象、表达式、答案对象和状态槽，数量不能直接与新 JSON 的命名对象数量比较。两份旧运行时快照保留为后续生产绑定验收的基线。

源码稳定：`True`；真实 LLM 调用：0；新输入运行时绑定：未实现。
