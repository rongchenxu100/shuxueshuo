# 函数定义域 Q15：实现范围与验收记录

更新：2026-10-26。**Q15 代表题的专题与拍题双入口本地验收已完成，成为函数专题唯一上架题；最新 D1 已简化为一道定义域／值域含义单选。** 初版课包已核验专题登录用户自主 7/7、错误反馈、等价答案、保存与恢复、访客隔离和草稿、拍题 AI／学生模式隔离及窄屏显示；本轮新 D1 的浏览器、照片 API 与学习记录复核见文末。窄屏采用 375×700 iframe，并非真手机设备；第二账号及重新登录未作 UI 实测，账号异步队列隔离由自动化补充。本批未提交，未部署生产。

正式公共题目 ID：`function-concepts-q15`。题目为求 $f(x)=\frac{\sqrt{x-1}}{x-2}$ 的定义域，结果为 $[1,2)\cup(2,+\infty)$。设计与扩题门禁见 [T2 设计](function-domain-problem-type-design.md)，章节进度见[函数专题计划](function-concepts-topic-and-photo-learning-plan.md)。

## 当前交付范围

- 二次根式知识 `square-root-expression#meaning` 已登记在 `junior-knowledge`，公共条目与依据引用可解析。
- T2 `type-function-domain` 已激活，入口为 M1 `method-domain-intersection`，调用 S3 `skill-expression-defined` 及已有 `skill-inequality-transform`。单路线直接选法，没有新增公共选法规则节点。
- 首批目标为明确的 `find_domain`，函数定义保留原 AST；仅接受经过结构检查的单变量、固定有理数系数、仿射根式／分母和固定题设区间。参数、建模、二次条件、根号内分式、绝对值及零次幂等尚未开放。
- `input_domain` 只记录题设范围；条件来自原式。S3 的 `condition_id`、`source_ref`、`ast_path`、`expression_ast`、`condition`、`kind`、`basis_refs` 贯穿求解和区域高亮。Q15 两个位置为 `[1,2]`、`[2]`，均来自 `/root/definitions/0`。
- 条件求解、交集和独立原式验证已接入共同 Stage3。验证器重新读取原表达式，对所有临界点及其间区间检查定义性与题设范围，不复用条件清单冒充独立验证。
- D1 引用需唯一定位原文函数定义，并比较未经化简的算术结构；不同 RHS、已约分替代式和未知 TeX 不生成伪公式引用，保留可靠目标行与诊断。
- 旧 Stage1 录制中，非 `find_domain` 目标可以缺少新增 `function_domain` 特征，原有必需特征继续校验；新目标缺该特征仍被拒绝。

P0 历史截面为 89 节点、零题专题。本批增加一个知识、一个方法、一个技能，当前图谱为 **92 节点、285 条边**；方法总数 15，技能 21，知识 26。当前公共内容合计 **40 道题、51 条路线、266 步**。函数专题已上架且只收录 Q15，其他 29 道大题及未完成目标不提前展示或标成已支持。

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

## 已执行的验证

以下是本次各次定向运行的结果，套件有重叠，**不相加为一个独立测试总数**。

