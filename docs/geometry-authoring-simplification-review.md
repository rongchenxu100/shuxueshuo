# 几何表达简化：现行格式与实现审查

2026-09-15：本文件统一为已确认的现行设计。完整架构见 [题意与匹配设计](problem-understanding-and-solver-matching-design.md)，修改前审查过程保存在 [历史归档](validation/understanding-simplified-20260915/historical-designs.zip)。

## 模型只输出整题 IR + 题型声明

以 Aug10 problem-domain/v1 的 root/children 为基础；新试验契约为 problem-domain/v2。root 及各 children 都包含 label、source_text、entities、facts、goals、children、uncertainties。没有独立 parts 树，没有 transcription/domain/match 三份子对象。

LLM 使用 A、B、k 等原名，将本题临时定义展开为具体对象上的基础 fact，选择已注册 family 或明确 unmatched。代码负责内部 ID、词法名称解析、受控表达式、校验、修订和审计。代码不会根据“k倍四边形”等名称套用内置模板。

## 关系审查对照

|原复杂模型表达|当前模型表达|由代码承担|
|---|---|---|
|quantity_relation + 两个 angle_measure|angle_equal angles=[BAC,DAC]|角顶点解析、对称规范化|
|quantity_relation + multiply + number + angle_measure|angle_ratio angles=[BDC,ABD], ratio=[2,1]|交叉相乘、比例方向和量纲|
|两个 segment_length + 等式|equal_length segments=[AB,CD]|端点引用、无向线段|
|递归长度倍数表达式|length_ratio segments=[BD,CD], ratio=[4,1]|受控系数表达式|
|triangle_area + divide|find_area_ratio triangles=[ACD,ACB], in_terms_of=[k]|面积无向、分母义务|
|triangle_area 等式/倍数|area_equal / area_ratio / area_value|量纲与顺序|
|angle_measure + tan + quantity_goal|find_tan angle=ACD|度数制正切、定义域义务|
|midpoint + prefixed refs|midpoint point=E, segment=OB|局部名字解析|
|原题命名的交点|intersection point=O, segments=[AC,BD]|使用题面原名；interior 不默认 true|
|新增交点 + 两段长度比例|cut_ratio segment=BD, by=AC, ratio=[k,1]|代码解析交点、保持端点比例方向|
|为平分关系新增交点 + midpoint|diagonal_bisects polygon=ABCD, bisector=BD, bisected=AC|比较时展开为内部交点和中点关系|
|polygon 实体+下标引用|polygon vertices=ABCD|保留有序顶点，不按集合排序|
|parallel/perpendicular first/second|parallel/perpendicular segments=[AB,BM]|端点及交换等价|
|point_on_ray + ray entity ref|point_on_ray point=C, ray=BM|起点方向保留|
|coordinates + 两个 QuantityTerm|coordinates point=P, coordinates=[m,m^2-1]|受控代数解析|
|extremum_goal + 递归量树|find_minimum expression=length(E,G)+length(F,G), variables=[G]|内部运算节点与范围引用|
|definition + formals + definition_use|各问实际基础 facts 与 any_of|无题内术语分派，无模板解释器|
|source_unit_ids + 反向覆盖表|保留各层 source_text|保存整图、原文、调用审计；无逐句映射门槛|

以上是阅读示意，准确字段见 [自动生成的操作表](validation/understanding-cut-ratio-20260915/operations.md) 与 [模型 schema](validation/understanding-cut-ratio-20260915/model-schema.json)。示例中的数学字符串在 JSON 中均应加引号。

复杂算式仍允许受控字符串，包含精确数字、参数、加减乘除、sqrt、有界整次幂，以及 length、angle、area、x、y、degrees、length_units、area_units、tan；代码生成内部运算节点。拒绝面积加长度、几何对象冒充标量、零分母、显式退化与非法代码字符串。

## 题内定义不是内置数学类型

“k倍四边形”是本题给出的定义，它将基础关系打包，不是该名字对应的通用 Solver family。模型需要理解定义并应用到每问，不能只输出名字等待代码硬编码展开。

本题的基础关系应包括：有序四边形、对角线交点、被平分对角线的中点关系、另一条对角线两段的长度比，以及 k≥1。未知方向/选择用通用 any_of 保留。四分支金标保留为参考表达；允许在已给平分条件下输出等价的两分支，由代码验证等价，不强制按分支数量验收。

图1的 AECD 有对角线 AC、ED，其交点可以由已知共线关系确认是 O。局部名字 X 仅是另一种表示，不表示 X≠O；代码仅依据明确的交线及共线条件确认同一交点，不任意合并独立声明。图1～4缺图仍保留；用户已确认本题 □ABCD 表示平行四边形，因此本题金标采用 parallelogram。此确认不作为其他题的符号解释规则，不默认交点内部或比例方向。

模型侧不再出现 definition、parameters、local_witnesses、definition_use，也不输出 p1_A/p2_A。截线比例与对角线平分使用直接关系，不让模型新增辅助点名字。原题命名点仍保留原名；其他无法表达的未命名对象记 unstructured。

## 简短提示与独立 few-shot

