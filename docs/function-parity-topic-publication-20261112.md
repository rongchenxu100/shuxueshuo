# 函数奇偶性专题：统一发布与验收记录

日期：2026-11-12。基于 T6 提交 `1f4cdb60`，将已实现、已验收的 T1–T6 课程统一加入正式专题，并同步本地学习目录。

入口：`/topics/function-parity/`。本轮发布到本地网站 `http://127.0.0.1:8779/`，未提交、未 push，也未部署远程服务器。

## 发布范围

| 题型 | 页面数 | 原始作答目标数 | 题源 |
| --- | ---: | ---: | --- |
| T1 判断函数的奇偶性 | 2 | 2 | A01①、A01② |
| T2 根据奇偶性求参 | 7 | 7 | A17、C01–C06 |
| T3 根据奇偶性求解析式、对称求值 | 9 | 10 | A03、A04、A06–A09、A12、A13、A15 |
| T4 利用奇偶性解不等式 | 6 | 8 | A02、A05、A11、A18–A20 |
| T5 利用图像的对称性 | 2 | 3 | A10、A14 |
| T6 奇函数＋常数结论的应用 | 5 | 5 | A16、B01–B04 |
| 合计 | **31** | **35** | A01–A20、B01–B04、C01–C06 |

- 原专题已有 A01 的两个页面和 A17，本轮加入其余 28 页。
- A05、A09、A10、A11 保留原题的两问；A05、A11 不再只展示解析式子问。
- T6 题干不带“例 15”“变式”等教材标签。
- 教材知识层仍是“函数的奇偶性”“奇偶函数的图像特征”“函数图像的对称性”三个节点，详情页的可视化保留。定义域、绝对值、分式列为先修知识。
- T2–T6 暂存清单已登记发布状态，保留原 `pending` 条目用于追溯题源与课程输入。

课程从已有 authored record 统一重建。本轮没有重新调用 OCR 或模型，不把这次构建计为新照片验收；真实照片结果见各 T1–T6 验收记录。

## 统一构建中修复的问题

T6 的显式表达式识别把嵌套调用 `f(f(1))` 的标量解析失败当成自身可处理的题目，导致既有单调性 B09 的求值目标被错误接管。现在嵌套调用保留给逐层代入求值路线，后续不等式目标仍按原路线处理。

新增回归覆盖 `f(f(1))`、`f(1+f(1))`、分段函数的嵌套调用，以及 B09 的两个完整目标。没有修改 prompt。

## 发布兼容性

统一刷新了 126 门公开图谱课程，再编译课包、专题目录和公共知识图谱。最终三个构建器的 `--check` 均通过。

本地日常学习库有六道单调性课程的旧教学契约，不能用相同 ID 覆盖。为它们分配新版本，页面地址保持不变：

| 原课程 ID | 新课程 ID |
| --- | --- |
| function-monotonicity-a16-v2 | function-monotonicity-a16-v3 |
| function-monotonicity-a07-v2 | function-monotonicity-a07-v3 |
| function-monotonicity-a18-v2 | function-monotonicity-a18-v3 |
| function-monotonicity-b16-v2 | function-monotonicity-b16-v3 |
| function-monotonicity-b11-v2 | function-monotonicity-b11-v3 |
| function-monotonicity-b10-v2 | function-monotonicity-b10-v3 |

新版本从同一 authored record 生成，旧数据库课程和历史课包保留；未修改数据库摘要绕过契约检查。新来源在 `internal/senior-high/authored-courses/function-monotonicity-publication-20261112/`。

本地 `publish-learning` 成功，`verify-release --site-version site/knowledge/teaching/version.json` 返回 `site: match`。发布版本：

`651ce5e821ddd01ea284a8da733b3d757a16a21841cdc4a6c5a41bd82b92c111`

全站学习目录包含 170 个知识图谱节点、165 道练习、185 条方法路线、1518 个步骤；其中奇偶性专题为上述 31 页。

## 验收结果

| 检查 | 结果 |
| --- | --- |
| T6 路由、泛化与相关适配回归 | 126 项通过 |
| 专题覆盖、前端判题回放、恢复、课程身份、知识导出与专题页面 | 95 项通过 |
| 独立 PostgreSQL 发布与合同检查 | 4 项通过；包含 31 页全部步骤的后端评分、完成保存及中途恢复 |
| 实际 HTTP 页面及课包 | 31 页全部返回 200，包含多问题页 |
| 实际课程内容 API | 31 个 `page_contract_hash` 与所加载课包一致，目录版本与静态版本一致 |
| 浏览器抽查 | 目录显示“6 个题型 · 31 道题”；A05 两问原题、T6 B04 页面正常进入读题步骤，无版本过期提示 |
| Ruff 与差异空白检查 | 通过 |

保存测试在独立数据库的新 schema 内完成并清理测试数据；未用日常学生账号提交测试答案。日常库发布前后计数完全一致：

| 历史记录 | 发布前 | 发布后 |
| --- | ---: | ---: |
| 练习尝试 | 28 | 28 |
| 作答事件 | 566 | 566 |
| 步骤结果 | 177 | 177 |
| 掌握标记 | 23 | 23 |
| 知识练习尝试 | 1 | 1 |
| 知识练习答案 | 5 | 5 |

机器可读摘要及逐页合同核对见 [validation/function-parity-publication-20261112/summary.json](validation/function-parity-publication-20261112/summary.json)。本轮没有改动用户已有的 `.gitignore` 修改。
