# Track F：ProblemExtractionContext 实现计划

## 1. 目标

把题目来源转换为可追溯、可校验的 `ProblemIR`：

```text
图片 / PDF / OCR / 网页
→ source fingerprint
→ PP-DocLayout + OCR / formula OCR
→ layout / printed / handwritten SourceObservation JSON
→ ProblemRegionProposal[]
→ 前端展示候选区域，用户确认或调整 SourceSelection
→ selected-region SourceObservation
→ deterministic SourceRouter
   ├─ deterministic_complete：deterministic candidate parser
   ├─ text_semantic_required：低成本文本 LLM
   └─ multimodal_required：多模态 LLM
→ evidence-backed typed candidates
→ deterministic normalization + validation
→ ProblemExtractionContext
→ validated ProblemIR
```

OCR/layout 只报告页面观察，不能输出或补全语义 ProblemIR。Candidate extractor 只报告带 source evidence 的题面候选，不选择 capability、不构造 FunctionalPlan、不推断隐藏解法，也不使用 expected answer 补事实。Validator 是 accepted candidates 投影为 ProblemIR 的唯一权威。

F 初期以 authored ProblemIR 为 gold 运行 shadow。G 在此期间继续消费 authored ProblemIR；两条线最终通过 validated ProblemIR 和 immutable Context dependency 汇合。

F/G 阶段每次门禁都运行完整冷路径。`source fingerprint` 只承担来源身份、依赖和可追溯性，不在 Track F 实现 extraction 或最终 Lesson 缓存；缓存与重复构建优化留到 Track E。

## 2. 范围

实现：

- entity、fact、scope、goal 的 source evidence；
- OCR/layout 与数学语义歧义的分离；
-整页多题的题目区域建议、用户确认和区域版本审计；
-印刷题面、学生笔迹、混合遮挡和未知来源的 evidence 分层；
-本地轻量 layout/OCR 快路径与按需文本/多模态升级；
-可审计的 source route mode、reason code、调用次数和阶段耗时；
- label normalization 和稳定对象 identity；
- primitive-first relation extraction；
- blocking issue 与 extraction retry；
-干净 ProblemIR projection；
- authored/extracted ProblemIR 的统一 solver API。
- source fingerprint、immutable dependency 与阶段成本观测。

不实现：

- capability 或数学路线选择；
-方程求解、答案验证；
-根据常见图形补猜未声明关系；
-把学生演算、手写答案或辅助线当成题设；
-学生作答过程分析；该能力属于未来独立的`student_work_analysis`流程；
- Lesson、Diagram、Animation 生成；
- Best-of-N 选择。

## 3. Context 模型

内部 schema：`problem-extraction-context/v1`。

`ProblemExtractionContext` 与 `PlannerStateContext` 使用相同架构原则：不可变版本、完整阶段状态、显式 parent/dependency、state 权威、decision/event 审计、typed issue、retry checkpoint 和安全 projection。它只负责 extraction 阶段，不保存 Planner、runtime 或 lesson 状态。

| 区域 | 核心字段 |
|---|---|
| manifest | context/schema/parent/dependency/source id 与 hash、producer/version |
| source | asset ref、media/page/dimension、normalized source hash、canonical transform |
| selection | region proposals、用户确认/调整的polygon/block refs、selection hash和revision |
| observations | layout/OCR/formula/visual evidence refs、printed/handwritten origin和observation bundle hash |
| route | route mode、extractor path、reason codes、region refs、调用次数 |
| state | scope/entity/fact/goal candidates 的当前完整状态 |
| decisions | accept/reject/link/merge/split/revise_scope 的确定性记录 |
| issues | code、candidate/evidence refs、blocking、retryable、retry regions |
| attempts | provider、route、input/output artifact refs、usage、latency、result |
| retry | unresolved work order、locked candidate refs、attempt budget |
| projection | validated ProblemIR id/hash 或 blocked 状态 |
| quality | coverage、ambiguity、precision/recall shadow 和成本指标 |

Candidate status 使用：`proposed | accepted | rejected | ambiguous`。Context 保存候选和证据；ProblemIR 只保存 accepted semantic facts。

Context 只保存权威状态和 artifact refs。原始整页图片、完整 OCR响应、LLM prompt/raw response、handwriting mask和crop保存在Artifact Store，Context以hash/ref引用，避免一个Context JSON复制大对象。裁剪图不能替代原图成为source authority。

版本规则：

