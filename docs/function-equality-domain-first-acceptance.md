# T1 域优先比较：真实新题与原题收束两层交互验收

日期：2026-10-28。范围是修复同一函数判定的通用准入、数学执行和原题收束，不新增专题题号。本题来自用户本轮实际拍题记录，区别于已用于开发的 Q19、Q20。当前状态：历史失败及首轮新拍题模式冲突完整保留，修复后真实上传已复核并求解为 C；原候选全流程、两层交互和独立冻结 8 对结构留出通过，新真实录制的离线回放及认证 API 也通过。浏览器自己做、刷新恢复、独立 AI 回放及只读回看均通过。

相关约定见 [T1 设计](function-equality-problem-type-design.md) 与 [专题和拍题开发流程](topic-and-photo-learning-development-workflow.md)。不能用历史识别通过、离线数学通过或浏览器截图，替代新的真实上传与完整交互验收。

## 1. 实际失败与题源

历史记录 `8f8b3caf3eb5` 的原图提取和复核均已通过：`reviewed_candidate`、`source_reviewed=true`、`features_ok=true`，耗时 47.62 秒，共 2 次语义调用、2 次网络尝试。随后 Stage2 目标为 `unsupported`，没有选中题型。问题发生在结构准入，不是拍题识别未读清函数。

旧 T1 把“对应关系能否由现有化简族证明”提前作为整题准入条件。A 项的三次被开方数、B 项的一般分式、D 项的根式乘积触发范围外，即使其中 B、D 仅比较原定义域就能得到结论，也未进入 M8。

原始上传整页、产品旋正页、原色矩形裁片、实际送模灰度图与裁题元数据见 [题源 manifest](../internal/senior-high/source-images/function-equality-domain-first/manifest.json)。矩形坐标为 `[147,526,981,1031]`；整页旋转、裁片像素以及 `question_png` 结果均逐项核对。所有 PNG 保留实际记录字节，没有重绘、遮罩、改字或以浏览器截图替代。实际记录中的 `original.png` 是原色裁片，不把它误称为整张原上传图。

历史候选仅以 [public candidate fixture](../server/tests/solver/fixtures/function-equality/domain-first-photo-public-candidate.json) 归档，不复制账户、会话或运行配置。原图有手写批注，以下金标由数学推导独立确定。

## 2. 数学金标

原题问“下列各组函数表示同一个函数的是”。题面没有明示单选或多选，因此保留 `selection_mode=unspecified`；不能由常见题型或算出的正确项数量反推原题模式。按后续确认的产品规则，未注明选择模式默认按不定项选择处理：选出全部符合题意的项、项数不预设、精确集合评分。此规则明确答题行为，不回写历史模型录制。

| 项 | 原函数 | 域优先证据 | 结论 |
| --- | --- | --- | --- |
| A | $f(x)=\sqrt{-2x^3}$，$g(x)=x\sqrt{-2x}$ | 两域均为 $(-\infty,0]$；在 $x=-1$ 时，两值为 $\sqrt2$ 和 $-\sqrt2$ | 不同，对应关系反例 |
| B | $f(x)=x$，$g(x)=x^2/x$ | 左域为 $\mathbb R$，右域为 $\mathbb R\setminus\{0\}$；约分不恢复原分母禁取点 | 不同，跳过对应关系比较 |
| C | $f(x)=x^2-2x-1$，$g(t)=t^2-2t-1$ | 两域均为 $\mathbb R$；绑定自变量改名后，对所有输入都为 $u^2-2u-1$ | 相同 |
| D | $f(x)=\sqrt{x-1}\sqrt{x+1}$，$g(x)=\sqrt{(x+1)(x-1)}$ | 左域为 $[1,+\infty)$，右域为 $(-\infty,-1]\cup[1,+\infty)$；$-1$ 仅在右域 | 不同，跳过对应关系比较 |

