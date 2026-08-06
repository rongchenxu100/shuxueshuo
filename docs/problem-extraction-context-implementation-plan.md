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
→ Multimodal Evidence Pack（完整题目图 + OCR/layout/formula/ink 辅助观察）
→ 单一多模态语义 extractor
→ evidence-backed typed candidates
→ deterministic normalization + validation
→ ProblemExtractionContext
→ validated ProblemIR
```

完整题目图是语义提取的第一手输入。OCR/layout/formula/ink 只报告页面观察，作为多模态模型的辅助转录、阅读顺序、局部放大和冲突提示，不能输出或补全语义 ProblemIR。多模态 extractor 只报告带 source evidence 的题面候选，不选择 capability、不构造 FunctionalPlan、不推断隐藏解法，也不使用 expected answer 补事实。Validator 是 accepted candidates 投影为 ProblemIR 的唯一权威。

F 初期以 authored ProblemIR 为 gold 运行 shadow。G 在此期间继续消费 authored ProblemIR；两条线最终通过 validated ProblemIR 和 immutable Context dependency 汇合。

F/G 阶段每次门禁都运行完整冷路径。`source fingerprint` 只承担来源身份、依赖和可追溯性，不在 Track F 实现 extraction 或最终 Lesson 缓存；缓存与重复构建优化留到 Track E。

## 2. 范围

实现：

- entity、fact、scope、goal 的 source evidence；
- OCR/layout 与数学语义歧义的分离；
-整页多题的题目区域建议、用户确认和区域版本审计；
-印刷题面、学生笔迹、混合遮挡和未知来源的 evidence 分层；
-本地 layout/OCR/formula/ink 辅助观察与统一多模态语义提取；
-可审计的 source preflight、辅助证据、模型调用次数和阶段耗时；
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
| extraction | 固定多模态contract、preflight reason、evidence pack refs、调用次数 |
| state | scope/entity/fact/goal candidates 的当前完整状态 |
| decisions | accept/reject/link/merge/split/revise_scope 的确定性记录 |
| issues | code、candidate/evidence refs、blocking、retryable、retry regions |
| attempts | provider、extractor contract、input/output artifact refs、usage、latency、result |
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

## 4. Source observations 与 evidence

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

F2 本地墨迹分析对彩色笔迹提供保守的 `handwritten/mixed` 判断；对黑灰中性笔画，只在笔画具有
OCR 框外 seed 且穿入 printed span 时降级为 `mixed/unknown`。完全位于 OCR 框内、与印刷同色且被
OCR 识别为正文的手写，以及空白区内未与 printed span 相交的纯黑演算，不能由这套确定性 CV 稳定区分，
必须作为 unresolved observation 交给 F3 多模态 extractor 结合完整题目图判断，F2 不得猜测其来源。

遮挡错误包括：

```text
extraction.source_occluded
extraction.printed_content_unrecoverable
```

普通、不重叠的笔迹无需打扰用户；只有遮挡可能改变题意时，前端才提示重新拍摄、调整region或上传干净来源。未来若分析学生解题步骤，必须使用独立Context和schema，不能复用ProblemIR extraction的accepted facts。

### 4.4 统一多模态提取边界

生产路径不再判断“是否需要 LLM”，也不在确定性 parser、文本模型和多模态模型之间路由。通过 source、selection 和 artifact preflight 后，每道题统一调用一次多模态语义 extractor：

```text
首轮：完整 SourceSelection 题目图
    + 高可信 OCR/layout/formula/ink 摘要
    + unresolved region 清单
重试：同一完整题目图
    + 上一轮 typed issue
    + 由 evidence polygon 确定生成的定向 zoom