- provider超时、限流或空响应不推进semantic state；每次调用生成不可变attempt artifact，下一份语义Context引用最新attempt ledger；
-可解析的`ExtractionDecisionPatch`经deterministic merge后产生新的child Context；
- patch必须声明`base_context_id`，不能应用到其他版本；
- accepted candidate默认locked，除非当前typed issue明确授权修订；
- validated Context投影ProblemIR后保持不可变；新的source evidence创建child Context并使依赖旧ProblemIR的下游Context显式stale；
- `state`是当前事实权威，decision/event只解释状态如何形成，不能靠重放自然语言日志恢复状态。

LLM输出统一为`ExtractionDecisionPatch`，而不是ProblemIR或完整Context：

```text
base_context_id
resolved_task_ids
entity_links
fact_classifications
scope_resolutions
goal_classifications
remaining_ambiguities
```

具体dataclass与JSON字段应由同一schema事实源生成，不在文档维护第二份完整定义。

## 4. Source observations、路由与 evidence

Source ingestion 只生成观察，不生成数学实体、事实或目标：

-原始文件或稳定引用、source hash；
-页码、尺寸、方向；
- PP-DocLayout 的 text/formula/figure/table block、bbox 与置信度；
- OCR span、公式 OCR、图中短标签与置信度；
- printed/handwritten/mixed/unknown来源和笔迹遮挡关系；
-题目候选region、所属block和跨区域配图关联；
-可选的非文字 line/curve/axis 视觉 region；
- extractor/version 信息。

`source_hash` 必须基于规范化后的源内容生成，不依赖文件名或上传 URL。Context manifest同时记录 extraction contract/schema version 和会改变语义结果的 extractor配置，使 E 后续可以建立可靠缓存键；F 本身不执行缓存命中短路。

每个语义候选必须引用 evidence。图像坐标使用 source-relative 表示，避免渲染尺寸改变 Context。

确定性 normalization 可以连接或规范 evidence，但不能制造题面未给出的事实。

### 4.1 Observation JSON 不是 ProblemIR

OCR 可以输出 JSON，但其权威范围仅限文字、公式、区域和置信度，例如：

```json
{
  "kind": "text_span",
  "origin": "printed",
  "text": "抛物线 y=x^2-2x-3 与 x 轴交于 A、B 两点",
  "bbox": [0.08, 0.12, 0.92, 0.18],
  "confidence": 0.98
}
```

它不能直接断言 `A/B` 是两个 Point、方程属于哪条曲线、交点关系或 QuestionGoal。此类语义只能由 candidate extractor提出，并由 deterministic validator接受或拒绝。

### 4.2 整页多题与 SourceSelection

客户端上传未经圈选、未经裁剪的完整页面。后端根据题号、列布局、vertical gap、文字/公式连续性和邻近配图生成`ProblemRegionProposal[]`。一个题目可以由多个polygon或block组成，不能假设题干和配图总在同一矩形内。

建议的接口边界：

```text
POST /v1/source-assets
→ source_asset_id + canonical transform + ProblemRegionProposal[]

POST /v1/problem-extractions
← source_asset_id + SourceSelection
```

`SourceSelection`至少记录：

```text
proposal_ids[]
polygons[]
included_block_ids[]
mode = auto_confirmed | user_confirmed | user_adjusted
selection_revision
```

前端只负责绘制候选区域、坐标变换和用户交互；后端负责区域建议、稳定region id和selection审计。正式提取以用户确认或明确自动确认的selection为边界。完整原图、selection和派生crop必须同时保存，以支持source fingerprint、evidence坐标和重新裁剪。

区域检测低置信度、题干跨页、题号归属不明或配图可能属于相邻题时，必须要求用户确认，不能静默选择。对应错误包括：

```text
extraction.problem_region_ambiguous
extraction.problem_region_incomplete
```

### 4.3 学生笔迹与遮挡

Track F默认运行`problem_only`语义模式。每个视觉/OCR evidence必须标记：

```text
printed | handwritten | mixed | unknown
```

固定规则：

-空白区域内的学生演算、答案和批注保留为observation，但不进入题面candidate；
-圈线、下划线或涂画与印刷内容重叠时，保留原始像素和overlap关系，允许printed OCR在置信度足够时继续；
-学生添加的辅助线、坐标、点名或等量标记不得升级为题设fact；
-学生笔迹覆盖关键文字、数字或公式且无法稳定恢复时fail closed，不通过inpainting、学生答案或常见题型猜原文；
-去笔迹图只能是便于OCR的派生artifact，不能成为source evidence authority。

遮挡错误包括：

```text
extraction.source_occluded
extraction.printed_content_unrecoverable
```

