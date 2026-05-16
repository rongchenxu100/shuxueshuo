# Skill Reference 与知识库改造设计

## 1. 背景与问题

当前 `quadratic-lesson` 和 `geometry-lesson` 的 reference 机制主要依赖固定 Markdown 文档和固定 few-shot 示例。这个方式让页面生成流程有了基本护栏，但在人工校验过多道题后，暴露出几个稳定问题。

第一，固定 reference 文档越来越重。为了纠正某一道题出现的问题，我们会把经验继续追加进 `quadratic-solving-principles.md` 或 `diagram-drawing-principles.md`。长期看，这些文档会混合"通用原则""题型模板""单题经验"和"渲染细节"，模型每次都要读很多上下文，却未必能选中当前题真正需要的规则。

第二，固定 few-shot 不适配新题。现在二次函数综合题主要依赖 `nankai-25-fewshot.md`。它对"系数约束固定对称轴、等腰直角、EG+FG 最小值"这类题很有帮助，但河西 25 这种"构造等腰直角三角形转化 AN，再将军饮马"的题，真正相似的参考题可能是西青 25 或其他已发布题，而不是固定的南开 25。

第三，模型容易使用非初中方法。二次函数综合题经常可以用向量、投影、点到直线距离、斜率夹角公式快速求解，但这不是面向初中生的教学解法。我们需要把"初中可接受知识点"变成明确可引用的知识，而不是只在 prompt 里反复提醒"优先几何方法"。

第四，JSON 中样式和默认值声明过多。很多字段并不是题目数学意图，而是固定视觉策略，例如颜色、线宽、虚线样式、不可拖动步骤的 range、常见图层、公式卡片的取舍。让模型逐项声明这些内容，会增加出错面，也会让模型把注意力从解题和图形语义转移到样式细节。

## 2. 目标

把 skill 从"固定文档说明书"升级为"可按题查找的知识系统"，同时保持极低的维护成本。

核心原则：

- **明确区分三类概念**：题型标签（pattern）描述题目场景设定，解题方法（method）描述具体解法技巧，课程知识（topic）描述涉及的数学主题。三者不混称为"知识点"。
- **一个文件放方法和标签**：解题方法的完整条目和题型标签的枚举表放在同一个 Markdown 文件中。不搞多级目录。
- **渐进披露找相似题**：不建标签检索和向量索引。维护一个案例目录，按题型和方法双维度分组，模型先读目录定位候选，再按需读具体题的 lesson-spec。模型自己做"检索"决策。
- **代码下沉样式与默认值**：能由代码稳定处理的内容移走，模型产出的 JSON 只表达数学对象和步骤意图。

### 三类概念的定义

**题型标签 (pattern)**：描述题目的场景设定和结构特征。读完题目后的第一反应。一道题通常只有一个主 pattern。

- 例：`path-minimum`（路径最值）、`moving-point-folding`（动点折叠）、`moving-point-rotation`（动点旋转）、`coefficient-constraint`（系数约束）、`area-maximum`（面积最值）

**解题方法 (method)**：描述解决某个子问题的具体技巧。有明确的触发条件、允许/禁用方法、推导模板。一道题的不同小问可能用到不同方法。

- 例：`horse-drinking`（将军饮马）、`isosceles-right-triangle-transform`（等腰直角三角形转化线段）、`rotation-by-congruence`（旋转全等）

**课程知识 (topic)**：涉及的数学主题。太粗，不区分题目。已在 `problems.json` 的 `tags` 字段中存在（`quadratic-function`、`coordinate-plane` 等），不纳入本系统。

## 3. 新 Reference 架构

三层，但比之前轻得多。

### 第一层：Skill 流程文档

`internal/skills/quadratic-lesson/SKILL.md`（及 `geometry-lesson/SKILL.md`）当前定义生成流程和校验/编译命令。Phase 2 之后，SKILL.md 将扩展为包含知识库操作的完整步骤序列（详见第 4 节和第 7 节 Phase 2）：

