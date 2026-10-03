# 当前编写契约

本说明对应 `site/assets/practice/` 与 `tutor_demo` 运行时。它帮助定位字段，不替代读取当前代码。完整的可运行样本是仓库中的 Q01；不要维护另一份复制后逐渐过期的页面模板。

## 学生 HTML

页面需加载现有公共样式、站内 KaTeX、`math-text.js`、`components.js`、`context.js`、`runtime.js`，保持脚本依赖顺序。复用 Q01 的主区域、步骤/历史容器、完成区、输入栏、网络状态、重试按钮、数学项菜单与无障碍播报节点。

`script#practice-config[type="application/json"]` 包含：

| 字段 | 用途 |
| --- | --- |
| `id`、`version` | 与后台教师 JSON 一致；更改契约时协调更新两端版本 |
| `variables` | 当前模板支持的数学变量；不要假设任意表达式解析已经实现 |
| `method_question`、`methods` | 首次选择问题及 `{id,label}` 方法列表 |
| `routes` | 路径 ID → 节点数组，顺序是学习顺序 |
| `completion` | HTML 完成模板 ID，例如 `lesson-completion` |
| `comparisons` | 可选，路径 ID → 完成后对照其他思路的模板 ID |

节点的公共字段为 `id`、`title`、`question`、`interaction`、`expected_answer`、`feedback`。HTML 配置还包含 `submit_label`、`display`，选择组件可另有 `board`。`display` 是模板 ID，或 `{field, options: {选项值: 模板ID}}`，按已选思路展示。选择组件还可使用 `preview: {选项值: 模板ID}`，在选择后、确认前展示预写的展开式；预览本身不推进节点，不代表运行了计算工具。Q02 的和/差平方为实例。

HTML 模板是题目专属内容。当前简单替换支持 `first` / `second`（本步两个槽位的值）、`first_math` / `second_math`（对应数学显示标签）、`variable` / `other`（所选变量与另一个变量）、`choices` 中已有字段以及 `uid`。全部替换值先转义，不支持运行 JS、任意算式求值或复杂模板条件。重复渲染和历史路径中的 SVG 标题、详情折叠等 ID 使用 `uid` 避免冲突。

注意实际支持范围：当前 `variable` / `other` 面向两个变量；根号槽位及正项标记是二元基本不等式。若新题需要系数项、多个变量或自由表达式，先确定需要的输入形式，再扩展相关公共能力。不要把 `m` 换成一长段 LaTeX 就假定组件和校验都支持。

题干等固定数学内容可以直接使用 HTML；题干、节点、预览、已完成模板和历史尝试中的 `data-math-text` 均使用公共 KaTeX。采用 `$...$` 时将标记放在仅含文本的叶元素上，不要覆盖嵌套的槽位按钮；同一 DOM 元素只渲染一次。

完成态同样复用已有视觉结构：基本不等式主展示保留方框、圆圈及学生选项顺序，不退化为一行无标记公式；配方主展示复用 Q01 的 `function-conversion`、箭头与 `square-term` 高亮，明确原目标如何转化为平方项的最值。详细计算写在下方推导区。完成态模板也用于历史路径，验收时同时检查两处。

每个完成态都由两部分组成，缺一不可：上方可视化只展示本步最核心的概念或关键点（图像、清单、情形对照等），不展示计算过程，也不重复推导里已经写出的句子；下方 `<details class="details" id="{{uid}}-节点ID-derivation" open><summary>完整推导</summary>…</details>` 用 ∵、∴ 写出本步可直接写进答卷的推导，每行一个 `<p data-math-text>`。可视化不能代替推导；推导只写到本步结论，不提前写出后续步骤的结果。各步推导依次连起来就是完整答案（/2/q01 为例，测试会检查每个完成态都有推导）。