普通、不重叠的笔迹无需打扰用户；只有遮挡可能改变题意时，前端才提示重新拍摄、调整region或上传干净来源。未来若分析学生解题步骤，必须使用独立Context和schema，不能复用ProblemIR extraction的accepted facts。

### 4.4 SourceRouter

第一层路由不调用大模型。首版使用本地 `PP-DocLayout-S`，必要时升级 `PP-DocLayout-M`，并结合 OCR 覆盖率、公式 parser 和轻量图形特征输出：

```text
ExtractionRoute = deterministic_complete | text_semantic_required | multimodal_required
```

路由规则：

- `deterministic_complete`：selection完整，printed OCR、公式、实体、关系、scope和goal均被已注册typed grammar唯一解析，coverage validator证明没有未消费数学语义，且不存在影响题意的mixed/unknown遮挡；
- `text_semantic_required`：无必须读取的figure，但实体、scope、fact、goal或指代需要语言理解，使用低成本文本LLM；
- `multimodal_required`：存在figure/坐标轴/几何标签关联，或layout/OCR/公式/笔迹重叠证据需要看原图消歧，使用OCR observations、handwriting mask和相关原图crop调用多模态LLM。多模态模型仍不能从不可见像素补猜被遮挡题面。

Router 只决定 extractor，不产生数学事实。每次决策必须记录 mode、reason codes、region refs、模型调用数和耗时。多模态 retry优先发送冲突 bbox，不重复发送整页。

### 4.5 Candidate JSON

三类 extractor 使用同一个 typed candidate schema，例如：

```json
{
  "candidate_id": "fact_12",
  "kind": "curve_axis_intersection",
  "subjects": ["curve_f", "x_axis"],
  "result_entities": ["point_A", "point_B"],
  "scope_hint": "problem",
  "evidence_refs": ["text_span_8", "formula_3"],
  "status": "proposed"
}
```

Candidate extractor不能省略 evidence、把视觉外观升级为已知条件，或直接生成最终 typed identity。对象 linking、scope tree、value parsing、ambiguity 和 ProblemIR identity由后续确定性阶段处理。

## 5. Primitive-first

应提取：

```text
point M
point D
angle(M, D, N) = 90°
length(D, M) = length(D, N)
point P lies on parabola f
symbol m has domain m > 0
```

不应提取 planner-specific 概念，例如某个 recipe 已就绪或某条 capability 路线应该被采用。复合 Condition、object role 和 capability admission 由 solver contract 投影。

## 6. Identity 与 scope

- label 是 identity evidence，不是 identity 本身；
-同名多个 region 在证据唯一前保持歧义；
-坐标、长度或表达式相等不合并对象；
- Symbol 先注册 typed identity，表达式写法不创建新身份；
- scope 先由题号/layout 候选产生，再经确定性 tree validator；
- fact 放在 evidence 能证明的最窄 scope；
-所有小问前明确给出的公共事实可进入父 scope；
-不得因 sibling 后续需要而提升 child-private fact。

## 7. 初始语料与扩展规则

Track F 先使用现有五道题的结构化gold作为端到端锚点；对应原始图片由用户补充后进入source corpus：

```text
nankai
heping-ermo
xiqing
hexi
heping
```

五题用于建立第一版 source image、region manifest、authored ProblemIR、solver 结果和 lesson 输出的可追溯基线，但不据此宣称已经覆盖所有输入类型。测试必须另行维护 coverage matrix，至少标记：

- 页面数量、方向和图片质量；
-是否为未经裁剪的整页、同页题目数量、目标题region和配图归属；
-是否含学生演算、圈画、辅助线，以及是否遮挡印刷内容；
- 是否含数学图形、坐标轴、表格或仅有正文；
- OCR、公式 OCR 和 reading order 难度；
- 预期 route；
- entity、relation、scope、goal 和指代类型；
- 是否应做到零 LLM。

如果五题缺少某个实现阶段的必要覆盖，例如 `deterministic_complete` 的无图、文法明确题，测试不得伪造“已覆盖”。应输出一份具体的补充输入需求，包括：

```text
缺失 route / semantic dimension
建议题型与版面特征
必须包含或避免的元素
期望经过的F阶段
需要提供的图片数量
```

用户提供图片时优先使用未经裁剪、未经画框的完整原页，并指出目标题号；跨页题提供全部相关页面。原有学生笔迹无需人工擦除。新增图片进入 corpus 前，必须补齐 source manifest、gold SourceSelection、printed/handwritten annotation、authored ProblemIR、evidence annotation 和预期 route；确认后的样本永久进入离线回归。模型偶然成功的 live 样本不能直接作为 gold。