- **Step 0**（Phase 2 新增）：读取方法库和案例目录，识别 pattern/method，选参考题。
- **Step 1–N**：现有生成流程（01_problem → 02_solution → 03_visual_steps → JSON）。
- **Step N+1**（Phase 2 新增）：在 lesson-data.json 中写 classification（pattern + methods）。
- **Step N+2**：校验（validate-geometry-spec.mjs + Phase 3 后加入 lint-lesson-quality.mjs）+ 编译。
- **Step N+3**（Phase 2 新增）：更新 case-index.md（Part 1 + Part 2 各加一行）。

HTML 是编译产物、真实 schema 是权威来源。不再在 SKILL.md 里堆积具体题型经验。

### 第二层：解题方法与题型标签（单文件）

放在 `internal/knowledge-points/junior-math-methods.md`。

文件分两部分：头部是题型标签枚举表，后面是解题方法的完整条目。

#### 题型标签枚举（文件头部）

```markdown
# 初中数学解题方法与题型标签

## 题型标签 (Pattern)

模型读完题目后，先从以下标签中选择最匹配的 pattern。pattern 是 case-index.md 粗导航的路由键。

| pattern ID | 名称 | 典型特征 |
|---|---|---|
| path-minimum | 路径最值 | 求 PA+PB 最小、折线最短、含权重路径最值 |
| area-maximum | 面积最值 | 求三角形/四边形面积最大或最小 |
| moving-point-rotation | 动点旋转 | 动点绕定点旋转，求旋转后图形性质 |
| moving-point-folding | 动点折叠 | 沿某线折叠，求折叠后坐标或性质 |
| moving-point-translation | 动点平移 | 图形平移后求相关量 |
| coefficient-constraint | 系数约束 | 由几何条件（点在曲线上、线过定点等）求系数 |
| special-triangle-existence | 特殊三角形存在性 | 是否存在等腰/直角/等腰直角三角形 |
| segment-ratio-or-equality | 线段比或等量关系 | 证明或求线段比值、线段等量 |
```

#### 解题方法条目

每条格式统一，通过 method ID 引用：

```markdown
---

### method: horse-drinking

**名称**：将军饮马（折线路径最值）

**触发条件**：题目要求 PA+PB 最小、PA-PB 最大、或含权重的折线路径最值。

**初中允许方法**：
- 对称点拉直：关于边/轴作对称点，三点共线时最短。
- 如果有权重（如 2DM+AM），先构造可见线段吸收权重（如等腰直角三角形使 DM→D'M/√2），再拉直。
- 用"三点共线""垂线段最短"等初中语言。

**禁用方法**：
- 点到直线距离公式作为主解。
- 向量投影。

**标准推导模板**：
1. 识别折线路径和约束线。
2. 作对称点。
3. 证明三点共线时取最短。
4. 计算对称点到终点的线段长。

**图形要求**：
- 画对称点、拉直线段。
- 不画投影线或法向距离。

**常见错误**：
- 忘记检查共线点是否在约束线段范围内。
- 含权重时直接对称，没有先用构造吸收权重。

**构造宏状态**：观察中（3/3，可讨论固化 `horsePathStraightening`）
```

其他文件通过 method ID 引用，例如 `参见方法 horse-drinking`。

**为什么单文件**：

- 当前和近期的 pattern + method 总共几十条，远不到需要目录拆分的规模。
- 模型一次读完（几千 token），比跳转多个文件效率更高、上下文更完整。
- 维护一个文件、一次 commit，不会出现"写完题忘了更新某个子目录"的漂移。
- 如果将来超过 100 条，再拆不迟。

### 第三层：案例目录（渐进披露）

放在 `internal/knowledge-points/case-index.md`。

这个文件按**两个维度**分组列出所有已发布、人工校验过的题。模型通过读这个目录来"检索"相似题——不需要标签匹配工具或向量检索。

#### Part 1：按题型标签分组（粗导航）

