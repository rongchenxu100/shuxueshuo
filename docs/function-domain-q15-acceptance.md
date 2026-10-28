# 函数定义域 Q15：实现范围与验收记录

Q15 已纳入函数专题，并完成专题与拍题双入口的本地验收。当前读题为一道定义域／值域含义单选。数学答案为 $[1,2)\cup(2,+\infty)$；不代表整个 T2 已支持。原始来源与机器证据保留在下列对应目录。

## 当前交付范围

- 二次根式知识 `square-root-expression#meaning` 已登记在 `junior-knowledge`，公共条目与依据引用可解析。
- T2 `type-function-domain` 已激活，入口为 M1 `method-domain-intersection`，调用 S3 `skill-expression-defined` 及已有 `skill-inequality-transform`。单路线直接选法，没有新增公共选法规则节点。
- 首批目标为明确的 `find_domain`，函数定义保留原 AST；仅接受经过结构检查的单变量、固定有理数系数、仿射根式／分母和固定题设区间。参数、建模、二次条件、根号内分式、绝对值及零次幂等尚未开放。
- `input_domain` 只记录题设范围；条件来自原式。S3 的 `condition_id`、`source_ref`、`ast_path`、`expression_ast`、`condition`、`kind`、`basis_refs` 贯穿求解和区域高亮。Q15 两个位置为 `[1,2]`、`[2]`，均来自 `/root/definitions/0`。
- 条件求解、交集和独立原式验证已接入共同 Stage3。验证器重新读取原表达式，对所有临界点及其间区间检查定义性与题设范围，不复用条件清单冒充独立验证。
- D1 引用需唯一定位原文函数定义，并比较未经化简的算术结构；不同 RHS、已约分替代式和未知 TeX 不生成伪公式引用，保留可靠目标行与诊断。
- 旧 Stage1 录制中，非 `find_domain` 目标可以缺少新增 `function_domain` 特征，原有必需特征继续校验；新目标缺该特征仍被拒绝。


`quantifiers`、`quadratic-inequality` 保留为 T2 求参与复杂条件扩题的知识关联，不作为 Q15 的强制依赖。

课包使用冻结的 `function-concepts-q15.evidence.json`。从该证据重建是稳定的；只新增无关图谱节点后重建，`bundleVersion` 与 native `contract_hash` 均保持不变，已做内存对照验证。当前契约同时包含执行来源身份，因此重新执行同一道题并替换 evidence 会产生新契约。正式发布后的同 ID 不允许更换该契约，发布器会拒绝；需要更换时沿用新 ID 规则，或另行设计语义 hash 升级，不能删除现有不可变发布门禁。

## 真实图片与调用证据

原图来源为用户上传的《函数的概念与性质小条（6）》第 15 题：

- [来源清单](../internal/senior-high/source-images/function-concepts-q15/manifest.json)记录原消息、图片尺寸、裁切坐标及 SHA-256。
- [原页](../internal/senior-high/source-images/function-concepts-q15/source-page.png)与[题面裁片](../internal/senior-high/source-images/function-concepts-q15/source-question.png)保留实际像素；裁片仅包含印刷题面，排除右侧手写答案，没有重绘或注入 OCR 答案。
- 最终提示词下的真实录制位于 [recorded-20261026](../server/tests/search/fixtures/function-domain/recorded-20261026/recording.json)。`result.json`、请求、响应和 ledger 均保存并校验哈希。
- 该次流程完成 **extract + review 两次语义调用、两次网络尝试，无修复调用**；`result.json.elapsed_seconds` 为 **17.432 秒**。单调用记录分别为 13.467 秒和 3.871 秒；它们不包括完整流程的其他开销。
- 提示词示例使用不同函数名、变量和系数的 `g(t)=sqrt(5-t)/(t+3)`，不嵌入本题原式；最终录制在此提示词下重新完成。
- [录制重验工具](../server/tests/search/function_domain_recording.py)重新验证候选与特征；[照片回放测试](../server/tests/solver/test_graph_stage_three_function_domain_recorded.py)进入真实识别、执行、持久化与教学链路。回放没有新增模型调用，不能将回放次数算作额外真实照片验收次数。

初版浏览器验收采用 `20261026-04` 的真实共享 PostgreSQL 执行，`run_id` 为 `1574d15a2f8a4b629f09fcaea298cedb`；[原导出证据](/private/tmp/sss-function-domain-browser-20261026-04/final-course-evidence.json)的来源身份与公开流一致，目标状态为 `solved`，结果为 $[1,2)\cup(2,+\infty)$。该文件是本地临时验收证据；仓库的[冻结证据](../site/data/graph-walk/function-concepts-q15.evidence.json)已基于同一次数学执行更新 D1 教学投影，`stream` 与 `provenance` 均保持不变。

主线程已在拍题浏览器中完成 **AI 7/7**，并肉眼检查截图：两个条件各有数轴，最终交集在 $1$ 处闭点、$2$ 处开点并向右延伸，端点理由与原式相符。此项证明 AI 回放与图示呈现通过，不等同于学生已完成练习，也不替代专题手机端或登录记录验收。

## 验收边界

本地覆盖专题登录作答与保存恢复、访客草稿、错答与等价答案、拍题 AI／自己做模式隔离及 iframe 窄屏。窄屏不等同于实体手机；多账号异步隔离另由自动化验证。当前课包及测试是复验入口，不沿用旧截图证明后续交互修改。