首批真实source coverage至少包括：

-一张干净整页、多题并存的图片，用于region proposal和用户selection基线；
-一张带有不遮挡题干的学生演算或圈画的图片；
-后续补一张笔迹与印刷内容重叠的图片，验证可恢复与不可恢复分界；
-严重遮挡关键条件的图片作为预期失败样本，不要求系统猜出原文。

因此，F 的语料增长方式固定为：

```text
五题锚点
→ coverage matrix 暴露缺口
→ 请求具有明确特征的新图片
→ authored annotation + 首个失败测试
→ 实现或修复
→ 新样本固化为回归 corpus
```

## 8. 实施阶段

所有阶段严格使用 red -> green -> refactor：先提交能稳定失败的正向、负向和幂等测试，再实现最小能力。每个阶段的离线测试不得依赖真实OCR或LLM网络；provider使用recorded response/contract fake。真实服务只在对应阶段离线通过后运行smoke。

### F0：五题 Gold corpus、coverage matrix 与 semantic diff（COMPLETE）

已于 2026-08-05 完成五张原图的 immutable manifest、authored selection、印刷/手写证据标注、完整 semantic evidence mapping、grounded coverage report 和稳定 semantic diff。F0 专项为 41 passed，连同 fixture schema 的规定回归为 68 passed。Auditor 自身要求五个锚点齐全并拒绝空 corpus、仓库外 asset/fixture、畸形 canonical fixture、目录身份漂移、孤儿 problem-source evidence 和重复语义缺失；selection/excluded 使用真实多边形正面积相交，边界接触不算重叠。排除区域通过 typed exclusion subject 引用相邻题、页眉等语义对象；邻题 coverage 统计唯一 `neighbor_question` subject，不依赖 polygon 数量。Coverage 同时报告 authored declaration 与 evidence-grounded facts；`deterministic_complete` 只能由 F3 可执行 parser 门禁关闭。当前 corpus 明确保留 deterministic complete、题内印刷图形、跨页题和不可恢复遮挡四项缺口。

先写失败测试：

- `test_problem_extraction_gold_corpus.py`断言五题source、page、gold SourceSelection、printed/handwritten annotation和authored ProblemIR一一对应；
- coverage matrix 必须报告五题实际覆盖的 route 和 semantic dimensions，缺失项必须显式列出，不能以默认值补齐；
-缺source region、重复evidence id、gold fact无evidence时稳定失败；
- semantic diff能报告首个entity/fact/goal/scope差异，而不是只返回不相等。

五道题原始整页图片补齐后，再实现source region manifest、gold SourceSelection和gold semantic projection，比较：

- entity/fact/goal precision 与 recall；
- subject、value、scope 和 symbol/domain；
- evidence coverage；
- problem region precision/recall和配图归属；
- handwriting origin与关键遮挡分类；
- blocking ambiguity；
- ProblemIR semantic equivalence。

退出门禁：五题原始图片与结构化gold一一对应并可确定重放，任意删除或篡改gold字段都会被对应测试捕获；coverage report能直接生成下一批图片的精确需求。

### F1：Source fingerprint 与 Context envelope（COMPLETE）

已于 2026-08-05 完成 `problem-extraction-context/v1`的身份与状态基础。F1 定向测试为
48 passed，与 F0 corpus 和 fixture schema 的规定联合回归为 116 passed。实现包括：

- 将 EXIF 方向归一后的 RGBA 像素、尺寸和页序固化为 `source_id`，将有序的原始页字节
  与 `page_id` 映射固化为独立 `source_revision_hash`；
- 将 authored/user selection 的归一化多边形和 block 集合固化为 `selection_id`，将 source、
  selection、contract、semantic config 和 upstream Context 组合为 `dependency_hash`；
- Context 的 state、decision/event、attempt ref、retry 和 pending projection 均递归冻结，
  `from_payload()` 经 JSON Schema 后重算全部 hash；
- `selection_id` 只表示 geometry/block 语义；mode、revision、parent selection 和 reason 等审计字段
  另由 `context_id` 覆盖，修改它们不会伪造新语义 selection，但会使旧 Context 失效；
- provider 失败只追加独立 attempt ledger，不产生语义 child Context；只有通过 base、ledger、
  evidence 和 locked-candidate 授权校验的 patch 才会原子生成 child Context；