模型读完题目后先识别 pattern，在这里找到同类题型的全部已发布题。适合两遍式流程的"粗判"阶段。

```markdown
# 案例目录

## Part 1：按题型标签 (pattern)

### path-minimum

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| tj-2026-nankai-yimo-25 | 25 | EG+FG 最小值 | horse-drinking, rotation-by-congruence |
| tj-2026-heping-yimo-25 | 25 | OM+BN 最小值 | horse-drinking |
| tj-2026-xiqing-yimo-25 | 25 | 2DM+AM 含权重路径 | horse-drinking, isosceles-right-triangle-transform |
| tj-2026-hexi-yimo-25 | 25 | AN 转化后路径最短 | isosceles-right-triangle-transform, horse-drinking |
| tj-2026-hedong-yimo-25 | 25 | AG+GH+FH 最短路 | isosceles-right-triangle-transform |

### coefficient-constraint

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| tj-2026-nankai-yimo-25 | 25 | M、N 在抛物线上求 a | coefficient-from-point-on-parabola |
| tj-2026-heping-yimo-25 | 25 | D 在抛物线上求 a、b | coefficient-from-point-on-parabola |

### moving-point-rotation

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| tj-2026-nankai-ermo-25 | 25 | AC 绕 C 旋转 90° 得 DC | rotation-by-congruence |

...（随已发布题增长）
```

#### Part 2：按解题方法分组（细导航）

模型确定需要某个具体方法后，在这里找到使用同一方法的所有已发布题。适合两遍式流程的"精判"阶段。

```markdown
## Part 2：按解题方法 (method)

### horse-drinking

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| tj-2026-nankai-yimo-25 | 25 | 第（Ⅱ）①④ | EG+FG 最小值，构造正方形对称点拉直 |
| tj-2026-heping-yimo-25 | 25 | 第（Ⅱ）问 | OM+BN 中 BN 经 CM=CN 转化，对称拉直求最小值 |
| tj-2026-xiqing-yimo-25 | 25 | 第（2）② | 2DM+AM，30° 等腰构造吸收权重后拉直 |

### isosceles-right-triangle-transform

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| tj-2026-hexi-yimo-25 | 25 | 第（Ⅲ）问 | 构造等腰直角三角形把 AN 转化为 √2·QN |
| tj-2026-hedong-yimo-25 | 25 | 第（Ⅱ）①② | 直角等腰条件确定 D，AG+GH+FH 最短路 |

### rotation-by-congruence

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| tj-2026-nankai-ermo-25 | 25 | 第（II）①② | AC 绕 C 旋转 90° 得 DC，用全等三角形求 D 坐标 |
| tj-2026-nankai-yimo-25 | 25 | 第（Ⅱ）① | ∠MDN=90°，DM=DN，用全等三角形确定 N |

### coefficient-from-point-on-parabola

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| tj-2026-nankai-yimo-25 | 25 | 第（Ⅱ）② | M、N 在抛物线上，联立消参求 a |
| tj-2026-heping-yimo-25 | 25 | 第（Ⅰ）① | D 在抛物线上，配合 A(-1,0) 求 a、b |

...（随已发布题增长）
```

模型应先读本目录确定候选，再读候选题的 `internal/lesson-specs/<id>/02_solution.md` 获取完整解法。

#### classification 与 case-index 的关系

三个数据源包含不同层次的信息，不是重复：


| 数据源                                | 包含什么                                        | 读者                  |
| ---------------------------------- | ------------------------------------------- | ------------------- |
| `classification`（lesson-data.json） | pattern ID + methods ID 列表                  | schema 验证、lint 批量检查 |
| case-index Part 1（by pattern）      | problem-id、题位、**一句话 pattern 描述**、methods 列表 | 模型粗判导航              |
| case-index Part 2（by method）       | problem-id、题位、**涉及步骤**、**解法摘要**             | 模型精判导航              |