最终正确标签集合为 **{C}**。不能将根式乘积直接合并后再求左式定义域，也不能用平方相等代替原式输出相等。题面模式未明示时，完成四项判断后使用精确标签集合收束；它不把原题改记为多选，也不因为只有一个正确标签而改记为单选。

## 3. 通用能力与支持边界

M8 先复用 M1 从原表达式求两域；域不同即以合法输入差异给出“不同”。只有两域相同时，才进入对应关系证明。能求域不等于一定能完成对应关系证明；后者超出范围时返回未判定，不能将其记为不同，也不能提前生成最终选项答案。

本批 M1 的固定有理系数多项式域条件扩至六次，并保留原式位置、分母非零和平方根非负证据。含参数的 M6 仍保留既有二次边界。对应关系使用受预算限制的有理式及实根式证明，保留符号分区与原定义域；复杂根式和、超出次数或符号分区预算的结构仍不自动承诺可解。完整机器边界以最终源码契约和拒绝回归为准。

正向证明必须覆盖全部共同定义域；负向证明提供一个经原式核验的反例。独立验证重新检查原树定义域、分区覆盖与证据，不将有限采样相等提升为恒等。

## 4. 离线全流程与交互门槛

[定向集成测试](../server/tests/solver/test_graph_stage_three_function_equality_domain_first.py) 从历史真实候选走 IR→Stage2→Stage3，并用实际执行导出课程、通过产品编译器形成内存 bundle。测试不手写替代性的题目步骤，也不声称重新调用了模型。

断言包括：

- A、B、C、D 四项均有独立作用域和单项 `choice` 结论，八次 M1 调用完整保留。
- A 保留输出反例，B、D 不生成对应关系卡，C 保留变量改名后的全域结论。
- [实际 bundle 验收脚本](../tools/tests/graph-walk-domain-first-acceptance.mjs) 在每个未完成步骤尝试提前提交 C，必须停留；任一单项错判不推进。
- 保留历史 `single` 分支的单选回归：四项完成后才进入原题 `choice`，仅标量 `C` 通过。新增 `unspecified` 分支必须保留原模式、按精确集合 `['C']` 评分，不能误收标量或带多余标签的数组。
- AI 使用独立进度；学生提交 C 后刷新恢复仍已完成。
- 从同一实际 bundle 导出的服务端评分契约必须保留单选原题身份；逐一删掉任一证据步骤的通过记录，服务端都拒绝终答。

首轮实际链路发现并修复了一个额外断层：原题单选的 native contract 投影没有保留 `source=original_choice`，导致前端能够完成、服务端契约却拒绝。现在带完整选项前置约束的原题单选保留身份；普通旧单选契约保持兼容。完成态提交也不再改变本题状态、事件或反馈，服务端拒绝使用新请求身份重交已完成终答。

上述实际链路最终 **5 passed**：题源字节与像素核验，以及历史 single、新 unspecified 两种模式分别走四项完整数学执行、实际课程导出到前后端两层交互。最终验收使用冻结后的完整源码，耗时 34.56 秒；原历史 fixture 未被改成 unspecified，新分支仅使用明确标注的测试副本。导出链包含逐个遗漏入口及证据记录的拒绝校验，未明示模式从原目标、结果到 handoff 均不改变。

新增识别边界回归保留 `abs(x^3+1)` 可准入，拒绝条件改用超出六次范围的 `abs(x^7+1)`；识别与独立留出联合运行 **28 passed**（19 项识别、9 项留出），与其他集合有重叠，不相加为独立总量。

## 5. 独立冻结结构留出

在运行扩展比较器前，独立冻结 8 对结构输入，涵盖不同系数、正负定义域、单点域、一般分式与显式去点域。金标通过数学符号替换、原算子限制和精确有理式推导获得。冻结 SHA-256：`fe4b36f579d3265c37f3ca2163e5d24d4e6b10a9f30c920648c7f7be9944248b`。