- child Context 保留全部祖先 `attempt_refs`，并追加当前 base ledger 的新 attempt；
  attempt ref 携带可重算的 record/artifact authority 摘要，`attempts_used` 与 budget 均按整条
  Context lineage 累计校验；
- 非 root Context 的 hydrate 和后续 patch 必须显式提供完整 root-to-parent Context 序列；每个节点的
  `ancestor_context_ids` 必须精确等于已提供前缀，不能从缺少真实根节点的自洽中间 Context 继续生长；
- lineage 中每个 Context 在被用作 parent、decision 或 attempt 权威前，必须独立重算其
  source/dependency、state hash、context id、event、attempt authority 和 retry 信封；被 `replace()`
  篡改但保留旧 hash 的 parent 不能生成或 hydrate child；
- child 的 decision、event 和 attempt ref 必须完整保留 parent 前缀，当前 patch 只能追加；新 attempt
  的 `base_context_id` 必须等于 immediate parent，不能借伪造祖先消耗 retry budget；
- decision 是不可变审计记录而不是当前 state 的活约束；历史 decision 可以继续引用后续已授权删除的
  candidate，只有当前 child 新增的 decision 需要对 parent/current candidate 集做引用校验；
- 普通 semantic patch 不能新建 lock，也不能将 proposed candidate 提升为 locked accepted；
  accepted/locked 必须由可信 validator 边界建立，已有 lock 的修订仍要求 blocking issue 显式授权；
- 带 `authorized_revision_candidate_ids` 的 issue 只能在被授权 candidate 发生实际修订后关闭；
  若确认为误报，必须提交 `dismiss_issue_false_positive` decision 并保留 candidate/evidence 引用；
- 五题已固化 source、revision、selection、dependency 和 initial Context 指纹；F0 adapter
  会先校验 manifest 的原始 SHA，再建立空语义状态的初始 Context。

本阶段未导入或调用 PP-DocLayout、OCR、DeepSeek 或多模态 provider；SourceObservation 从 F2
开始写入。

先写失败测试：

- `test_problem_extraction_source_fingerprint.py`覆盖图片字节、页面顺序、方向归一化和 extraction contract version；
-相同内容不同文件名/URL必须得到相同source identity，图片内容、页序或语义相关配置改变必须改变dependency hash；
-同一原图调整SourceSelection不得改变source hash，但必须改变selection hash和下游Context dependency；
- `test_problem_extraction_context.py`覆盖schema round-trip、state hash、parent/dependency和artifact refs；
-原地修改state、跨base应用patch、重复candidate id和悬空evidence ref必须失败；
- provider retry不产生child Context，semantic patch必须产生child Context；
-同一输入连续apply两次得到相同state或明确拒绝重复patch。

再实现 source fingerprint、dependency manifest，以及 immutable Context 的 manifest、state、decision/event、attempt summary、retry state和ProblemIR/quality projection骨架。本阶段不运行layout、OCR或LLM。

退出门禁：Context连续JSON round-trip语义相等；accepted candidate不会被未授权patch覆盖；坏dependency和坏hash fail loud。

### F2：图片/PDF 到区域、笔迹分层与 SourceObservation JSON

先写失败测试：

- `test_problem_extraction_observations.py`覆盖orientation、layout block、OCR span、formula、reading order和normalized bbox；
- `test_problem_region_proposals.py`覆盖单题、多题、双栏、题干配图分离、跨页和用户adjusted selection；
- `test_problem_extraction_handwriting.py`覆盖无笔迹、空白处演算、下划线重叠、手写辅助线和关键公式遮挡；
-删改原始图片region、交换page或破坏公式时，observation hash和对应evidence必须确定变化；
-候选region遗漏配图、误吞相邻题、selection引用悬空block或使用错误坐标transform时必须失败；
-学生手写答案和辅助线不得产生printed evidence或semantic candidate；
- Observation adapter不得创建entity、fact、scope或goal；
- recorded PP-DocLayout/OCR/formula OCR响应必须能离线重放为完全相同的JSON。

再实现PP-DocLayout/OCR/formula adapter、handwriting/overlap adapter、ProblemRegionProposer、SourceSelection contract和SourceObservation schema。真实provider输出先经过adapter contract归一化，生产逻辑不读取厂商私有字段。本阶段只形成页面观察、区域建议、用户selection和evidence origin，不作source route或数学语义判断。

退出门禁：所有gold source均可稳定生成候选region和SourceObservation JSON；gold SourceSelection可确定重放；同一recorded输入重复运行得到相同observation、mask和artifact hashes。

### F3：SourceRouter 与 deterministic candidate parser

先写失败测试：