→ typed candidates / ExtractionDecisionPatch
```

固定规则：

- 单页题首轮只发送一张完整 `SourceSelection` 题目图，包含全部题干、小问和归属该题的图形；相邻题、页眉和 selection 外学生演算不得进入；
- 多 polygon 同页 selection 先生成一张保留阅读顺序的 canonical selection canvas；只有真实跨页题才按 page order 发送每页一张主图；
- 首轮默认不发送 formula、diagram、遮挡 crop 或 overlay。高可信 OCR 文本、reading order、公式结果、置信度和 origin 只作为紧凑辅助摘要；
- OCR 不确定内容仍要告知模型，但只发送 `evidence_id`、region、issue code 和必要的可见片段提示。重复、膨胀或明显错误的原始 LaTeX 不进入 prompt，避免错误锚定；
- `extraction.formula_observation_unresolved` 等 F2 issue 不改变模型路径，而是形成明确的 work order，要求模型直接回看完整题目图对应区域；
- 多模态模型可以提出与 OCR 不同的候选文本或公式，但必须引用原始 source region，并保留冲突供 deterministic validator 判定；不得原地改写 SourceObservation；
- `handwritten/mixed/unknown` observation 只能用于来源判别和冲突说明，不能因为模型读出了学生答案或辅助线就升级为题设 fact；
- 关键印刷内容不可见或不可恢复时，preflight 或 validator 必须 fail closed，要求重新拍摄，不能让模型按题型猜测。

F1 中历史命名为 `route` 的 attempt 字段在 `problem-extraction-context/v1` 内只保存固定的 `multimodal` audit label，不再表达动态决策；后续 schema 升级时改名为 extractor contract。每次调用记录完整题目 artifact、辅助 observation bundle、zoom refs、模型版本、usage、latency 和 parsed patch。

F2 建立只读 `ObservationRegionIndex`：

```text
evidence_id / region_id
→ page_id + normalized polygon + source artifact
```

LLM 输出的每个 candidate 必须引用 catalog 中已有的 `evidence_refs`；无法完成判断时，只能通过 `review_region_refs` 指向已有 text span、formula candidate、ink/occlusion region、layout block 或 figure block，不能提交自由坐标。Validator 不重新运行 OCR，也不“看图”：它把 typed issue 关联到 candidate，再沿 candidate → evidence/review region → polygon 确定需要复核的原图区域。`RetryZoomProjector` 对这些 polygon 做确定性合并、padding 和 crop，从 canonical source artifact生成 zoom。

Retry 始终保留同一完整题目图和全部有效题干上下文，再追加上一轮 typed issue。只有存在可解析的 `retry_region_refs` 时才附加定向 zoom；没有可靠 region 时只使用完整图重试，禁止猜 crop。单页首轮因此通常只有一张图片，单页 retry 通常是“完整图 + 一张定向 zoom”；多张 zoom 只允许用于互不相连且同属一个 blocking issue 的区域，并受固定数量上限约束。

### 4.5 Candidate JSON

多模态 extractor 使用统一 typed candidate schema，例如：

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

Track F 先使用现有五道题的结构化gold和已入库原图作为端到端锚点：

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
- 预期 source preflight 结果与需要重点复核的视觉区域；
- entity、relation、scope、goal 和指代类型；
- 完整题目图、跨页、图形和冲突 zoom 等 multimodal evidence pack 维度。

如果五题缺少某个实现阶段的必要覆盖，例如必须消费的印刷图形、真实跨页题或不可恢复遮挡，测试不得伪造“已覆盖”。应输出一份具体的补充输入需求，包括：

```text
缺失 source / semantic dimension
建议题型与版面特征
必须包含或避免的元素
期望经过的F阶段
需要提供的图片数量
```

用户提供图片时优先使用未经裁剪、未经画框的完整原页，并指出目标题号；跨页题提供全部相关页面。原有学生笔迹无需人工擦除。新增图片进入 corpus 前，必须补齐 source manifest、gold SourceSelection、printed/handwritten annotation、authored ProblemIR、evidence annotation 和预期 preflight；确认后的样本永久进入离线回归。模型偶然成功的 live 样本不能直接作为 gold。

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

已于 2026-08-05 完成五张原图的 immutable manifest、authored selection、印刷/手写证据标注、完整 semantic evidence mapping、grounded coverage report 和稳定 semantic diff。F0 专项为 41 passed，连同 fixture schema 的规定回归为 68 passed。Auditor 自身要求五个锚点齐全并拒绝空 corpus、仓库外 asset/fixture、畸形 canonical fixture、目录身份漂移、孤儿 problem-source evidence 和重复语义缺失；selection/excluded 使用真实多边形正面积相交，边界接触不算重叠。排除区域通过 typed exclusion subject 引用相邻题、页眉等语义对象；邻题 coverage 统计唯一 `neighbor_question` subject，不依赖 polygon 数量。Coverage 同时报告 authored declaration 与 evidence-grounded facts。旧 coverage 中的 `deterministic_complete` 维度随单一多模态路径退役，F3 开始时迁移为 multimodal evidence/preflight coverage；当前仍需补充题内印刷图形、真实跨页题和不可恢复遮挡样本。

先写失败测试：

- `test_problem_extraction_gold_corpus.py`断言五题source、page、gold SourceSelection、printed/handwritten annotation和authored ProblemIR一一对应；
- coverage matrix 必须报告五题实际覆盖的 source、multimodal evidence 和 semantic dimensions，缺失项必须显式列出，不能以默认值补齐；
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

### F2：图片/PDF 到区域、笔迹分层与 SourceObservation JSON（IMPLEMENTED / HUMAN SIGN-OFF PENDING）

已于 2026-08-05 完成实现和真实五题 smoke。默认 solver 环境只包含 schema、adapter、
Context transition、artifact store、PDF rasterizer 和 review 生成器；Paddle 仅由独立
`server/.venv-ocr` worker 延迟导入。当前实现包括：

- `source-observation/v1` 与 `paddle-provider-record/v1`，统一 canonical page 坐标、reading order、
  provider authority、typed issue 和稳定 observation hash；
- `PP-DocLayout-S`、`PP-OCRv6_medium_det/rec`、`PP-FormulaNet_plus-M` 的独立 worker，五题 batch
  内每类模型只初始化一次；
- confirmed selection 快速路径采用“全页 layout + confirmed-selection crop 文字 OCR”；所有文字 observation
  的中心必须位于 selection 内。自动 proposal 所需的全页 OCR 是后续独立入口，不能与该 smoke 路径混用；
- 题号、双栏布局与保守跨页 continuation region proposal、彩色墨迹与跨 OCR 框中性深色笔画检测，
  以及 printed/handwritten/mixed/unknown 保守分类；公式 crop 在墨迹分类后生成，仅 printed 候选进入
  公式模型，handwritten/mixed/unknown 数学候选聚合保留 `extraction.formula_observation_unresolved`；
- printed OCR 与墨迹接触只有在目标文字框内的局部覆盖比例达到 ambiguous 阈值时才降为 `mixed`；
  recoverable 擦边继续保持 printed。遮挡 polygon 使用目标文字内真实 ink pixel 的紧致外框，不再复用
  跨半页墨迹组件的外接矩形；review overlay 用内容寻址 mask 的精确像素着色，大型组件不再绘制误导性整页框；
- Formula OCR 增加 source-fidelity audit：按 OCR 原文提取可见数学片段，检查 radical、数值、关系式和
  运算片段是否完整覆盖，并拒绝中文散文输出、异常长度膨胀和重复 token 幻觉。失败结果保留原始 LaTeX
  供人工审查，但权威状态降为 `unresolved` 并产生带 reason/expected fragments 的 typed issue；
  `recognized` 只允许 `origin=printed`，smoke 同时拒绝没有 typed issue 的 unresolved formula；
- 含数学内容的中文题干行不再整行送入 FormulaNet。F2 先用纯词法规则提取连续数学片段，按 OCR 行内
  字符位置生成紧凑 crop，例如同一行分别形成 `-1<m<0` 与 `∠CBE+∠ACO=45°`；完整 OCR 题干仍保留为
  后续多模态 extractor 的辅助转录。每个 provider result 必须携带精确 `formula_request_id`、source hint、
  source observation 与 polygon，旧整行结果或同源错绑结果均 fail closed；片段输出除等价排版符号外不得
  多出邻接字符，否则以 `formula_output_contains_unexpected_content` 降为 unresolved；
- 内容寻址 artifact store、可信 observation Context attachment、recorded replay、静态 HTML review pack；
- Context attachment 对 canonical page、公式 crop 和笔迹 mask 执行完整 artifact closure 校验，并在 evidence
  payload 中保留派生 artifact 引用；Paddle 与 local CV 使用独立 attempt，公式 crop 必须是 provider input，
  handwriting mask 必须是 local CV output；authoritative bundle 只允许 selection/formula crop，厂商 raw payload
  只写入 `provider-records/*.raw.json` 调试 sidecar，不进入 Context；
- OCR 质量使用图片的 authored physical transcript，不使用允许语义归一的 canonical ProblemIR 文案。

规定的 F0-F2、provider adapter、smoke acceptance 与 fixture schema 联合回归为 185 passed；全量 solver 为
1391 passed、12 skipped。真实五题 smoke 为 5/5，
三类模型初始化计数均为 1，recorded replay 的 observation/artifact/Context hash 无漂移。五题归一化
OCR CER 依次为：和平二模 0.0055、和平一模 0.0276、河西 0.0064、南开 0.0094、西青 0.1452；
均低于 0.20，且无整行题面缺失。河西 clean baseline 无笔迹误报；西青的公式候选因 mixed/unknown
来源不进入公式 OCR，并保留聚合 typed unresolved 与 overlap issue。基于该次真实 provider records 的
确定性重放仍为 5/5；normalized record 与 raw vendor payload 可分别重放，旧版无 raw sidecar 的记录继续兼容。
2026-08-06 对和平一模/二模人工复核暴露的公式与墨迹问题完成泛化修复后，真实 provider 与 recorded
replay 仍为 5/5。和平一模被轻微墨迹擦边的 `(II)` 题干恢复为 printed，原半页遮挡框收紧为三个局部交点；
公式题干由整行 crop 改为片段 crop，`∠CBE+∠ACO=45°` 已稳定识别为
`\\angle CBE+\\angle ACO=45^{\\circ}`，不再产生重复 `\\angle B^2` 幻觉。`y=ax²+bx-3` 后混入 `(a`、
`A(-1,0)` 后混入中文等邻接污染会明确 unresolved；和平二模的 `b=-2,c=3` 与 `3√5` 均可由紧凑 crop
完整识别。所有 unresolved 仍作为后续多模态 work order；模型始终接收完整 selection 题目，局部 crop 只作 zoom。
最新审查包位于 `internal/solver-runs/problem-extraction/f2-sixth-review-guided/review/index.html`。单题页按
“区域与版面 → 印刷 OCR → 公式 OCR/crop → 笔迹与遮挡 → typed issues”组织，并在顶部提供人工签核清单；
勾选只辅助本次浏览，不修改 Context。静态 review pack 已生成，F2 标记 COMPLETE 前仍保留一次人工签核。

F2 人工签核只确认观察层是否忠实：selection、OCR框、原始转录、formula crop、origin、遮挡和 typed issue 是否与图片一致。它不要求每个公式都由 FormulaNet 给出最终正确 LaTeX；可靠结果可以作为辅助转录，`unresolved` 结果必须保留原始输出和复核区域并交给 F3。错误结果若被标为 `recognized` 则属于 F2 缺陷，明确降级为 `unresolved` 则属于预期工作流。

本地真实 provider 环境按 [OCR 本地环境安装](ocr-local-environment-setup.md) 准备；Paddle 依赖使用
独立 `server/.venv-ocr`，不进入默认 solver `.venv`。离线 adapter 测试仍不得下载或调用真实模型。

先写失败测试：

- `test_problem_extraction_observations.py`覆盖orientation、layout block、OCR span、formula、reading order和normalized bbox；
- `test_problem_region_proposals.py`覆盖相邻多题、双栏隔离、页脚排除、保守跨页 continuation、稳定顺序和
  用户adjusted selection；跨页 proposal 只有在上一页内容延伸至页底且下一页题号前存在连续内容时生成，
  并强制人工确认。真实跨页 gold 和必须归属题目的印刷配图仍是 corpus 缺口，不能记为已覆盖；
- `test_problem_extraction_handwriting.py`覆盖无笔迹、彩色笔迹、重叠遮挡、黑灰笔画穿过 printed span 和
  确定性 mask；
- `test_problem_extraction_f2_smoke.py`离线覆盖 acceptance 通过/失败、selection-crop OCR 范围、provider
  raw payload round-trip；`f2_provider_ids` 漂移、未入 ledger 的 artifact 和非法 artifact kind 均 fail closed；
-删改原始图片region、交换page或破坏公式时，observation hash和对应evidence必须确定变化；
-候选region遗漏配图、误吞相邻题、selection引用悬空block或使用错误坐标transform时必须失败；
-学生手写答案和辅助线不得产生printed evidence或semantic candidate；
- Observation adapter不得创建entity、fact、scope或goal；
- recorded PP-DocLayout/OCR/formula OCR响应必须能离线重放为完全相同的JSON。

再实现PP-DocLayout/OCR/formula adapter、handwriting/overlap adapter、ProblemRegionProposer、SourceSelection contract和SourceObservation schema。真实provider输出先经过adapter contract归一化，生产逻辑不读取厂商私有字段。本阶段只形成页面观察、区域建议、用户selection和evidence origin，不作数学语义判断。

退出门禁：所有gold source均可稳定生成候选region和SourceObservation JSON；gold SourceSelection可确定重放；同一recorded输入重复运行得到相同observation、mask和artifact hashes；人工确认五题 review pack 后将 F2 标记 COMPLETE。

### F3：Multimodal Evidence Pack 与统一语义 extractor

先写失败测试：

- `test_problem_extraction_evidence_pack.py`断言每次请求都包含完整、有序的 SourceSelection 题目图，以及对应 source、page、selection 和 transform identity；
-整页多题输入不得包含 selection 外相邻题；多 polygon/跨页题必须发送完整的有序 region 集合；
-单页首轮必须只有一张主图且没有 zoom；高可信 OCR/formula 摘要与 unresolved region 清单必须可追溯，明显错误的 raw FormulaNet 输出不得进入 prompt；
- `ObservationRegionIndex` 的 evidence/region、page、polygon 和 artifact 闭包必须完整，错 page transform 或悬空引用时 fail loud；
- `test_problem_extraction_multimodal.py`覆盖文字题、图形题、图中 label linking、坐标轴/几何关系、公式冲突和遮挡复核；
-首轮和 retry 都禁止 crop-only 请求；删除完整题目 artifact 后即使 zoom 齐全也必须失败；
- `test_problem_extraction_llm_contract.py`拒绝无 evidence candidate、自由文本 relation、完整 ProblemIR 输出、capability hint、解法和 expected answer；
-模型读出的学生答案、演算、辅助线或 selection 外内容不得形成题设 candidate；
-模型与 OCR 不一致时必须返回带 source region 的冲突候选或 ambiguity，不能原地覆盖 observation；
-provider timeout、限流、reasoning-only、空响应和坏 JSON 只产生 immutable attempt，不创建语义 child Context；
-相同 recorded request/response 重放得到相同 patch、artifact hash 和 attempt authority。

再实现 `MultimodalEvidencePackBuilder`、统一多模态 provider contract、response parser 和 typed candidate/patch schema。模型始终看完整题目图；OCR/layout/formula/ink 用于提高可读性、提示 reading order、指出不可靠区域和提供 zoom，不作为最终文字或数学事实权威。

五题全部使用同一模型路径。无图、OCR 完整的简单题也不切换到文本模型；架构先以一致性和较少分支为优先，成本与缓存优化留到 E。F1 `attempt.route` 在 v1 中固定写为 `multimodal`，不得出现基于 observation 的动态路由。

退出门禁：五题均能生成完整 evidence pack 并调用同一多模态 contract；recorded replay 稳定；完整题目图调用率为 100%；crop-only、无 evidence 和来源越权输出全部 fail closed。

### F4：Candidate Normalization、Validation、Context 与 retry

先写失败测试：

- `test_problem_extraction_candidates.py`覆盖 scope/entity/fact/goal typed candidate schema、全局 identity、cardinality 和 evidence refs；
- `test_problem_extraction_normalization.py`覆盖 OCR/视觉转录规范化、value parser、scope tree、label linking和primitive fact canonicalization；
- `test_problem_extraction_validation.py`逐个覆盖 typed issue、blocking/retryable 分类和 trusted accepted/locked transition；
- `test_problem_extraction_retry.py`断言 retry 继续携带完整题目图，只追加相关 typed issue、冲突 evidence、必要 zoom 和 locked refs；
- validator issue 必须通过 candidate/evidence refs 确定映射到 `retry_region_refs`；测试禁止 validator 重跑 OCR、读取图片像素或接受 LLM 自由坐标；
-有 region 的单页 retry 生成“完整图 + 定向 zoom”，无 region 时只发送完整图；同一 polygon 重复引用必须确定性去重；
- retry 不能重写无关 accepted candidate，不能使用 selection 外整页、expected answer、Functional catalog 或解法提示；
- issue 集合连续两轮无进展、evidence 缺失或预算耗尽时进入 blocked；
-成功 patch 原子创建 child Context并保留完整 parent/attempt 审计。

先实现 deterministic normalization：

- OCR/模型转录的 Unicode、空白、标点和跨 span 规范化；
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

再实现 validator、`ExtractionWorkOrder`、`ExtractionDecisionPatch` merge 和 retry projector。Validator 对模型候选与 source evidence 做确定性校验；模型不能自行把 proposed 提升为可信 accepted/locked。不可恢复遮挡在这一层保持 blocking，不能靠 retry 猜出缺失像素。

退出门禁：所有候选进入同一 normalizer/validator；所有失败有稳定 code、root evidence 和 retry 边界；失败 Context 不产生 ProblemIR；连续执行相同 retry 序列结果幂等；每轮多模态请求仍包含完整题目图。

### F5：ProblemIR projection 与冷路径集成

先写失败测试：

- `test_problem_extraction_to_problem_ir.py`断言 blocking issue、ambiguous candidate 和缺 evidence 时禁止 projection；
- projection只包含 accepted semantic state，不复制 OCR、bbox、confidence、attempt 或 rejected candidate；
- `test_problem_extraction_solver_integration.py`比较 extracted/authored ProblemIR 的 family admission、answer signature 和 provenance；
-五题从真实 source recorded artifact 完整进入 solver，至少一题继续进入 Track G 并编译 HTML；
-消融测试分别移除 OCR、FormulaNet 结果或 zoom，确认它们只影响辅助质量，不改变“完整题目多模态”主契约；若 FormulaNet 对正确率、retry 或成本没有可测收益，则从生产关键路径移除。

再实现唯一 ProblemIR projector：

-存在 blocking issue 时禁止 projection；
- ProblemIR source manifest 只记录 Context id、source hash 和 schema/version；
-不复制 OCR 内部数据；
- extracted 与 authored ProblemIR 进入同一 family/planner/solver API。

退出门禁：五题 semantic diff 达到要求，补充的 source/semantic corpus 全部通过，solver/lesson-page 回归通过，重复冷路径生成相同 ProblemIR 语义 hash；全链只存在一个多模态语义 extractor，不存在 SourceRouter、文本 LLM 或 deterministic semantic parser 产品分支。

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

每个F0-F5阶段先运行本阶段定向测试，再运行全部已完成F阶段测试；任何阶段不得以live provider偶然成功代替离线contract测试。

Generated/metamorphic门禁：

-重命名 label、OCR span 重排、无关文本和标点扰动；
-调整前端显示尺寸、设备像素比或crop渲染尺寸不改变normalized SourceSelection；
-在相邻题增加文字或配图不得改变已确认目标题的semantic extraction；
-在空白处添加学生演算不得改变ProblemIR；
-给原图添加手写辅助线不得新增几何fact；
-新增无关装饰图片不应自动产生数学 diagram fact；
-删除 figure region时 evidence pack、candidate coverage或blocking issue必须确定变化；
-公式 parser 从成功变为歧义时模型路径保持不变，但 work order、辅助证据和validator结果必须确定变化；
-新增同名 region 必须产生 ambiguity；
-删除 evidence 后 dependent fact unresolved；
-改变题号后 scope 确定变化。

Mutation门禁：

-故意删除evidence ref、交换scope parent、接受ambiguous candidate、复用错误base_context_id或把视觉候选升级为fact，必须在首个负责阶段失败；
-故意误吞相邻题、遗漏目标题配图、把handwritten改成printed或用inpainting结果补事实，必须有对应测试变红；
-故意让evidence pack遗漏完整题目图、模型引用selection外证据、validator接受学生笔迹、retry覆盖locked candidate或projector复制OCR字段，必须有对应单测变红；
-测试不得只断言最终`ok`，必须比较evidence pack、候选集合、issue code、Context parent/hash、attempt、projection和artifact refs。

Integration门禁：

-五题 source 与 authored ProblemIR semantic diff；
-整页多题region proposal与gold SourceSelection比较，并覆盖用户确认和adjusted selection；
-学生笔迹不遮挡时ProblemIR保持不变；关键题面不可恢复时稳定blocked而不是猜测；
- coverage matrix 对缺失类型 fail loud，并能生成给用户的补图需求；
-五题全部通过同一多模态语义 contract；不存在 deterministic-only 或 text-only 产品分支；
-每次首轮与retry请求都向多模态模型发送完整目标题区域和全部题干，局部region只作为补充zoom；
- extracted ProblemIR 通过 family admission；
- answer signature/provenance 与 authored 路径一致；
-至少一题进入 Track G 并编译 HTML；
- planner retry 不得用 prose 猜 extraction gap。
-每次集成门禁均记录 layout、OCR、formula、multimodal extractor的冷路径耗时、token与调用次数；
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
test_problem_extraction_evidence_pack.py
test_problem_extraction_candidates.py
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

F5完成前再运行：

```bash
cd server
uv run pytest tests/solver -q
git diff --check
```

真实PP-DocLayout/OCR/formula/multimodal smoke只在对应offline gate通过后运行，并保存provider版本、输入hash、固定extractor contract、latency、usage和parsed patch；smoke失败必须先匿名化为recorded fixture，再修生产代码。

## 12. 完成条件

-五题保留全部 solver-required entity、fact、scope、symbol 和 QuestionGoal；
-五题原始整页图、gold SourceSelection和派生crop均可追溯，自动region proposal不会混入相邻题；
-printed/handwritten/mixed/unknown evidence分层可审计；学生答案、演算和辅助线不进入ProblemIR；
-关键印刷条件被不可恢复地遮挡时fail closed并给出明确重拍提示；
- coverage matrix 明确区分“五题已覆盖”和“待补图片”，不得用mock或默认值假装覆盖真实source维度；
-需要新增类型时，能向用户给出可从高中题库选择的精确图片特征；确认后的新增图片进入永久gold corpus；
- blocking ambiguity 不被静默解决；
- extracted/authored ProblemIR 产生相同 required answer signature；
- extraction configuration/unclassified error 为零；
- source preflight、阶段 latency 与 layout/OCR/formula/multimodal调用次数可审计；
-所有通过preflight的gold source均调用同一多模态语义extractor，完整题目图输入率为100%；
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
→ F3 Multimodal Evidence Pack + unified multimodal extractor
→ F4 candidate normalization + validation + Context + retry
→ F5 ProblemIR projection + integration
→ F/G image-to-lesson gate
```

F/G 产生完整质量、失败、延迟、token和模型调用指标后，再启动 Track E统一实现最终缓存、分层复用、并发去重和条件式Best-of-N。