**classification 是 pattern/methods ID 的 source of truth**。case-index 的 ID 必须与 classification 一致，但 case-index 额外提供人类可读的导航描述（"2DM+AM 含权重路径"、"第（2）②"、"30° 等腰构造吸收权重后拉直"），这些信息 classification 里没有，也不该有——它们是给模型浏览用的上下文。

lint 批量模式检查一致性：classification 声明了某个 method，case-index Part 2 必须有对应条目；classification 的 pattern 必须在 Part 1 对应分组下有条目。

#### 两个 Part 的关系

Part 1 帮助粗判：模型识别出 pattern 后，看到同类题一共有哪些、各自用了什么方法组合。

Part 2 帮助精判：模型锁定某个 method 后，看到这个方法在不同题中的具体使用方式。

**渐进披露流程（两遍式）**：

1. **粗判**：模型读新题文本 + 读 `junior-math-methods.md` 头部的 pattern 枚举 → 识别 pattern（如 `path-minimum`）。
2. **查 Part 1**：去 `case-index.md` Part 1 的对应 pattern 分组下，看到同类题及其 method 组合 → 初步判断可能需要哪些 method。
3. **查 Part 2**：去 Part 2 的对应 method 分组下，看到具体解法摘要 → 选 1–3 道最相关候选。
4. **精判**：读候选题的 `02_solution.md` → 从解法中确认/修正 method 选择（例如读到西青 25 的解法后才意识到需要"等腰直角三角形吸收权重"）→ 如有需要，回到 Part 2 补看其他 method。
5. **定稿**：确定最终的 pattern、method 列表和参考题，读对应 method 条目的完整内容，开始写解法。

以上是 SKILL 主流程 Step 0 的展开。生成完成后的写回步骤（classification、case-index 更新）见第 4 节完整步骤序列。

**为什么不做工具检索**：

- 当前已发布题 ~25 道，案例目录一页就能读完。模型一次 Read 就能看全，不需要搜索算法。
- 模型自己判断"哪道题的方法和当前题相似"比关键词匹配更准——它能理解数学结构，不只是匹配字面词。
- 不引入新工具 = 不引入新 bug、不增加维护面。
- 等题库超过 100 道、案例目录过长时，再考虑拆分或加辅助工具。

## 4. `lesson-data.json.meta.classification`

在 `lesson-data.json` 的 `meta` 中新增可选字段，让分类标注和题一起 commit，不需要独立索引。

```json
{
  "meta": {
    "id": "tj-2026-hexi-yimo-25",
    "outputPath": "site/problems/tj/25/tj-2026-hexi-yimo-25.html",
    "classification": {
      "pattern": "path-minimum",
      "methods": ["isosceles-right-triangle-transform", "horse-drinking", "coefficient-from-point-on-parabola"]
    }
  }
}
```

`pattern` 是一个字符串（一道题一个主 pattern），`methods` 是一个数组（一道题可涉及多个方法）。这两个字段和 `junior-math-methods.md` 中定义的 ID 对齐。

### 维护方式：融入 SKILL 主流程，不新建独立 skill

`classification` 和 `case-index.md` 的维护作为 SKILL.md 主流程的正式步骤，不是可选的"最后补一下"。

SKILL 主流程更新后的步骤序列：

```
Step 0: 读取方法库和案例目录
        → 读 junior-math-methods.md，识别 pattern 和候选 method
        → 读 case-index.md，选参考题
        → 读参考题的 02_solution.md

Step 1–N: 现有生成流程（01_problem → 02_solution → 03_visual_steps → JSON）

Step N+1: 写 classification
          → 在 lesson-data.json 的 meta 中填写 pattern 和 methods
          → 模型刚写完解法，此时判断最准确

Step N+2: 校验 + 编译
          → validate-geometry-spec.mjs（结构/几何正确性）
          → lint-lesson-quality.mjs（教学质量，warning 不阻塞）
          → build-lesson-page.mjs

Step N+3: 更新案例目录
          → case-index.md Part 1 对应 pattern 下加一行
          → case-index.md Part 2 对应 method 下各加一行
          → 与本题 commit 同步
```