提示说明临时定义必须以本题为准，将它展开到各问具体对象，保留原文和不确定分支，不求解。

定义 few-shot 改为“合邻三角形”：某顶点邻边相等且该角为60°，或按顶点顺序邻边比2:1且该角为直角；ABC 在 A 点满足定义，另给 ∠BAC=60°。输出独立的 60° 条件和包含两组完整条件的 OR，它仍是合法的完整展开示例；在60°条件下省去不可能分支的等价表达也可接受。示例构造器与 schema 使用同一操作目录，并经过真实解析器验证。独立测试使用改名、同名改定义、改作用顶点、关系组合与 OR 的其他定义，不把 few-shot 本身充当泛化测试。

提示词源码：[prompt.py](../server/shuxueshuo_server/problem_understanding/prompt.py)。

## 定义展开边界与统一 OR

现行规则：定义代入具体对象并展开基础关系，接受数学等价的简洁表达；不能确定等价时保留所有可能与比例方向。完整保留题设，不猜未给条件、不计算所求。

所有 fact 统一由 `kind` 分派，OR 采用以下结构，旧的仅含 `any_of` 字段的形式不再接受：

```json
{
  "kind": "any_of",
  "branches": [
    [{"kind":"equal_length","segments":["AB","AC"]}],
    [{"kind":"right_angle","angle":"BAC"}]
  ]
}
```

一个分支内的 fact 同时成立，分支之间至少一个成立，允许多个同时成立；顶层 facts 已表示同时成立，不引入 all_of。至少两个非空分支，分支内可嵌套 OR；输入及展开总量仍受资源限制。

原始IR保持模型返回，不把OR分支提升为无条件题设。比较使用独立工作副本，支持证明冗余/不可能分支不增加解集；证明不了则返回 not_proven_equivalent，不要求模型模仿金标的字面分支数。各分支的字段、对象引用、量纲和表达式安全校验照常进行。此处通过只表示表达合法，不表示已经证明整组几何条件可满足。

人工金标仍保留完整四分支与明示中点作为参考，但不以它的字面结构作为唯一正确输出。用户对本题平行四边形的确认已记入人工金标；原图、观察、旧真实调用记录和生产五题金标不变。

## OCR 简化

OCR 本身不移除。原始观察继续保存；模型只接收页序、文字分行、公式候选和少量中性提示。unknown 或没有 layout 命中的文字不能丢弃，分母行不能丢弃。手写/混合信息仍提示可能为批注；不把来源候选升级为题干。坐标、观察 ID、置信度、provider/内部诊断字段不进入首轮辅助视图。

不同公式候选保留；只做同一来源位置的可靠完全去重。生产复核仍使用完整观察，本步骤不改变复核触发条件。

## 实现与验收

隔离包：[problem_understanding](../server/shuxueshuo_server/problem_understanding/)。

本次实现范围为契约、编译校验、不可变候选、patch、安全渲染、简洁输入、离线回归及本题一个新真实 smoke。生产入口、新 Solver adapters、产品 unsupported、数据库/API、部署和清空数据属于后续步骤。

尺寸及结果统一记录于 [本次验收目录](validation/understanding-simplified-20260915/README.md)，历史的 18,599 / 32,838 / 21,389 字符基线不改写。不能用历史成功样本拼接本次结果，也不能把本次 IR 合法误报成 Solver 投影成功。

实际状态：离线 149 项通过；唯一一次真实抽取在第（3）问截断，门槛未通过。详见 [失败诊断](validation/understanding-simplified-20260915/live-diagnosis.md)。没有追加调用或修改金标。

组织规则另用一个短示例明确编号下的两个图景、局部参数与未命名交点；role 缩减为原文明示的 fixed/moving。父节点不再复写子节点原文。见 [组织规则修复验收](validation/understanding-organization-fix-20260915/README.md)。

定义展开边界与统一 OR 已同步实现，离线 169 项通过，6 项真实测试未启用；没有新模型请求。现行快照及大小见 [定义规则修复验收](validation/understanding-definition-fix-20260915/README.md)。


## 缺图处理与推理观察（2026-09-15）

重复编写 JSON 暂不干预，只观察；不加入限制推理区的提示词。图形引用必须与实际图片区分，未提供的图形在所属层写 missing_figure，不能据引用补图形性质。

缺图一律保留 IR 并阻断后续流程，由用户补图；没有“文字充分可继续”的例外。独立候选新增 continuation 和补图展示样例。生产前端/API 尚未接入新契约，待接入时必须展示缺图、已提取题意和补图操作，并在任何后续调用前拦截。详见主设计 §12。

## 最新实施状态：v8 截线关系

已实现 cut_ratio、代码内部交点和有依据的同点规范化；层级、局部参数、数字直接代入、平铺 OR 与首选操作提示同步更新。离线 207 项通过，6 项真实测试未启用。此前各阶段数字为历史记录；本轮真实调用结果单独记录于 [v8 验收](validation/understanding-cut-ratio-20260915/README.md)。