| 验证 | 结果 | 覆盖与证据 |
| --- | --- | --- |
| Day-0 根式依据 | 通过 | 图谱校验、内存公共导出、`meaning` 锚点、初中集合归属；公共图谱测试继续覆盖 |
| Day-0 `!=` 正式能力探针 | 通过 | `test_day_zero_real_shared_not_equal_capability` 经 `REGISTRY["solve_conditions"]` 求 $x-2\ne0$，并与 $x-1\ge0$ 合并为 Q15 精确集合 |
| 识别与兼容回归 | 364 passed | 新定义域识别，既有 Stage1 features/contracts 与 Stage2 recognition/fragments/input-values/workflow；旧录制保持可用 |
| 精确 D1 与真实录制读题 | 37 passed | 结构及语义反例、原式引用、真实照片重验与共同 D1/D2 |
| 记法与既有片段回归 | 230 passed | math notation、scope、semantic equivalence、原 Stage2 fragments；新目标枚举已同步 |
| 公共图谱与生命周期 | 30 passed | 92 节点、集合、状态、条目引用、详情／平面／3D、输出一致性与受控清理 |
| 主线程搜索／身份／实际照片链路回归 | 92 passed | 下方命令；隔离 PostgreSQL 环境，含旧搜索课程、公共提取与身份回归 |
| 主线程前端搜索回归 | 225 passed | `search-notation.test.mjs`、`search-flow.test.mjs`；不替代真实浏览器检查 |
| 执行链最终定向回归 | 34 passed | 执行链实现者报告的最终定义域定向结果；与下方独立复核及此前测试有重叠 |
| 执行链既有功能回归 | 396 passed | 执行链实现者报告的旧链路回归，验证新增定义域能力未破坏原有执行路径 |
| 数轴与真实导出独立复核 | 35 passed | `test_graph_stage_three_course_export.py`、`test_graph_stage_three_function_domain.py`；隔离 PostgreSQL，14.97 秒；包含来源、共用坐标、端点、真实导出及损坏证据拒绝 |
| 数轴与专题前端独立复核 | 37 passed | `graph-walk-ui.test.mjs`、`graph-walk-topic.test.mjs`；包含答前不泄露交集、AI 完成隔离及原生练习导出 |
| 最终照片回放与 API | 5 passed | 主线程最终运行，22.83 秒；正式照片录制回放与定义域 API |
| 登录与学习记录回归 | 68 passed, 1 skipped | 跳过 `test_live_tutor_persists_original_dialogue`，原因是未开启 `RUN_LLM_INTEGRATION`；该实时导师测试与新增定义域能力无关，不记作通过 |
| 最终专题与图谱前端回归 | 174 passed | 专题实现者最终运行；包含独立条件／解集不误连为推导箭头，以及近邻端点的图形降级回归 |
| 拍题首页能力说明回归 | 208 passed | `search-flow.test.mjs`；首页已补定义域支持范围和 Q15 示例链接，冻结课包不变 |
| 最终构建与产物一致性 | 通过 | 专题实现者完成全部相关构建器的 `--check`，冻结课包、专题与公共导出一致 |
| 独立边界探针 | 7 passed | 临时测试文件复用正式 shared runner 和隔离 PostgreSQL schema，覆盖常数合法根式、无条件表达式、重复来源、空集、单点、互斥条件、冗余分母；22.15 秒 |

主要复核命令（Python 命令在 `server/` 执行）：

```sh
uv run pytest -q tests/solver/test_graph_function_domain_recognition.py tests/solver/test_graph_stage_one_features.py tests/solver/test_graph_stage_two_recognition.py tests/solver/test_graph_stage_two_fragments.py tests/solver/test_graph_stage_one_contracts.py tests/solver/test_graph_stage_two_input_values.py tests/solver/test_graph_stage_two_workflow.py
uv run pytest -q tests/solver/test_graph_function_domain_recognition.py tests/search/test_function_domain_lesson.py
uv run pytest -q tests/solver/test_math_notation.py tests/solver/test_math_notation_state_scope.py tests/solver/test_semantic_equivalence.py tests/solver/test_graph_stage_two_fragments.py
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-function-domain-20261026 PRODUCT_TEST_INSTANCE=function-domain uv run pytest -q tests/solver/test_graph_stage_three_function_domain_recorded.py tests/search/test_function_domain_api.py tests/search/test_function_domain_lesson.py tests/search/test_lesson.py tests/search/test_public_extraction.py tests/search/test_identity.py
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-function-domain-20261026 PRODUCT_TEST_INSTANCE=function-domain uv run pytest -q tests/solver/test_graph_stage_three_course_export.py tests/solver/test_graph_stage_three_function_domain.py
```