Step 0 和 Step N+1/N+3 是新增的正式步骤，不是可选项。把它们写进 SKILL.md 的步骤序列，模型每次执行 skill 都会走到。

**批量验证**：在 `lint-lesson-quality.mjs`（见第 5 节）中新增检查项：扫描所有已发布题，检查"lesson-data.json 有 classification 字段吗""case-index.md 两个 Part 都有这道题的条目吗"。这是验证而非生成，不需要独立 skill。

为什么不新建独立 skill：这不是一个独立任务，而是生成流程的正式环节。独立 skill 意味着每次发布要"切换上下文"到另一个流程，容易忘；写进主流程就像编译和校验一样，不会跳过。

## 5. 哪些功能应代码化

以下内容应优先从模型声明中移走，改由代码默认化或后处理。

### 实现原则：声明性的用 JSON，过程性的用 JS

不从 Markdown 编译生成 CSS 或 JS。原因：

- CSS 本身已经是声明式语言，从 MD 编译成 CSS 多了一层间接但没增加信息量。
- 逻辑是过程性的（if/then/遍历/正则），Markdown 不擅长表达算法，从 MD 编译成 JS 实质是发明 DSL，维护成本高。
- 两份实现（MD 描述 + 编译出的代码）会漂移。

替代方案：

- **声明性的内容 → JSON 配置文件**：样式 preset、lint 关键词黑名单、默认 policy 值。改配置不需要改代码。JSON 本身就是可读的文档，也是可执行的配置。
- **过程性的逻辑 → JS 代码**：normalizer 遍历、lint 检查、range 补齐。直接写，不从 MD 编译。
- **设计文档（MD）描述 why**：为什么有这条规则、为什么用这个默认值。MD 不做代码源。

### 样式默认化 → `style-presets.json`

一个 JSON 文件定义所有默认样式，normalizer 读取后补齐模型未声明的字段。

字段名与现有 step-decorations / geometry-spec schema 保持一致（`color`/`width`/`dash`/`r`/`size`），不引入 SVG 命名。

preset key 只按 decoration 的 `type` 字段匹配，不引入 `role` 子分类（如 `point.key`、`point.auxiliary`）。原因：现有 schema 没有统一的 `role` 字段，normalizer 无法判断一个 point 是"关键点"还是"辅助点"。模型通过显式写 `color` 覆盖默认值来表达语义差异。

```json
{
  "parabola": { "color": "#2563eb", "width": 2.9 },
  "axisOfSymmetry": { "color": "#94a3b8", "width": 1.4, "dash": "8 6" },
  "point": { "color": "#1f2937", "r": 4 },
  "rightAngle": { "size": 10, "color": "#64748b" },
  "segment": { "color": "#334155", "width": 1.5 },
  "coloredLine": { "color": "#0f766e", "width": 2.1 },
  "dashedLine": { "color": "#94a3b8", "width": 1.6, "dash": "5 5" }
}
```

normalizer 逻辑：对每个 decoration，查 `preset[decoration.type]`，对 preset 中每个字段，如果 decoration 没有该字段则补齐。模型显式写了 `color` 就覆盖默认值。

- 模型写 `{ "type": "point", "at": "P", "color": "#dc2626" }` → 颜色用红色（显式覆盖）。
- 模型写 `{ "type": "point", "at": "O" }` → normalizer 补 `color: "#1f2937", r: 4`。

这个文件同时服务三个角色：normalizer 读取后补齐默认值；模型生成时知道"不用写这些"；人类改一处全局生效。不需要 schema 改动，不需要迁移字段名。

### policy 默认化 → normalizer 自动补齐 + lint 警告

可自动补齐（normalizer）：

- 不可拖动步骤不必每次手写完整 `range: [t,t]`，可由 normalizer 根据 `steps[].t` 自动补齐。
- 主 slider 只在存在真实移动参数时出现。

不自动修正，改为 lint 警告（`lint-lesson-quality.mjs`）：