基本不等式完成态使用公共 `completedAmgm`，与作答态共享公式结构，左右两侧（包括根号内）均保留圈框。HTML 使用 `<div data-completed-amgm data-first="{{first}}" data-second="{{second}}" data-first-label="{{first_math}}" data-second-label="{{second_math}}"></div>` 挂载，不再每题手写圈框公式。对话气泡用左右位置和底色区分身份，不显示“你／老师”文字标签；身份保留在无障碍标签中。

表达式圈框按内容撑开；基本不等式在窄屏可于左右两侧之间换行，不拆开数学项或根号。新增含括号、分式等较长项时，检查作答态与完成态的内容是否留在圈框内，并验证窄屏；不要用题目专属样式修补公共组件。

对话复用 `PracticeMath`：消息和 Context 保存普通文本，公式使用 `$...$`（行内）或 `$$...$$`（独立推导），也兼容 `\(...\)` / `\[...\]`。通用 Prompt 要求 LLM 按此格式输出，JSON 中反斜杠需要转义。当前、已完成步骤及历史路径的对话使用同一渲染器；不将消息当 HTML，不猜测转换没有定界符的旧公式。单个公式解析失败时保留原文，其他公式继续渲染；窄屏长公式在气泡内滚动。

预写的 `feedback` 与 `completion_reply` 也遵循同一公式标记约定，不能仅依赖 LLM 格式要求。公共 controls 的即时反馈和记录到对话中的反馈均支持数学渲染；新增题目需检查错答反馈中的指数、分式等，而不仅检查正确路径。

## 现有组件