仓库根目录的前端与图谱命令：

```sh
node --test tools/tests/public-knowledge-graph.test.mjs tools/tests/public-knowledge-lifecycle.test.mjs
node --test tools/tests/search-notation.test.mjs tools/tests/search-flow.test.mjs
node --test tools/tests/graph-walk-ui.test.mjs tools/tests/graph-walk-topic.test.mjs
node --test tools/tests/graph-stage-three-math-dom.test.mjs tools/tests/graph-walk-topic.test.mjs tools/tests/graph-walk-stream-state.test.mjs tools/tests/graph-walk-ui.test.mjs tools/tests/practice-records.test.mjs tools/tests/public-knowledge-export.test.mjs tools/tests/topic-overviews.test.mjs
node tools/build-public-knowledge-graph.mjs --check
node tools/build-topic-overviews.mjs --check
node tools/build-graph-walk-topic.mjs --check
node tools/export-public-knowledge.mjs --check
```

独立数学探针另外检查：将七例的正确结果替换为错误集合，原式验证器均返回 `math_failed`；将参数、二次根式、绝对值或零次幂的特征伪改为支持并显式指定 T2，四例均返回 `no_applicable_method`。重复根式的来源路径不同；冗余分母的原始条件与位置保留，即使最终集合没有额外缩小。

恒零分母和常量负数开平方目前会在公开候选的语义校验中被阻断，例如 `1/0`、`1/(x-x)`、`sqrt(-1)`、`1/sqrt(0)`。这些输入没有被记录为公开拍题“已求得空集”。已通过的空集案例来自条件冲突或题设区间；内部能力的额外健壮性不能替代公开准入验收。

## 最终课包与浏览器验收

已冻结的交付产物为：[课程来源](../site/data/graph-walk/function-concepts-q15.source.json)、[教学课包](../site/data/graph-walk/function-concepts-q15.json)、[AI 回放](../site/data/graph-walk/function-concepts-q15.replay.json)、[专题题页](../site/topics/function-concepts/q15/index.html)和[公共教学投影](../site/knowledge/teaching/problems/function-concepts-q15.json)。[专题配置](../site/data/knowledge-next/topics/function-concepts.json)的定义域分组只有 Q15，其余四组没有练习。

当前冻结版本记录（已包含 D1 单选调整）：

- 课包 `bundleVersion`：`["stream","fe3795045c001552cae4ca167e362a97942a8a16784bb46cb228019a69222667","cfa13e148c3bd6527068232b975c13bf85188ccca370813748f433feda215ce3","1574d15a2f8a4b629f09fcaea298cedb","/root/goals/0"]`。
- native `contract_hash`：`90ac818ed6f449351e329fa4d23060c876789badb7c30e364687d5483cf14094`。
- 公共 `content_version`：`796d05236b54cba66cd9f7ad0fc09ded67959e4cef0af9fa865411bd13fa9f07`；计数见[版本清单](../site/knowledge/teaching/version.json)。

以下保留初版课包的浏览器覆盖记录；本轮 D1 调整的复核范围在文末单列，不将旧截图作为新单选页面的证据。