冻结文件在实现代理宣布数学源码完成前不向其披露。源码冻结后首轮执行 **9 passed**（8 对输入和 1 项冻结哈希校验），每对还交换左右分别比较并独立验证。原题金标及冻结文件均未根据执行结果修改。

归档：[冻结结构输入](../server/tests/solver/fixtures/function-equality/domain-first-heldout-frozen.json)、[独立验收测试](../server/tests/solver/test_graph_function_equality_domain_first_heldout.py)。这些是结构验收，不计为额外真实照片。

## 6. 真实模式冲突修复与新拍题验证

首轮新浏览器记录 `60809cd078af` 在 73.952 秒后以 `workflow.oscillation` 结束，没有成功复核。extract 猜为 single，review 正确指出题面未明示模式，要求数学目标与公开 choices 同步改为 unspecified；但旧比较目标 schema 不接收该值。第一次 repair 只改公开 choices，触发两侧模式不一致；第二次又恢复 single，回到原候选而停止。四次调用为 extract→review→repair→repair，该记录不计为成功。

已同步记法 schema、图谱提取 schema、Stage2 特征 schema 与提取／复核／修复共用规则：groups/shared_baseline 接收 unspecified，pair 仍只能 none。题面明确单选或多选时照实保留；未明示时不报题目缺失、不猜模式，两处字段必须一致。修复权限仍限于复核指明的两个 selection_mode 字段，不能顺带改公式、极性或正确标签。

实际失败候选、复核和两次修复候选已[最小归档](../server/tests/search/fixtures/function-equality/domain-first-mode-oscillation-20261028/recording.json)。[回归测试](../server/tests/solver/test_graph_function_equality_selection_mode.py) 保留历史失败序列可复现，并通过 `SearchStageOneContract` 与真实 `run_workflow` 路径验证正确修复→再次复核；最终确认使用离线 provider 探针，不冒称真实模型重新复核。新增 12 项与旧 IR、识别、局部修复、方向和 Q19 IR 联合 **97 passed**。

源码冻结并重启服务后，从原失败页面正常重试得到新记录 `10861330e2cf`。仍使用真实原色裁片经相册上传、选择整张图；实际送模图与开发核对图 SHA 均为 `aa81810476271e74fd8b1f86837c0e7131767c8c0af2adf859a58866018fff9d`。浏览器相册画布编码与服务端正常预处理使它不同于历史灰度图的 `85b96…` 字节，各角色图片哈希单独归档，不能混称原始上传字节。

本次实际模型仅 **extract→review**，耗时 **29.199 秒**，2 次语义调用、2 次网络尝试，无 repair，状态 `reviewed_candidate`，`source_reviewed=true`、`features_ok=true`。目标和公开 choices 均保留 unspecified。成功响应文本、原候选、复核、请求与耗时记录已[脱敏归档](../server/tests/search/fixtures/function-equality/domain-first-browser-recorded-20261028/recording.json)；只清除 provider 文件／请求身份和传输 URL，没有改写数学或响应文本，也没有复制账号、会话或配置。

真实执行 run 为 `0d973bf242f549449c8c48178e14b693`，状态 `completed`、目标 `solved`，四项依次为不同、不同、相同、不同，原题精确标签集合为 C。数学课包指纹为 `b0fd56f7f08847f41d9178b41af867b80722e91ac89c9a296c276a7afff1380f`；本次执行的全部冻结实现文件与当前源码逐项比对，零漂移。[实际求解摘要](../server/tests/search/fixtures/function-equality/domain-first-browser-recorded-20261028/lesson-verification.json) 记录真实 result 哈希，不以离线重放 run 冒充该次执行。

[新录制回归](../server/tests/search/test_function_equality_domain_first.py) **2 passed，18.04 秒**：逐次回放真实提取／复核响应并检查图片、响应文本和归档文件哈希，再经认证拍题 API 完成 Stage2→Stage3→四项交互投影→精确集合 handoff。断言 B、D 跳过对应关系卡、A 和 C 保留对应关系证据、终答保留 unspecified；重复启动和读取 snapshot 复用同一次执行。测试禁止实时模型 provider，不产生新模型调用。