- 待求系数（如 a、b、c）出现在可拖动 policy 中 → 报警告，不自动改。原因："是否是待求系数"是语义判断而非纯结构信息，自动修正会掩盖模型把 slider 设计错的根因，也可能误伤真实探索参数（有些题确实需要学生拖动参数观察）。

### 图层默认化

- 坐标网格、原点、基础抛物线、对称轴等常见背景可通过 step intent 自动生成。
- Part I / Part II 的多曲线可用 section 或 curve role 自动分层。
- 已知 final-state 点不应进入早期通用图层，可由 lint 检查。

### lint 护栏 → 独立脚本 `lint-lesson-quality.mjs` + `lint-config.json`

教学质量 lint 不放进 `validate-geometry-spec.mjs`。原因：

- `validate-geometry-spec.mjs` 的职责是几何/spec 结构正确性校验（坐标计算、交点有限、折线长度守恒等）。
- 教学质量 lint（禁用关键词、slider policy、视觉进度）是另一类关注点。
- 后续要做"批量验证所有已发布题"，两种检查的触发频率和修复方式不同。
- 混在一起会让 `validate-geometry-spec.mjs` 职责过重。

新建 `tools/lint-lesson-quality.mjs`，读取 `lint-config.json`：

```json
{
  "forbiddenDeriveKeywords": [
    { "keyword": "向量", "allowIfPrecededBy": ["不用", "不要", "禁用", "避免", "不使用"] },
    { "keyword": "投影", "allowIfPrecededBy": ["不用", "不要", "禁用", "避免", "不使用"] },
    { "keyword": "点到直线距离", "allowIfPrecededBy": ["不用", "不要", "禁用", "避免", "不使用"] },
    { "keyword": "斜率夹角公式", "allowIfPrecededBy": ["不用", "不要", "禁用", "避免", "不使用"] },
    { "keyword": "tan(A-B)", "allowIfPrecededBy": ["不用", "不要", "禁用", "避免", "不使用"] }
  ],
  "suspiciousDraggableCoefficients": ["a", "b", "c"]
}
```

**作用域**：只检查 `lesson-data.json` 的 `steps[].derive` 和 `steps[].box` 文本。不检查方法文档（`junior-math-methods.md`）和解题原则（`quadratic-solving-principles.md`），因为这些文档本身会提到禁用方法作为说明。

**否定语境排除**：如果关键词前 N 个字符内出现 `allowIfPrecededBy` 中的短语，跳过不报错。例如 derive 中写"不要用向量"不会触发误报。

`lint-lesson-quality.mjs` 的检查项：

- **自动化、高确定性**：
  - derive/box 文本匹配 `forbiddenDeriveKeywords`，排除否定语境后报错。
  - `suspiciousDraggableCoefficients` 中的系数出现在可拖动 policy 中（报警告，不自动修正）。
  - diagram formula card 与 derive/box 内容重复（报警告）。
  - 直角被标为 `45°`（报错）。
  - classification 字段缺失或 case-index.md 条目缺失（批量模式下报错）。
  - classification 中的 pattern/methods 与 case-index.md 条目不一致（批量模式下报错）。
- **降级为人工 review 注意事项，不做自动化**：
  - 早期步骤出现 final-answer 坐标。原因：没有可计算的 final-answer 来源，lint 无法知道最终答案是什么。
  - 无必要辅助垂足过多。原因："必要"是语义判断。

两个脚本的职责边界：


| 脚本                           | 职责                      | 报告级别                         |
| ---------------------------- | ----------------------- | ---------------------------- |
| `validate-geometry-spec.mjs` | JSON 结构、几何正确性、数学运行时     | error（不通过则阻塞编译）              |
| `lint-lesson-quality.mjs`    | 教学风格、禁用方法、slider 策略、完整性 | error + warning（warning 不阻塞） |


### 构造宏（延后，人工触发）

以下构造在 ≥3 道题出现真实重复后再考虑固化为 schema 扩展：