统计口径：当前有 10 类作答交互（下表，`checklist` 为恒成立专题新增），另有 `completedAmgm`、`quadraticGraph` 两类只读展示；槽位、操作按钮与辅助标记不重复计入教学组件。各题覆盖与使用量见[设计文档第 4 节](../../../../docs/interactive-lesson-shared-runtime-design.md#4-组件与未来探索能力)。

| `interaction.type` | 配置 | 预期答案 |
| --- | --- | --- |
| `structure` | `terms`：两个槽位的候选数学项 | `{terms: [...], fixed: "sum"或"product", target: "product"或"sum"}` |
| `amgm` | `terms`：二元基本不等式正项候选 | `{terms: [...]}`，成对项顺序可交换 |
| `equality` | `terms`：取等的成对项候选 | `{terms: [...]}`，成对项顺序可交换 |
| `symmetry` | `terms` 为不变/改变等判断值，`slot_labels` 分别标识条件、目标；HTML `board` 用 `.sym-check` 逐行展示原式与交换后，并以 `<span data-judgment="i"></span>` 放置第 i 个判断（缺省时判断排在画板下方） | `{terms: [...]}`，按位置分别校验 |
| `substitution` | 定义形态：`terms` 是和、积等表达式候选，`slot_labels` 声明 `s,p`。点选形态：`slots` 只有一个，含 `label`、`names`（新变量名，个数即最多可换的整体数）、`options:[{value,label}]`；页面节点另有 `board` 与 `scope_boards`（见下文“点选换元”） | 定义形态 `{terms: [...]}`，有序定义；点选形态 `{terms:["对象"]}`，多个对象按候选顺序用 `|` 连接 |
| `homogeneity` | `terms` 为整数次数候选，`slot_labels` 标识各表达式，个数即格数（缺省两格）；可选 `slot_shapes` 逐格指定 `square`/`circle`。两格时 HTML board 用 `.deg-equation` 排成“目标 × 条件 = 相乘后”，以 `<span data-degree="0"></span>` 与 `1` 声明槽位，`<span data-degree-total></span>` 放置相乘后的次数（缺省时排在画板下方）。目标两项次数不同时用三格（Q13）：board 加 `.deg-board-terms`，按“第一项 + 第二项 ┆ 条件表达式”排列，用 `.deg-sep` 分隔，`data-degree` 为 `0`、`1`、`2`，不显示相乘后的次数。需要先拆项再判断时（Q15），在 `.deg-equation` 前放 `.deg-split` 一行，内含 `.deg-split-label` 与分段不换行的拆项等式，两列改为判断拆出的两组 | `{terms: [...]}`，有序次数；两格时系统计算两者之和 |
| `rewrite` | `slots` 固定两个：作用范围与乘数；各有 `label` 和独立的 `options:[{value,label}]` | `{terms:[范围值,乘数值]}`，有序并按槽位候选域校验 |
| `fill` | `terms` 为候选值，`slot_labels` 标识各槽位，个数即格数；可选 `slot_shapes`。HTML `board` 写出公式，在需要填写的位置放 `<span data-fill="i"></span>`（缺省时槽位排在画板下方）。公式窄屏需换行时加 `.fill-formula`，用 `.fill-group` 分出不可拆开的段（Q16、Q17、Q19、Q20、Q23–Q27、Q30 分式分离；Q21、Q22 待定系数；Q18 单格配因式，单格可用 `attempt_calculations`，按填写值查找展开核对模板） | `{terms: [...]}`，按位置分别校验 |
| `checklist` | 判断方法前提等逐项核对。`title` 为清单标题；`slots` 每项一行：`label`、可选 `hint`（提示去哪里看），`options:[{value,label,note}]`。候选常驻显示，选中后显示该项 `note`；`note` 只写这个选择意味着什么，不写对错，不泄露答案。可选 HTML `board`，显示在清单上方，用来交代要检查的对象来自哪里（如上一步范围的边界）；完成态由 `display` 模板写出已满足的各项与结论，并写明检查对象（/2/q01 两条路线的“判断适用条件”与“检查边界”；方法的适用条件可在 `board` 里先用一行讲清方法本身，再逐项核对） | `{terms: [...]}`，按位置分别校验 |
| `choice` | `field`：状态答案键；`options`：`{value,label}` 数组；可有 `description` 给老师解释值的含义 | `{one_of: [...]}`，列可接受的候选值 |

`structure` 当前视觉将定和对应求积最大、定积对应求和最小。这依赖正项等教学前提，不是所有极值题的通用规则。候选项与运算需与题意匹配。

`terms` 是槽位候选；AM-GM 可用 `positive_terms` 显式声明已由条件或前一步确认的正项，显示正项标记。省略时沿用全部 `terms`，适用于候选均为正的题目。候选中包含负项时必须提供 `positive_terms`，不能将所有候选一律标为正；Q04 使用四个候选，但仅 −x、−4/x 有正项标记。通过条件仍由 `expected_answer.terms` 决定。

成对项可声明 `term_labels: {"1/x^2": "$\\frac{1}{x^2}$"}`：`terms` 保留稳定的候选值，标签只用于菜单、槽位、正项标记及模板显示。前后台仍按候选值校验，不解析 LaTeX 作为答案。`equality.caption` 可覆盖默认的“基本不等式取等”；例如 Q02 配方路径使用“平方项为零”，该组件不假定两项为正。

`choice` 多个正确选项必须由学生选择，老师不能擅自代选。UI 事件只带值，服务端按当前节点的 `field` 绑定；不要自己在事件中拼任意状态路径。

## 教师 JSON

存放在 `server/shuxueshuo_server/tutor_demo/lessons/<lesson-id>.json`，当前加载器按已安装文件名发现题目。

- 顶层为 `id`、`version`、`problem`、`methods`、`routes`、`initial_state`。
- `problem` 提供 `statement`、`conditions`、`target`；不加入学生输入。题干可以使用 LaTeX 文本。
- 教师 `routes` 是路径 ID → `{label, nodes: [...]}`，不同于页面直接使用节点数组。
- 节点包含与页面一致的公共字段，另有 `required_evidence`、`criteria`、`completion_reply`、`results`。
- `required_evidence` 用简短语义标识；`criteria` 解释什么表达足够/不足及等价答案，不把 UI 点击顺序写成数学要求。
- `results` 是作者参考结论，不是运行时证明证书。可以用 `{{variable}}` 等已选字段引用；当前后台只从 `choices` 解析这些占位，不支持任意公式计算。
- `initial_state` 应与公共 `PracticeContext.freshState()` 一致：`active=0`、`method=null`、`swapped=false`、足够的空成对槽位、所有 choice 字段为 null、空反馈和提示状态。不要沿用 Q01 的固定三步或无关答案键。

仅选择方法不足以完成节点；系统代算的部分要在教学标准中明确，不能反过来要求学生重复输入。完成确认不要追问下一节点的问题，下一张步骤卡会提出。

教师 JSON 不放 `text_autofill`、可执行 JS 或任意字段路径。通用 Prompt 不加入这道题的变量、答案和路线特例。

## 同步与测试入口

本地状态先行。第一次对话才创建后台会话，再携带未同步操作和学生输入调用 events；无需为新题创建独立服务。服务端在临时 Context 中重放校验，成功后整体提交。复用公共通信流程，不在本题 HTML 写自己的 fetch。

稳定边界由这些文件示范：

- `server/tests/tutor_demo/test_local_practice.py`：前后台配置一致、逐操作状态一致、批量重放、失败原子性、重试后新增操作。
- `test_attempts.py`：独立路径尝试、证据隔离、等价输入与契约边界。
- `test_tutor_live.py`：Q01 的真实 DeepSeek 验收示例；新增题必须编写自己的场景，不能把通过 Q01 当作通过新题。

章节 `/1/` 的七种题型（首页按此顺序编号 01–07，并在“题目”下方列出题型目录）：直接法求最值、常规配凑法求最值、配齐次式求最值、消参法求最值、换元求最值、分式分离法求最值、找对称结构和积换元。新增题目或题型时同步更新目录行的题数与各组 `type-count`（`test_chapter_index.py` 会核对）。题型组可在题数旁放“图解”按钮（`data-method-dialog`），指向页面底部的 `<dialog class="method-sheet">`：一句核心 + 核心图像 + 三步 + 本组示范题链接；示范链接只能指向本组题目，标题与组名一致（同一测试核对）。按主要训练目标归类，页面可提供多条可行路径。新增其他章节时检查静态入口与独立 API 开发服务的挂载范围，不要假设目前只挂载 `/1` 的开发服务会自动提供所有新章节。

Q08 的对称路径将识别与换元分开：交换前后的式子由题目 HTML 直接并排展示（x、y 用固定两色标出位置互换），展示不是已作答证据；条件、目标的判断记录为两个 fill 输入。Q08 的换元用定义形态，只定义 s、p（xy 不是目标式中连续的一块，无法点选），后续化简和可行范围由预写推导展示，不引入计算板或表达式解析器。Q28–Q30 沿用同样的识别与定义形态（Q29、Q30 的对称判断预期为“改变”，随后用 choice 选换元构造对称），之后的和积改写、不等式与范围用 choice 完成；Q30 的变量为正数，选不等式的 `one_of` 同时接受 p≤s²/4 与 s≥2√p。Q11 使用点选换元形态。

### 二次函数图像（只读展示）

Q01 顶点法与 Q09 两种消参结果共用 `PracticeComponents.quadraticGraph`。HTML 在 `.reasoning.vertex-reasoning` 中并排放推导与 `.quadratic-graph`，窄屏自动上下排列。图形挂载点为 `<div data-quadratic-graph="…JSON…"></div>`，属性值需要 HTML 转义。

配置使用顶点式：`coefficient * (x-h)^2 + k`，`vertex:[h,k]`；`bounds:[xmin,xmax,ymin,ymax]` 为绘图窗口（当前坐标轴要求窗口含原点与顶点），不是定义域。可选 `domain:[left,right]` 限制曲线范围；`excluded` 用空心点标出不取的横坐标。`xTicks:[[值,标签],…]` 包括原点、顶点横坐标和需标出的特殊值，`yLabel` 为顶点纵坐标显示。`variable/title/description` 提供坐标变量及无障碍说明，`uid:"{{uid}}-quadratic"` 保证当前步骤和历史图像 ID 不重复。公式与图注仍由本题 HTML 编写。

其他可选项：`showVertex:false` 隐藏顶点及注释；`referenceLines:[{value,label}]` 画水平参考线；`points:[{x,label}]` 在曲线上标点；`markSign` 标出违规的一侧：`true` 或 `"below"` 浅红铺出 y<0 区域、曲线负值段改红（≥0、>0 型题），`"above"` 铺出 y>0 区域、正值段改红（≤0、<0 型题），并标出与横轴的公共点；`strict:true` 时公共点也算违规（画红色），用于严格不等式；`solution:{intervals:[[from,to],…],closed}` 在横轴上画出所选范围（`null` 为无界；`closed` 为布尔值时统一决定端点实心／空心，为数组时按端点顺序逐个指定，用于半开区间），用于解一元二次不等式。`coefficient:0` 可画水平直线，用于二次项系数为零的退化情形。`interval:[a,b]` 用于“在某区间上恒成立”：区间两端画竖直虚线，区间外的曲线淡化，`markSign` 只在区间内判断；一端写 `null` 表示该侧无界（如 `[null,0]` 表示 $x<0$），不画竖线（三个图像组件相同）。`points` 的每一项可加 `place`（`above-right` 默认、`above-left`、`below-right`、`below-left`）避开曲线或刻度；加 `open:true` 画成空心点，表示开区间端点取不到，标签写“取不到”（`reciprocalSumGraph` 相同）。

### $y=ax+\frac bx$ 图像（只读展示）

`PracticeComponents.reciprocalSumGraph` 画 $y=ax+\frac bx$ 在 $x>0$ 的一支（$a,b>0$ 时为对勾函数），挂载点 `<div data-reciprocal-sum-graph="…JSON…"></div>`。配置 `a`、`b`、`bounds`，可选 `interval`、`xTicks`、`points`、`referenceLines`、`variable`，以及 `title/description/uid`，用法与 `quadraticGraph` 相同；`asymptotes: true` 再画出两条渐近线（$y$ 轴与 $y=ax$，虚线并标注 $y=ax$），用于“画函数图像”一步展示完整的对勾形状，此时窗口要放宽到能看出贴近 $y=ax$。用于分离参数后 $x$ 一侧为 $x+\frac kx$ 型的题（/2/q04 的 $h(x)=x+\frac4x$）。$x<0$ 时加 `negative: true` 改画左边一支（/2/q06 的 $h(x)=-x-\frac2x$，`a:-1, b:-2`，渐近线标注 $y=-x$）。$x$ 一侧带负号时画去掉负号的正函数，不画倒过来的图像；水平线取本题具体的值（如 $y=-m$）。

`PracticeComponents.linearGraph` 画一次函数 $y=\text{slope}\cdot t+\text{intercept}$ 的直线，挂载点 `<div data-linear-graph="…JSON…"></div>`。配置 `slope`、`intercept`、`bounds`，可选 `interval`、`xTicks`、`points`、`markSign`、`strict`、`variable`，以及 `title/description/uid`，用法与 `quadraticGraph` 相同；`interval` 外的部分淡化，`markSign` 时标出与横轴的交点（`strict` 画红色）；整段落在横轴上（`slope:0, intercept:0`）且 `strict` 时整段标红。斜率符号随另一个字母变化时（/2/q09），用三张真实实例放进 `.graph-cases` 对照最低点的位置。用于更换主元后关于主元的一次函数（/2/q08：$f(m)=(x^2-x+1)m-6$ 取 $x=0$、$x=2$ 两个真实实例对照斜率，边界处 $f(m)=2m-6$ 的右端点落在横轴上）。`quadraticGraph` 的根刻度要用精确的根值（无理根不要四舍五入），`markSign` 才能识别为根并把标签移到曲线外侧。

### 可拖动对称轴（探索组件）

`PracticeComponents.axisExplorer` 画 $f(x)=a(x-h)^2+c-ah^2$，学生拖动图中的对称轴 $x=h$ 或下方滑块，观察区间上的一段与较高端点（标“最高”）如何变化。挂载点 `<div data-axis-explorer="…JSON…"></div>`。配置：`coefficient`（$a$）、`constant`（$c=f(0)$）、`axis: {min, max, step, value}`（对称轴可动范围与初始位置，顶部浅色轨道画出这个范围，拖动不会越界）、`interval`、`bounds`、`marks: [{x, label}]`（分类分界点，如区间中点），以及 `variable`、`title/description/uid`。它只供观察，不计答案、不发事件。分类讨论最值的一步这样用：`board` 放一张，范围跨过分类分界点，学生自由拖动后在 `checklist` 作答；完成态每种情况放一张，`axis.min/max` 限定在该情况内（严格不等的一侧离开分界点一个 `step`），图注写用对称轴表示的分类条件和最值，不举具体的参数值。图下不显示数值读数，靠图像本身看出哪端最高。只处理开口向上；默认求最大值，`target: "min"` 改求最低处（/2/q06）：顶点在区间内时顶点标“最低”，否则较低端点标“最低”（`open` 时“下端”）；`board-caption` 不渲染公式，题板说明写纯文字。开区间（/2/q05）加 `open: true`：两个端点都画空心，较高一端标“上端”，图注与题干说“取值范围的上端”，不说最大值，也不用“上确界”。

/2/ 的存在性题（“有解”按“存在”理解，/2/q05）沿用恒成立的节点 ID 与交互，只换措辞：题意卡写“有解即存在：$\exists x\in\ldots$”；`i_condition`／`e_condition` 标题“转化为范围条件”，`i_extremum` 标题“分类讨论取值范围”，`e_extremum` 标题“求取值范围”；检查边界候选为“存在 $x$ 成立，保留／没有 $x$ 成立，排除”。和恒成立的对比放在干扰项里（比下端、恒成立时的答案），不另加步骤。

配套的公共模板样式（写在本题 HTML 模板里，不要另造同义类名）：
- `.graph-cases` > `.graph-case`：几种情形并排的缩略图卡片，抛物线取本题真实参数值对应的函数，某种位置在本题不可能出现时，图像标题写“示意”、描述注明“不是本题…对应的图像”；`figcaption` 内放 `.graph-case-name`、`.graph-case-fact` 或 `.graph-case-delta`、`.graph-case-verdict`；不满足加 `.rejected`，“所选条件包含／排除”用 `.included`／`.excluded`；结论条 `.graph-cases-verdict`。
- `.case-merge`：几个情形合并成一个条件。`.case-merge-group` 内放 `.case-merge-cell`（`.case-merge-name` + `.case-merge-value`）与 `.case-merge-total`，被排除的情形单列 `.case-merge-cell.rejected`，内含 `.case-merge-out`。保留两项时 total 写“取并集：…”，只保留一项时写“只保留：…”，几个条件要同时成立时写“取交集：…”；保留一项、排除两项时自动排成三栏；组内三格（如 /2/q07 的三种情况）排成一行三栏，此时把名称里的“（条件）”写成 `<span class="nowrap" data-math-text>（…）</span>`，外层 `.case-merge-name` 不加 `data-math-text`，窄屏换行才落在条件之前。合并之前要交代前提时（/2/ 判别式条件的“开口向下（$k<0$）时”），在组前放 `<p class="case-merge-caption" data-math-text>`。`data-math-text` 按 `textContent` 渲染，里面不能再嵌套标签。

/2/ 的 `choice` 不配 `preview`：选中只高亮，提交后由 `feedback` 给提示（不直接写出答案），图像和解释放在完成态；`server/tests/tutor_demo/test_quadratic_always_consistency.py` 检查。

新增公共能力须满足：命名不含题号或方法名；配置只描述数学内容；在本题或已有题中至少两处使用；同步写入本文件与共享运行时设计文档。两条路线中相同的步骤应共用模板（如 /2/q01 的 `range-board`），只有完成态按路线分别说明。

同一专题中，不同题目的相同步骤也要一致：使用同一节点 ID、标题、交互类型、提交按钮文字、题干句式和完成态结构，只替换函数、参数与数值。/2/ 的判别式法按 [恒成立题库设计](../../../../docs/quadratic-inequality-always-true-practice-design.md) 中的“判别式法标准步骤”编写（`d_basis`、`d_rewrite`、`d_degenerate`、`d_position`、`d_delta`、`d_range`、`d_merge`、`d_boundary`，按题目条件取舍，计算不单独成步），区间最值法按同一文档的“区间最值法标准步骤”编写（`i_basis`、`i_condition`、`i_extremum`、`i_range`、`i_boundary`；`i_condition` 与 `e_condition` 选项值相同），分离参数法按同一文档的“分离参数法标准步骤”编写（`e_basis`、`e_separate`、`e_condition`、`e_graph`、`e_extremum`、`e_range`、`e_boundary`，`e_basis` 清单逐题完全相同；$x$ 一侧不是可直接求最值的函数时用 `e_graph` 先画图像），更换主元法按“更换主元法标准步骤”编写（`v_basis`、`v_rewrite`、`v_condition`、`v_extremum`、`v_range`、`v_boundary`；`config.variables[0]` 写恒成立所针对的主元，如 `['m','x']`；`v_basis` 先问“题目要求对哪个变量的所有取值都成立”，选项值固定为 `given`／`asked`，标题、清单句式和选项值逐题相同，只替换字母与范围）；每条路线的最后一步都按“检查边界（所有路线共用）”编写，候选里的“对所有〈量〉”用 `variables[0]`；结论不同的边界各画一张图。题板提示句、适用条件的结论与推导首句、转化条件的三个标签、`v_extremum` 与“区间与最低点的位置”的选项值，按同一文档的“同一步骤的统一写法”逐题固定。以上由 `server/tests/tutor_demo/test_quadratic_always_consistency.py` 检查。新增一道题时先对照标准步骤表；确需新步骤或改句式时，先改标准表，再同步已有题目。

Q01 的定义域是 (0,2)，Q09 的定义域是排除两个值后的实数集；不能为了统一图形把 Q09 曲线裁成正积区间。组件仅绘图，不解析表达式、不判断答案、不调用模型。

### 范围与乘数配式

`rewrite` 的页面节点声明 `board`（原式画板）与 `scope_boards:{范围值:模板ID}`。原式画板用 `.rw-board` 常驻显示原式，每个可选部分写成 `<button type="button" class="rw-target …" data-rewrite-scope="范围值">`，可以是整个式子（`.rw-whole` 外框，内放 `.rw-legend` 标签；它是 `.rw-source` 里铺满外框的底层按钮，各项按钮叠在其上，因此点外框留白或标签选中整体，按钮不能互相嵌套）、某一项（`.rw-term`），也可以是局部的某个常数；分子或分母里的局部目标用 `.rw-frac` 手写分式，使按钮能放进分子。画板内放一个 `<span data-rewrite-result></span>`，组件在此处显示所选范围对应的 `scope_boards` 模板（`.rw-result` 一行“= … × 乘数”），未选范围时显示占位提示。每个 `scope_boards` 模板包含一个 `<span data-rewrite-factor></span>`，组件替换为乘数槽位。范围按钮对应第 0 个 fill，乘数对应第 1 个 fill；切换范围时保留乘数。画板中的范围值必须与第 0 个槽位候选完全一致（测试会核对）。未声明 `board` 时退回为范围按钮列表。模板映射只在学生 HTML 中，教师 JSON 保存范围含义、候选值、预期答案和教学依据。

带 `slots` 的组件（rewrite、点选换元）按实际槽位数判断是否填完与校验，不要求补齐第二个槽位。

### 点选换元

`substitution` 声明 `board` 与 `scope_boards` 时，学生在目标式里点选要看成整体的部分。原式画板用 `.sub-board`，可选部分写成 `<button type="button" … data-sub-target="对象值">`：单个字母等叶子用 `.sub-leaf`；包含其他可选部分的整体（如包含 a 的 a+1）用 `.sub-chunk` 包住一个空的 `.sub-frame` 底层按钮和 `.sub-inner` 内容，点外框留白选中整体、点里面的叶子选中叶子。分式手写为 `.sub-frac`，运算符用 `.sub-bin`。画板内放 `<span data-sub-result></span>`，组件在此显示 `scope_boards[所选值]` 模板，一般是 `.sub-table` 对照表（`.sub-def` 写“设 t=…”，`.sub-head` 与 `.sub-row` 为“行名 / 原变量 / 箭头 / 新变量”四列，窄屏自动变三列）。

槽位值为所选对象按 `options` 顺序用 `|` 连接，空字符串表示未选；数量不超过 `names` 个数。前端按此规则校验，后台把全部合法组合列为候选值，两边一致。重叠对象由画板嵌套关系判断，选一个自动取消另一个；已选满时再选新的会替换最早选的。新变量名按对象在画板中的位置从左到右分配，不按点击顺序，所以 `scope_boards` 模板与后续步骤可以固定写 t、u。每个可能的组合都要写对照表模板；只是改名、没有推进的选项（如 t=a）也要如实展示，由提交反馈说明问题。画板中的对象值必须与候选一致（测试会核对）。条件、范围、目标的改写由系统展示，不算学生推导；教师 JSON 要写明换元后的范围，取等检验要验证取等点落在这个范围内。

Q10 中 whole/first/second 是该题的候选值，公共代码不包含这些值，也不写死“整体正确”。后续局部配齐次可用同一组件声明不同正确范围。配式预览是学生尝试，提交通过后才推进；不支持自由划选、任意公式输入或动态计算，计算板尚未接入。


### 配式组合的计算反馈

`rewrite` 及单、双槽位 `fill` 节点可在学生页面的 `practice-config` 中声明 `attempt_calculations`，双槽位映射为“第一槽值 → 第二槽值 → HTML模板ID”，单槽位映射为“填写值 → HTML模板ID”。参照 Q14、Q18。对有限候选组合，预先验证并写出计算过程，不为点选调用模型或引入计算引擎。核对对象不能恰好是本步要学生求出的结果：Q17 不展示 1/(5n²)+4n²/5，而是把所填两项通分后与原式的分子比较系数。

- 选择时保留“尝试改写”；确认未通过后展示所选组合的计算模板。通过后仍使用节点 `display` 完成态。
- 数学区 `.rewrite-calculation-math` 只放数学推导；反馈区 `.rewrite-calculation-feedback` 分别解释等价性和是否达成本步目标。
- 乘错因子时，只能展示候选表达式自身的正确展开，不能用等号将它与原式连接。
- 计算展示依据 Context 中当前尝试/路径/步骤最近一次 UI 提交，并核对当前组合；不要依赖临时 feedback。对话或提示保留计算，改选会清除旧计算，即使改回也需重新确认。通用 UI 反馈仍保存在 Context，但配置组合计算后不重复显示成聊天气泡。
- 模板与引用属于 HTML，不放入教师 JSON。测试应覆盖全部候选组合的模板引用，并实际验证未确认、错误提交、改选、正确推进及其他题目的兼容性。

Q16 的双槽位填空沿用二层映射（第一槽值 → 第二槽值 → 模板），不表示支持任意数量槽位的计算。未确认的恒等式标为尝试；错误组合展开后比较系数，必要时使用不恒等符号，避免把某些取值下成立的等式说成处处不相等。

Q18 单槽位 `fill` 的 `attempt_calculations` 使用一层映射（填写值 → 模板）；双槽位沿用二层映射。单槽位仍复用双格状态存储，确认组合恢复时保留空的第二格。提问保留计算，改选清除，正确提交使用完成态。
