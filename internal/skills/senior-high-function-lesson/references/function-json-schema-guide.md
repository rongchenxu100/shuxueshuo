# Function JSON 规格指南

## 文件

- `function-spec.json`：数学对象、参数、bindings 和面板数据。
- `function-decorations.json`：每一步显示哪些面板，以及强调哪些对象。
- `lesson-data.json`：题干、步骤、导航、控制策略和输出路径。

`lesson-data.problem.keyPoints` 是可选的解题要点区块，包含 `title`、可选 `lead` 和 1～4 条 `items`。它只概括可复用的方法框架或易漏条件，不写具体答案；没有必要时应省略，编译器不会生成空区块。题干、步骤和要点中的简单行内公式使用 `\\(R_f\\subseteq B\\)`、`\\(y=\\frac{2x}{3}\\)`、`\\(f(x)=\\frac{\\sqrt{3x+11}}{x}\\)` 形式，由编译器安全生成下标、嵌套上下分式、关系符号和覆盖完整被开方式的根号，不在 JSON 中写 HTML，也不要使用裸文本 `2x/3` 或 `√(...)` 代替需要规范排版的公式标记。

所有需要数学排版的题干、选项、步骤标题、推导和聚合页文本都必须使用同一套公式标记。重点检查：

- `x^2`、`2x^3` 使用真正的上标；
- `R_f`、`x_0` 使用真正的下标；
- `\\frac{a}{b}` 的分子、分母与同行文字垂直居中；
- `\\sqrt{...}` 的根号横线覆盖完整被开方式；
- 嵌套式如 `\\frac{(2x-1)^0}{\\sqrt{2-x}}` 不得拆成互相错位的片段。

发布前必须同时在单题页和 worksheet 聚合页检查这些公式，因为二者字号和行高不同。

## 面板

每个面板必须有稳定 `id`、`kind`、归一化 `viewport` 和与 kind 对应的数据。面板 ID 在同一题中不得重复。

`functionGraph` 的函数表达式由安全表达式引擎计算；定义域必须显式写成区间或有限值。候选函数的 `intervals` 表示函数能够绘制的天然定义域，面板的 `studyIntervals` 表示题目当前研究的输入集合。两者不能混用。

同一 `functionGraph` 中的候选函数应共用 `domain` 视窗。需要同时展示完整曲线和题设区间时，在 decorations 中设置 `highlightStudyInterval: true`：运行时先在 `intervals` 上绘制完整曲线，再加粗 `intervals ∩ studyIntervals`，不会绘制天然定义域外的部分。

`numberLine` 的每个区间必须注明开闭端点。`mapping` 的候选关系必须给出显示标签和规则表达式。

`relationPlot` 可在步骤装饰中设置 `showVerticalTest: true`，运行时会根据主参数绘制竖线、交点及交点数量，用于检查缺失输入或一对多关系。教材原图中的坐标投影虚线写入面板的 `guidePoints`，其中 `showX/showY` 分别控制到 x 轴和 y 轴的投影。`domain` 表示题目中的数学范围；当教材坐标轴明显长于关系图形时，用 `axisPadding` 扩展显示视窗，不能改动线段端点来伪造留白。若题干需要展示原图，在 `lesson-data.problem.lines[].figures` 中引用对应面板的同一个 `id`；编译器会在原题区渲染无教学叠加的基础图，步骤区继续复用该面板并按 decorations 增加竖线检验。

`contextGeometry` 的点和多边形可使用 `label` 标明实际量。圆锥、圆柱和旋转体的截面使用声明式 `ellipses`；需要表达被曲面遮挡的后半圆时设置 `backHalfDashed: true`，不要用两个平面三角形代替立体容器。半无限研究区间用有限视窗绘制时，应设置 `extendsMin/extendsMax` 和相应数学标签，明确图形仍向视窗外延伸。

`lesson-data.meta.outputPath` 是发布路径的唯一来源，格式为 `site/problems/senior-high/<chapter-id>/<section-id>/<problem-id>.html`。构建题库、worksheet 和解析链接时读取该字段，不根据 lesson ID 拼接 `drafts` 路径。

## 步骤装饰

每个 lesson step 必须在 decorations 中有同名条目。常用字段：

- `visiblePanels`：当前可见面板。
- `activeCandidateId`：mapping、relationPlot 或多候选 functionGraph 的当前候选。
- `visibleElementIds`：当前出现的约束、区间或表格行。
- `highlightElementIds`：当前强调对象。
- `highlightStudyInterval`：浅色绘制完整曲线，并加粗题设研究区间内的有效片段。
- `showProjection`、`showDomain`、`showRange`：函数图辅助信息；只在对应信息确实参与当前推理时开启。

规格不得包含 HTML、可执行 JavaScript 或动态代码字符串。表达式只允许使用数学表达式引擎支持的语法。

## 文本与公式契约

- 可见数学内容使用结构化公式片段，统一处理分式、根式、上下标、集合和区间，保证与正文基线对齐。
- 禁止在普通可见字符串中写原始 TeX 定界符或命令，例如 `\(`、`\)`、`\Rightarrow`、`\cap`、`\mid`、`\ge`。编译后必须扫描这些残留。
- 分子分母使用竖直分式，根号横线覆盖完整被开方式，幂指数位于右上角。题干、步骤正文和聚合页必须共用同一格式化能力。

## 步骤布局契约

- `showDiagram` 为可选证据开关。没有匹配面板时必须为 `false`，且运行时不得保留空白图形区域。
- 两个步骤若引用同一面板且没有可见对象、参数或强调状态变化，应删除其中一个图形引用。
- 步骤标题只写动作，不包含 `第 N 步`；编号由页面运行时和导航统一生成。
- 导航分组只对应题目中的真实问题或小问。单问问题直接列步骤，不额外创建方法分类分组。

## 聚合页与发布契约

- `lesson-data.json` 是题干、来源和原题图形的唯一来源；聚合页不得复制一份手工题干。
- 来源以括号形式放在题干前，不单独占行。无来源时不输出空占位。
- 选择题选项与题干分行。短选项可同排，长选项每项一行，并在题目页和聚合页保持一致。
- Worksheet 聚合页不包含答案、解题要点、步骤或完成进度；解析链接使用新标签页打开。
- 聚合页中的 SVG 使用题目 ID 命名空间，并按实际嵌入尺寸校验文字、数字、坐标刻度和尺寸标注可读。
- 基础练习与能力提升使用独立 collection，但共享章节分类和渲染规则。
- 草稿只存在内部构建路径。发布后使用稳定的章节目录与文件名，删除 `draft`、`待复核`、`草稿` 等内部文案，并确保 catalog 只链接正式路径。
- 折叠完整题目时保留第一条印刷题干，不渲染空白占位行。