- `test_problem_extraction_routing.py`覆盖三种route及reason codes；
- `test_problem_extraction_deterministic_parser.py`覆盖实体、坐标、公式、primitive relation和QuestionGoal grammar；
-打乱OCR span、重命名evidence id或改变无关标点不改变canonical candidate outcome；
-删除figure、降低OCR置信度、制造公式parser歧义时route必须确定变化；
- selection不完整或mixed/unknown evidence遮挡关键内容时不得进入`deterministic_complete`；
-未消费数学clause、否定、代词或多重合法parse必须退出`deterministic_complete`；
- Router不得创建entity/fact/goal，`deterministic_complete`路径的LLM spy调用数必须为零。

再实现 SourceRouter、typed grammar coverage validator和deterministic candidate parser。Deterministic parser只覆盖简单、文法明确且公式可解析的纯文本题；正则仅用于词法识别，数学表达式、关系、scope和goal由结构化parser与typed rule registry处理。

本阶段若五题没有可证明`deterministic_complete`的样本，coverage gate必须请求至少一张“无图、单页、题干与目标均可由已注册grammar完整消费”的题目图片，不能用mock source替代集成锚点。

退出门禁：三种route可确定复现；至少一份真实图片走deterministic完整路径且LLM调用为零；coverage不足必定升级而不是丢弃clause。

### F4：DeepSeek 文本语义 extractor

先写失败测试：

- `test_problem_extraction_text_llm.py`用recorded/fake DeepSeek响应覆盖entity linking、指代、scope、fact和goal分类；
- `test_problem_extraction_llm_contract.py`拒绝无evidence candidate、自由文本relation、完整ProblemIR输出、capability hint和expected answer；
- prompt只包含selected-region中的printed SourceObservation、candidate schema和unresolved work order，不包含学生手写答案、原图、Functional catalog或解法；
-provider超时、reasoning-only、坏JSON和语义patch无进展必须分别产生稳定attempt状态；
-相同recorded响应重复应用得到相同patch与Context state。

再实现低成本文本模型backend：输入OCR/layout/formula observations，输出`ExtractionDecisionPatch`或typed candidates。它不读取图片，不生成最终ProblemIR，也不能覆盖已locked且不在work order中的候选。

退出门禁：所有`text_semantic_required` recorded cases可离线重放；provider失败与语义失败分类清楚；文本backend与deterministic backend产出同一candidate contract。

### F5：多模态语义 extractor

先写失败测试：

- `test_problem_extraction_multimodal.py`覆盖图形region选择、图中label linking、坐标轴/几何关系候选和冲突crop retry；
-只发送route指定的相关crop与必要题干，禁止默认重复发送整页；
-删除关键figure region、交换图中同名label或提供冲突OCR时必须保留ambiguity，不能按视觉常识补事实；
-即使多模态模型读出了学生答案或辅助线，也必须因evidence origin不合法而拒绝写入题面candidate；
-多模态输出必须与文本backend使用同一candidate/patch schema和evidence约束；
-provider输出不含source evidence时稳定拒绝。

再实现多模态backend：输入OCR observations、相关题干和diagram/冲突crop，输出带evidence的typed candidates或`ExtractionDecisionPatch`。Router在运行时只选择文本或多模态分支之一；不会先调用文本模型再无条件调用多模态模型。

退出门禁：至少一份含图gold source完成multimodal离线重放；crop选择、调用次数和artifact refs可审计；文本与多模态分支可独立运行。

### F6：Normalization、Validation 与 retry

先写失败测试：

- `test_problem_extraction_candidates.py`要求deterministic/text/multimodal backend输出同一candidate schema；
- `test_problem_extraction_normalization.py`覆盖OCR规范化、value parser、scope tree、label linking和primitive fact canonicalization；
- `test_problem_extraction_validation.py`逐个覆盖下列typed issue和blocking/retryable分类；
- `test_problem_extraction_retry.py`断言retry只包含相关evidence、unresolved tasks和必要locked refs；
- retry不能重写无关accepted candidate，不能重新发送整页，不能暴露expected answer或Functional catalog；
- issue集合连续两轮无进展、evidence缺失或预算耗尽时进入blocked；
-成功patch创建child Context并保留完整parent/attempt审计。

先实现deterministic normalization：

- OCR 空白、标点和跨 span 合并；
-分数、根式、坐标和方程解析；
-题号与 scope tree；
- evidence 唯一时的 label linking；
- duplicate evidence 与 primitive fact canonicalization；
- value/type validation。

首批错误码：