| 门禁 | 当前记录 | 实际覆盖范围 |
| --- | --- | --- |
| Q15 唯一专题题与最终课包 | 已冻结、已上架 | 上述产物与版本一致，构建 `--check` 通过；专题只有 Q15 |
| 拍题入口真实执行与 AI 回放 | 已通过 | 最终 `20261026-04` 运行完成 AI 7/7；run 与导出证据见上文，不计为学生完成 |
| 拍题首页能力说明与试做入口 | 已实查通过 | 首页显示具体函数定义域（平方根、分式）的支持范围；浏览器已点击 Q15 试做链接并打开题页，最终 `search-flow` 208/208 通过 |
| 拍题入口 Q15 数轴与端点 | 已目检通过 | 两条条件数轴、最终 $1$ 闭点与 $2$ 开点、向右箭头、端点理由均正确 |
| 专题登录用户自主作答 | 已实查通过 | 自主完成 7/7；漏选分母得到 wrong 反馈；最终集合描述式的等价选项通过；每步显示已保存 |
| 登录练习刷新恢复 | 已实查通过 | 刷新后明确提示“已恢复服务端确认的练习进度”，显示已完成及 7 steps |
| 退出账号后的访客隔离 | 已实查通过 | 退出测试账号后回到 guest 的 D1、0 steps、0 selected，不沿用登录用户进度 |
| 访客未提交草稿 | 已实查通过 | guest 选择 1 项但未提交，刷新后仍保留该 1 项选择 |
| 拍题 AI 与学生模式隔离 | 已实查通过 | AI 回放 7/7 后切换“自己做”，回到 D1、0 steps，不将回放冒充学生完成 |
| 375×700 窄屏布局 | 已实查通过 | iframe 内完成 AI 7/7，步骤抽屉可滚动；条件数轴、最终 $1$ 闭点／$2$ 开点和端点理由均目检正确；不声称真手机设备验收 |
| 账号异步队列隔离 | 自动化通过 | 由学习记录回归补充；未声称第二账号或重新登录 UI 实测 |
| 近邻端点的显示降级 | 已修复并通过前端回归 | $\sqrt{x-1}/(100x-101)$ 的近邻端点不再绘制重叠标记；共享刻度或端点间距不足 16 px 时保留真实集合式并说明降级，不改变数学证据或冻结契约 |
| 独立条件与解集的展示 | 已修复并通过前端回归 | `domain_conditions`、`domain_solutions` 的并列项目改为独立行，不再用通用横向箭头误示项目之间存在蕴含关系 |

本地截图：[专题完成](../internal/review-analysis/function-domain-q15-20261026/topic-complete.png)、[专题入口](../internal/review-analysis/function-domain-q15-20261026/topic-index.png)、[窄屏端点](../internal/review-analysis/function-domain-q15-20261026/mobile-endpoints.png)。这些截图位于 ignored 的本地审查目录，链接用于本地复核，不承诺随 Git 提交保留。

验收环境已收尾：隔离测试服务 `8844` 和测试 PostgreSQL 已正常停止，静态预览 `8843` 保留。用户原专题标签页已刷新并显示 1 题，另保留 Q15 普通题页标签；这些本地预览状态不代表生产部署。

第 15 题现记为**代表题双入口本地验收完成**，不代表整个 T2 或所有函数题已支持。下一道扩题为第 1 题 $y=(x+4)^0\frac{x^2-1}{x-1}$：零次幂依据、$x\ne-4$、约分前 $x\ne1$、对应交互与真实拍题仍待实施；不把它算入本次完成范围。

## 2026-10-26 审查补充

- 直连选法显式检查 `admission`；缺失或未知值抛出 `selection.unsupported_direct_admission`，不能因未来 schema 扩展而误用函数定义域准入。当前已声明的入口仍重新检查原候选。
- 临界多项式按原式来源和实际 AST 位置去重；`1/sqrt(...)` 的同一多项式只出一行，`condition_sources` 保留分母非零与根内非负两种要求。不同原式位置即使表达式相同，也不合并其证据。
- 数轴先绑定条件、显式题设范围和最终结果，再生成标签；条件与解集条数不符直接拒绝。无约束的默认行必须经检查确为实数集，不再用硬编码标签掩盖错位数据。
- `endpointChecksHTML` 继续严格拒绝未验证端点。运行时仅捕获已知端点校验错误，整张端点卡显示“暂不可用”，不泄漏任何该组端点结论；其他独立卡片继续显示，未知程序异常仍抛出。