浏览器自己做已完成 14 次评分决策、12 张展示卡：D 项故意错判“相同”被拒且终答仍锁定；改为“不同”后解锁原题；终答没有预选或提前展示结论板，空集合与 B 均被拒，仅选 C 通过。刷新后仍为“练习已完成”；切换 AI 时 A—D 从独立未完成态开始，自动回放 14/14 后显示“回放已结束”，切回学生仍保持完成。已完成 A 项只读回看保留 $x=-1$ 时 $\sqrt2$ 与 $-\sqrt2$ 的原式反例，不提供可编辑答案，返回当前步骤仍保持完成。

浏览器证据：[首次模式冲突](../internal/senior-high/source-images/function-equality-domain-first/acceptance-first-failure.png)、[学生完成](../internal/senior-high/source-images/function-equality-domain-first/acceptance-student-completed.png)、[独立 AI 完成](../internal/senior-high/source-images/function-equality-domain-first/acceptance-ai-completed.png)、[A 项只读反例](../internal/senior-high/source-images/function-equality-domain-first/acceptance-readonly-a.png)。这些是验收截图，不是识别题源。

隔离环境为 `/private/tmp/sss-domain-first-20261028`，实例名 `domain-first`；浏览器验收使用独立本地服务。实例最初 generation 未启用时的拦截未调用模型，不计入上述真实调用次数。历史 `8f8b3caf3eb5` 和首轮 `60809cd078af` 均保留原失败状态。测试不写日常数据，不以本地验收代替生产或实体手机验收。

## 7. 最终服务与回归状态

验收完成后已重启日常本地 8779 服务：旧 PID 71880 正常停止，新 PID **87611** 启动成功；拍题入口和函数专题均 HTTP 200。`check-learning` 通过：95 节点、295 边、47 题、58 条路线、359 个评分步骤；不变更已有学习记录，不新增专题题号。

定向验证按层记录，不对重叠用例简单求和：T1 数学核心 220 项；T1 联合回归在选择模式修补前 343 项通过，随后新增／相关模式上游 97 项、下游 12 项、实际完整导出 5 项与既有完成回归 26 项均通过；独立留出 9 项；最终 Node 430 项；认证与提交 18 项；新真实录制回放与认证 API 2 项。M1 域侧联合首次 310 通过、1 项 Q04 测试失败，核实是测试写死被打乱的选项 ID，按学生可见语义修正后 Q04 与 M6 邻域 256 项通过，运行实现无改动。四个 builder `--check` 均 changed=0，Ruff 与 diff 检查通过。

本轮没有提交或推送代码。浏览器范围为桌面内嵌浏览器；不声称实体手机或生产环境验收。

## 8. 未注明模式的默认规则补记

2026-10-28 后续确认：未注明选择模式默认按不定项选择处理。已同步提取／复核／修复共用规则、公开内容规则、记法 schema 描述与终答提示。来源仍保留 `unspecified`；终答提示选出全部符合项，不预设项数，漏选／多选均不通过。明确单选保留原交互。

本次定向验证：来源规则与完整求解／handoff 24 项、两层交互 20 项、状态／回放／构建 26 项通过，覆盖 0／1／2 个正确标签。首次未配置隔离数据库导致 12 项测试 setup 拒绝，配置独立实例后重跑全部通过。示例录制的原始 14 个动作重放通过，生成物签名已更新，四个 builder `--check` 均 `changed=0`。本次未重新调用真实图片模型；§6 的真实拍题记录保留原始内容。日常后台再次重启为 PID **90173**，8779 拍题与专题入口 HTTP 200；本次启动的隔离数据库已停止。未提交、未推送。