```text
extraction.entity_identity_ambiguous
extraction.fact_subject_unresolved
extraction.fact_value_unparsed
extraction.scope_unresolved
extraction.goal_target_unresolved
extraction.evidence_missing
extraction.source_conflict
extraction.problem_region_ambiguous
extraction.problem_region_incomplete
extraction.source_occluded
extraction.printed_content_unrecoverable
extraction.problem_ir_incomplete
```

再实现validator、ExtractionWorkOrder、ExtractionDecisionPatch merge和targeted retry。Retry只接收immutable Context、未解决候选、相关evidence和紧凑issue。Planner failure只有确定性归因为extraction gap后才能回到F。

退出门禁：三条backend均进入同一normalizer和validator；所有失败均有稳定code、root evidence和retry边界；失败Context不产生ProblemIR；连续执行相同retry序列结果幂等。

### F7：ProblemIR projection 与冷路径集成

先写失败测试：

- `test_problem_extraction_to_problem_ir.py`断言blocking issue、ambiguous candidate和缺evidence时禁止projection；
- projection只包含accepted semantic state，不复制OCR、bbox、confidence、attempt或rejected candidate；
- `test_problem_extraction_solver_integration.py`比较extracted/authored ProblemIR的family admission、answer signature和provenance；
-至少一题从真实source离线artifact完整进入Track G并编译HTML。

再实现唯一ProblemIR projector：

-存在 blocking issue 时禁止 projection；
- ProblemIR source manifest 只记录 Context id、source hash 和 schema/version；
-不复制 OCR 内部数据；
- extracted 与 authored ProblemIR 进入同一 family/planner/solver API。

退出门禁：五题semantic diff达到要求，补充的route-specific corpus全部通过，solver/lesson-page回归通过，重复冷路径生成相同ProblemIR语义hash。

## 9. 与 Track G 的接口

F 只输出：

```text
ProblemIR
ProblemSourceManifest
SourceVisualReferenceProjection（可选）
```

PlannerStateContext 只消费 ProblemIR。Planner prompt 不接收 OCR alternatives、bbox、被拒候选或内部 confidence。

DiagramContext 可读取 accepted label regions 和近似视觉位置，但不能新增或覆盖数学事实。

新的 accepted extraction version 会使依赖旧 ProblemIR 的 PlannerStateContext stale，并向 G 下游传播。Authored ProblemIR 不要求 extraction dependency。

F 不复制下游 artifact，也不在本阶段实现缓存。G 只依赖 F 输出的 Context/version/source hash；每次 F/G 门禁从 source完整运行到页面，并记录将来最小失效所需的 dependency manifest。最终 Lesson cache、extraction/solver/lesson/render分层复用和并发构建去重统一由 Track E实现。

## 10. Shadow

1. Authored ProblemIR 保持 solver authority。
2. F 从真实 source 生成 candidate ProblemIR。
3. Semantic diff 比较两者。
4. 必要时运行 deterministic solver preflight。
5. mismatch 归因到 extraction、normalization 或 authored gold。
6. Shadow 结果不修改正式 lesson artifact。

## 11. 跨阶段测试门禁

每个F0-F7阶段先运行本阶段定向测试，再运行全部已完成F阶段测试；任何阶段不得以live provider偶然成功代替离线contract测试。

Generated/metamorphic门禁：

-重命名 label、OCR span 重排、无关文本和标点扰动；
-调整前端显示尺寸、设备像素比或crop渲染尺寸不改变normalized SourceSelection；
-在相邻题增加文字或配图不得改变已确认目标题的semantic extraction；
-在空白处添加学生演算不得改变ProblemIR；
-给原图添加手写辅助线不得新增几何fact；
-新增无关装饰图片不应自动产生数学 diagram fact；
-删除 figure region时 route和 evidence coverage必须确定变化；
-公式 parser 从成功变为歧义时必须离开 deterministic_complete快路径；
-新增同名 region 必须产生 ambiguity；
-删除 evidence 后 dependent fact unresolved；
-改变题号后 scope 确定变化。

Mutation门禁：

-故意删除evidence ref、交换scope parent、接受ambiguous candidate、复用错误base_context_id或把视觉候选升级为fact，必须在首个负责阶段失败；
-故意误吞相邻题、遗漏目标题配图、把handwritten改成printed或用inpainting结果补事实，必须有对应测试变红；
-故意让Router漏报figure、deterministic parser忽略否定、retry覆盖locked candidate或projector复制OCR字段，必须有对应单测变红；
-测试不得只断言最终`ok`，必须比较候选集合、issue code、Context parent/hash、route、projection和artifact refs。