- `perpendicularFoot`：声明点到轴或线的垂足，由工具展开点、虚线、直角标记。
- `rightTriangleCongruence`：声明两个直角三角形及对应边，由工具生成必要边和角标。
- `isoscelesRightTriangle`：声明直角顶点和等腰边，由工具生成直角、45° 角、等长标记。
- `horsePathStraightening`：声明折线起点、中间点、终点和最短状态，由工具生成移动折线和拉直状态。

当前不新增这些声明类型。先观察已发布题的真实重复模式。

**判断时机与触发方式**：

不为构造宏新建 per-publish skill。原因：

- "是否该固化一个构造宏"是低频的设计决策，不是每道题都该触发的例行检查。
- 构造宏一旦建立会改变 schema 和编译工具，影响面大，不适合自动触发。
- case-index.md 本身就是最好的信号源——当一个 method 分组下有 ≥3 道题、且它们的视觉步骤结构高度相似时，就是考虑构造宏的时候。

在 method 条目中用"构造宏状态"字段追踪成熟度：

```markdown
**构造宏状态**：观察中（2/3）
```

含义：当前有 2 道已发布题出现相似视觉结构，达到 3 道时人工触发讨论——review 这些题的 step-decorations 和 geometry-spec 片段，判断是否值得抽象为宏。

这个决策由人读 case-index 后触发，不由自动化流程触发。构造宏的设计过程本身可以在对话中完成（不需要独立 skill），因为它涉及 schema 设计和工具代码修改，需要反复讨论。

## 6. 模型仍应负责的内容

代码不应替代模型做所有判断。以下内容仍应由模型根据题意和相似题决定：

- 识别题目的 pattern 和关键结构。
- 选择使用哪些 method（读 `junior-math-methods.md` 后判断）。
- 从案例目录中选择最相似的已发布题，并读取其解法作为参考。
- 设计学生可理解的推导顺序。
- 判断哪些构造是数学必要的，哪些只是计算辅助。
- 写出 `01_problem.md`、`02_solution.md`、`03_visual_steps.md` 的教学表达。
- 在特殊题中说明为什么某个常规模板不适用。

模型负责数学意图和教学叙事；代码负责可重复的渲染、默认值、规范化和机械校验。

## 7. 分阶段落地

### Phase 1：方法文件 + 案例目录 + classification 字段

做什么：

- 新增 `internal/knowledge-points/junior-math-methods.md`，头部写 pattern 枚举表，后面写首批 method 条目。
- 新增 `internal/knowledge-points/case-index.md`，Part 1 按 pattern、Part 2 按 method 分组列出现有已发布 25 题和关键 24 题。
- 在 `internal/schemas/lesson-data.schema.json` 中给 `meta` 加可选的 `classification` 字段（含 `pattern` 和 `methods`）。
- 给现有已发布题的 `lesson-data.json` 补上 `classification`。
- 不改 SKILL.md 的实际行为——只是把新文件准备好。

验收：模型手动读方法文件和案例目录后，能为河西 25 第三问识别 pattern 为 `path-minimum`，选出 method `isosceles-right-triangle-transform` 和 `horse-drinking`，且候选相似题包含西青 25 或和平 25。

### Phase 2：SKILL.md 接入知识库

做什么：

- 更新 `quadratic-lesson/SKILL.md`，将知识库操作写入主流程正式步骤：
  - 新增 Step 0：读取 `junior-math-methods.md` + `case-index.md`，识别 pattern/method，选参考题。
  - 新增 Step N+1：在 `lesson-data.json.meta` 中写 `classification`。
  - 新增 Step N+3：更新 `case-index.md`（Part 1 + Part 2 各加一行）。
  - 固定 few-shot（`nankai-25-fewshot.md`）降级为兜底，不再是所有题的默认入口。
- 同步更新 `geometry-lesson/SKILL.md`。

验收：用新 SKILL 生成一道从未见过的 25 题，模型选择的 pattern、method 和参考题合理，不使用非初中方法，且 classification 和 case-index 在生成流程中自动完成。