本轮 v8 真实验收：**未通过**，一次语义调用、两次网络尝试、141.131秒。首次推理耗尽预算；第二次合法JSON使用cut_ratio且不再新增点名，但图1定义未展开、局部k≥1及四幅缺图标记遗漏。缺图门禁因漏标没有触发，结果仍为隔离候选，未进入后续流程。代码和金标未在测试后修改，未自动重跑；详见 [本轮完整报告](validation/understanding-cut-ratio-20260915/README.md)。


## v9：可表达的未定分支、用户确认与已接受遗漏（2026-09-15）

- 未确定哪个分支成立不等于不能表达。已有关系及 any_of 能表达的定义必须展开，unmatched/source_text 不能替代 fact；直接代入和保留分支，不要求先证明、筛选或求解。允许原先已确认的等价表达，不恢复机械四分支门槛。
- 修改现有“合邻三角形”示例：邻边相等且角60°，或邻边按顶点顺序比2:1且角90°；另给角60°。示例直接展开两组条件，返回unmatched仍保留全部，展示无需提前求解。不加入k倍四边形专用提示或运行时类型。
- 图形未提供或无法确认是否提供，都填写missing_figure，文字区分实际缺图/待确认。代码提示用户确认或补图，不要求模型承担最终拒绝决定；仍先提取可读条件。此次没有增加独立视觉调用，不能保证模型不漏报。
- 新入口IR结构校验并不自动验证自然语言条件完整性；独立单次smoke没有LLM纠错循环。通用不等式识别不能可靠解决定义应用、局部归属和等价隐含条件，故本轮不加题目特定的遗漏拦截。
- 按用户明确选择，本题三个局部k≥1缺失不单独否决验收。以夹具acceptance-policy.json列出准确作用域、允许遗漏事实、理由及金标修订；政策冻结进请求审计，仅用于测试验收，不发给LLM，不改变生产校验器或金标。
- 严格diff继续报告不等价；单独acceptance.json可报告accepted_with_omissions。明确错误下界、其他条件/定义遗漏、错误比例、缺图漏标不在允许范围。旧批次记录不改判：v8仍有定义和缺图问题，按新政策回放也未通过。

本轮只执行离线回归，没有付费真实请求。示例、schema、尺寸及验收见 [v9报告](validation/understanding-v9-definition-20260915/README.md)。


### v9 最新真实验收（2026-09-15，另一次明确授权）

v9按用户批准的局部k≥1遗漏政策通过：图1定义已完整展开，四幅缺图均标记并触发阻断；严格语义仍有已批准遗漏，不宣称完全等价。一次语义调用、两次网络尝试、145.262秒，首轮仍推理耗尽。未执行下游。完整结果见 [v9真实报告](validation/understanding-v9-live-20260915/README.md)。


### 通用平分与比例冲突校验（2026-09-15）

已在独立简洁 IR 校验器实现基础关系检查：midpoint/diagonal_bisects 确定的两段等长，与同一交点的 cut_ratio/length_ratio 联合判断；精确不等比例或明确参数约束导致矛盾时，输出关联事实 ID 和定向修复说明。不依赖题名、family 或金标，不改提示词/schema。保留 OR 和原候选，只有全部备选分支都被该检查反驳时拒绝；父层继承、局部同名和不同交点分别处理。

离线 258 项通过，6 项真实测试未开启；没有新增模型请求。原 v9 正式返回仍按既定遗漏政策接受；反写第三问截线对象的副本被通用校验拒绝。新校验尚未接入生产入口，第三步才将报告交给 LLM 自动修复。生产已有“空正式内容原请求重试一次”和“草稿校验错误带反馈修复”两条路径，不能混称第二轮修复。详见 [校验与重试边界](validation/understanding-geometry-consistency-20260915/README.md)。


### v10 七题抽取实测（2026-09-15）

新增用户提供的函数量词题及人工图片金标。简洁 IR 补充通用 quantified_relation（forall/exists、实数/区间、局部变量）和 find_range；原五题、k 倍四边形、新题使用同一单轮抽取测试入口。新题使用明确标注的人工文字辅助，旧五题使用真实观察适配器回放；不改生产入口。

离线279项通过；七题真实批次0/7通过，共7次语义调用、8次网络尝试。河西/西青输出截断；其他五题因当前对象声明、命名或表达式引用校验阻断。新题量词和目标已正确抽取，但f(x)-g(x)等已定义函数引用尚不能被解析器转换，不宣称完成实时验收。没有新增自动修复轮、临时改金标或重复调用。完整记录见 [七题集成报告](validation/understanding-seven-20260915/README.md)。


### v10 豆包七题对照（2026-09-15）

按用户要求保持七题实际消息、schema、图片、金标、registry及允许遗漏政策不变，改用doubao-seed-2-1-turbo-260628，enabled/low、非流式JSON object，仍为单轮抽取测试。实际1/7通过：k倍四边形严格语义一致且保留四幅缺图阻断；其余六题被对象声明、命名、量纲或函数引用转换校验阻断。七题均完整JSON、题型声明均符合金标，但不等于IR全部合法。共7次语义调用、7次网络尝试；未改生产配置、未追加修复或重跑。详见 [豆包对照报告](validation/understanding-seven-doubao-20260915/README.md)。