选法回归 **77 passed**，定义域及本次证据／标签回归 **43 passed**，前端 `search-flow`、`graph-walk-ui`、`graph-walk-topic` 合计 **251 passed**。前端缓存版本同步更新为 `20261026-domain-review`。仅重建题页 HTML；冻结 evidence、bundle、replay 的 SHA-256、课程版本与 native 合同哈希均未改变，课包构建 `--check` 为 `changed: 0`，后续数学运行使用更新后的源码。Ruff 与 `git diff --check` 通过。

本轮 Python 命令在 `server/` 执行，并使用前文的隔离 `PRODUCT_TEST_DATA_DIR` 与 `PRODUCT_TEST_INSTANCE`：

```sh
uv run pytest -q tests/solver/test_graph_stage_three_selection.py
uv run pytest -q tests/solver/test_graph_stage_three_domain_review.py tests/solver/test_graph_stage_three_function_domain.py
```

## 2026-10-26 读题交互简化

D1 共用单选“题目要求‘定义域’，也就是要确定什么？”，选项为“自变量 $x$ 的取值范围”和“函数值 $f(x)$ 的取值范围”。原公式保留在题头，取消公式辨认和“只找一个能代入的 $x$”选项。若题设另给输入范围，在问题前只读展示并在答对总结中提醒同时满足，不增加作答槽。

选择函数值范围时解释它是值域；答对后显示“定义域是自变量的取值集合。本题需要找出所有使原解析式有意义的 $x$。”，完成回顾及下一步承接使用同一说明。公式的原文引用、分式／二次根式知识线索仍保留。定义域独立结构匹配的诊断控制是否生成练习，通用多项式读取器对合法 `\frac` 的提示不再误拦；未知公式命令、原式不匹配和多处定义仍拒绝生成练习。

本轮从原 `20261026-04` 执行记录离线重导出，只更新教学投影；与修改前备份逐项比较，`stream` 与 `provenance` 深度相等，没有新增模型调用。四个数学交互及总计 7 步保持不变。教学交互改变使 `bundleVersion`、native 合同和公共内容版本更新，旧 checklist 数组不能作为新单选答案；服务端不可变发布门禁未修改。新合同只在新的隔离测试实例发布，未更新生产。

| 本轮复核 | 结果 | 覆盖 |
| --- | --- | --- |
| 后端读题与兼容 | 176 passed, 2 deselected | 定义域及原有 lesson/negation；变量名、三种显式范围、原文绑定诊断、知识线索、标量回放。两项旧 API 测试在最终定向命令中排除，不计入通过数 |
| 照片 API、离线导出、原生学习记录 | 3 passed | 真实照片录制经正式 API 获得新 D1 并完成求解；导出来源与破损证据；新合同登录作答 7/7、重试幂等、越步拒绝、恢复和练习标记 |
| 前端与公共产物 | 390 passed | 错误反馈、不提前泄漏解释、完成回顾、AI 标量回放、原生单选记录及实际课包合同；旧数组拒绝 |
| 浏览器 | 通过 | 普通题页显示原式和两个选项；预览页选错仍停留 D1，选对进入 D2，完成卡与承接说明正确；根式／分式知识节点仍亮起 |
| 构建与静态检查 | 通过 | 三个构建器 `--check` 均 `changed: 0`，公共导出检查、Ruff 与 `git diff --check` 通过 |

最新页面截图：[单选读题](../internal/review-analysis/function-domain-q15-20261026/reading-choice.png)。图片位于 ignored 的本地审查目录。用户普通 Q15 标签页已刷新，预览测试页已关闭；本轮隔离 PostgreSQL `function-domain-reading` 测试完成后停止，`8843` 静态预览保留。

本轮主线程集成命令（在 `server/`）：

```sh
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-function-domain-reading-20261026 PRODUCT_TEST_INSTANCE=function-domain-reading uv run pytest -q tests/search/test_function_domain_api.py tests/solver/test_graph_stage_three_course_export.py tests/auth/test_function_domain_topic.py
```