Integration门禁：

-五题 source 与 authored ProblemIR semantic diff；
-整页多题region proposal与gold SourceSelection比较，并覆盖用户确认和adjusted selection；
-学生笔迹不遮挡时ProblemIR保持不变；关键题面不可恢复时稳定blocked而不是猜测；
- coverage matrix 对缺失类型 fail loud，并能生成给用户的补图需求；
-至少一条 deterministic-only、text-LLM 和 multimodal 路径通过端到端门禁；五题不足时使用按第7节流程补入的真实题目图片；
- deterministic_complete路径的LLM调用数为零；
- multimodal_required路径只向多模态模型发送相关region和必要题干；
- extracted ProblemIR 通过 family admission；
- answer signature/provenance 与 authored 路径一致；
-至少一题进入 Track G 并编译 HTML；
- planner retry 不得用 prose 猜 extraction gap。
-每次集成门禁均记录 layout、OCR、text/multimodal extractor的冷路径耗时、token与调用次数；
- source、extraction contract或extractor配置改变时，dependency manifest确定变化；
-仅改变下游 lesson/renderer contract时，ProblemExtractionContext内容保持稳定。

完整测试模块：

```text
test_problem_extraction_gold_corpus.py
test_problem_extraction_source_fingerprint.py
test_problem_extraction_context.py
test_problem_extraction_observations.py
test_problem_region_proposals.py
test_problem_extraction_handwriting.py
test_problem_extraction_routing.py
test_problem_extraction_candidates.py
test_problem_extraction_deterministic_parser.py
test_problem_extraction_text_llm.py
test_problem_extraction_multimodal.py
test_problem_extraction_llm_contract.py
test_problem_extraction_normalization.py
test_problem_extraction_validation.py
test_problem_extraction_retry.py
test_problem_extraction_generated_gate.py
test_problem_extraction_to_problem_ir.py
test_problem_extraction_solver_integration.py
```

阶段内标准命令：

```bash
cd server
uv run pytest tests/solver/test_problem_extraction_<stage>.py -q
uv run pytest tests/solver/test_problem_extraction_*.py -q
git diff --check
```

F7完成前再运行：

```bash
cd server
uv run pytest tests/solver -q
git diff --check
```

真实PP-DocLayout/OCR/text/multimodal smoke只在对应offline gate通过后运行，并保存provider版本、输入hash、route、latency、usage和parsed patch；smoke失败必须先匿名化为recorded fixture，再修生产代码。

## 12. 完成条件

-五题保留全部 solver-required entity、fact、scope、symbol 和 QuestionGoal；
-五题原始整页图、gold SourceSelection和派生crop均可追溯，自动region proposal不会混入相邻题；
-printed/handwritten/mixed/unknown evidence分层可审计；学生答案、演算和辅助线不进入ProblemIR；
-关键印刷条件被不可恢复地遮挡时fail closed并给出明确重拍提示；
- coverage matrix 明确区分“五题已覆盖”和“待补图片”，不得用mock或默认值假装覆盖真实route；
-需要新增类型时，能向用户给出可从高中题库选择的精确图片特征；确认后的新增图片进入永久gold corpus；
- blocking ambiguity 不被静默解决；
- extracted/authored ProblemIR 产生相同 required answer signature；
- extraction configuration/unclassified error 为零；
- route decision、阶段 latency 与 OCR/text/multimodal调用次数可审计；
-符合 deterministic_complete 条件的 gold source不调用任何LLM；
- diagram/ambiguous source不因追求快路径而静默丢失视觉 evidence；
- planner payload 不包含 extraction internals；
- Context dependency 与 stale propagation 通过测试；
-至少一题通过图片到 HTML 门禁；
-完整图片到HTML冷路径可以稳定重复执行；
- Context/source/dependency指纹足以支持E后续构造缓存键和最小失效；
- solver 和 lesson-page 全量回归通过。

## 13. 顺序

```text
F0 五题gold corpus + coverage matrix
→ F1 source fingerprint + Context envelope
→ F2 image/PDF → region/handwriting layers + SourceObservation JSON
→ F3 SourceRouter + deterministic parser
→ F4 DeepSeek text extractor
→ F5 multimodal extractor
→ F6 normalization + validation + retry
→ F7 ProblemIR projection + integration
→ F/G image-to-lesson gate
```

F/G 产生完整质量、失败、延迟、token和模型调用指标后，再启动 Track E统一实现最终缓存、分层复用、并发去重和条件式Best-of-N。