### Phase 3：教学质量 lint（独立脚本）

做什么：

- 新增 `internal/config/lint-config.json`：禁用关键词黑名单、可疑可拖动系数列表。
- 新增 `tools/lint-lesson-quality.mjs`（独立于 `validate-geometry-spec.mjs`），读取 `lint-config.json`：
  - derive/box 文本匹配禁用关键词（排除否定语境）→ error。
  - 可疑系数出现在可拖动 policy 中 → warning（不自动修正）。
  - diagram formula card 与 derive/box 重复 → warning。
  - 直角被标为 45° → error。
  - classification 字段缺失 / case-index 条目缺失 → error（批量模式）。
- `validate-geometry-spec.mjs` 不变，继续只做几何/结构正确性校验。
- 不改现有已发布题（它们应该已经通过这些检查）。

验收：对现有所有已发布题运行 `lint-lesson-quality.mjs` 通过（无 error）；对一道故意包含"向量旋转"的测试 JSON 报 error；修改 `lint-config.json` 的黑名单后立即生效，不需要改代码。

### Phase 4：normalizer + 样式 preset

做什么：

- 新增 `internal/config/style-presets.json`：所有元素类型的默认颜色、线宽、虚线、半径等。
- `build-lesson-page.mjs` 或新增 `normalize-lesson-spec.mjs`，读取 `style-presets.json`：
  - 模型未声明的样式字段按 preset 补齐。
  - 不可拖动步骤自动补齐 `range: [t, t]`。
- 不自动修正 slider 策略（待求系数可拖动等），这由 Phase 3 的 lint 以 warning 形式报告。
- 逐步减少模型必须声明的样式字段。

验收：用简化后的 JSON（省略默认样式字段）编译出的页面与原页面视觉一致；修改 `style-presets.json` 的颜色后重编译页面立即生效。

## 8. 验收标准（整体）

- 新题能通过 pattern 粗导航 + method 细导航选出 2–3 个真正相似的已发布题，而不是固定引用南开 25。
- 河西 25 第三问这类题会识别 pattern 为 `path-minimum`，触发 method `isosceles-right-triangle-transform` 和 `horse-drinking`。
- 学生主解不出现非初中方法（lint 可检测）。
- 模型产出的 JSON 逐步变短，主要表达数学对象和步骤意图。
- 固定样式和 policy 默认值由工具统一处理。
- 已发布页面的视觉稳定性不被破坏。

## 9. 本次不做的事

本设计文档只描述方向，不实现代码。

本次不修改：

- `quadratic-lesson/SKILL.md`
- `geometry-lesson/SKILL.md`
- `tools/*.mjs`
- `internal/schemas/*.json`
- 任何题目的 `lesson-specs`
- 任何已编译 HTML

本次也明确不做：

- 向量化检索或 embedding 索引。
- 独立的 case card 数据库或生成工具。
- 构造宏 schema 扩展。
- 方法文件拆分为多文件。
- 独立的知识库维护 skill。

这些在规模真正需要时再引入。

## 10. 文件清单（各 Phase 产出物）

### Phase 1

```text
internal/knowledge-points/
├── junior-math-methods.md   ← pattern 枚举表 + method 完整条目
└── case-index.md            ← Part 1 按 pattern 分组 + Part 2 按 method 分组
```

`lesson-data.json.meta.classification` 字段（含 `pattern` 和 `methods`）随各题 commit。

### Phase 3

```text
internal/config/
└── lint-config.json              ← 禁用关键词黑名单、可疑系数列表

tools/
└── lint-lesson-quality.mjs       ← 教学质量 lint（独立于 validate-geometry-spec.mjs）
```

### Phase 4

```text
internal/config/
└── style-presets.json       ← 所有元素类型的默认样式值
```

配置文件（JSON）是声明性的单一源，代码（JS）读取配置执行逻辑。不从 Markdown 编译生成 CSS 或 JS。