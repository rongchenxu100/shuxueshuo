# 函数的表示法：P0 本地验收记录

> 本文保留 P0 完成时的历史快照。2026-11-01 后续已实现 FR-T1 A0 根式换元，当前状态与运行范围见 [A0 验收记录](function-formula-a0-acceptance.md)；下文的 planned、零方法等描述不代表后续运行状态。

日期：2026-11-01。结论：**P0 已完成，新增独立的“函数的表示法”零题专题；FR-T1 开发设计已编写，求解与拍题能力待实施。**

对应[章节计划](function-representations-topic-and-photo-learning-plan.md)和[FR-T1 开发设计](function-formula-problem-type-design.md)。本次只完成章节基础与设计，没有提交、部署或运行真实模型。

## 1. 独立专题与知识组织

| 项目 | 本地结果 |
| --- | --- |
| 专题身份 | `function-representations`，入口 `/topics/function-representations/` |
| 源配置 | [`site/data/knowledge-next/topics/function-representations.json`](../site/data/knowledge-next/topics/function-representations.json) |
| 页面 | [`site/topics/function-representations/index.html`](../site/topics/function-representations/index.html)，由现有专题构建器生成 |
| 章节 | 复用 `chapter-functions`、`section-3-1`，专题标注 3.1.2 |
| 知识组织 | 14 个已有知识节点，按三种表示、求解析式基础、图像变换、分段规则分组 |
| 内容状态 | 4 个待建设题型、0 道练习；显示“题目建设中”，无作答入口、完成率或占位题 |
| 原专题 | `function-concepts` 保留独立入口、5 个分组、29 道练习；源配置与专题首页和工作开始时的 HEAD 完全一致 |
| 同名知识 | `/knowledge/function-representations/` 仍是知识页，与新专题具有不同引用类型和路径 |

共享知识页上的“函数的概念”是前置知识引用，不是把旧专题合并进新专题。两套题目清单各自维护；后续课程身份使用新专题前缀。

## 2. 待建设题型与运行隔离

| 分组 | 节点 ID | 状态 |
| --- | --- | --- |
| FR-T1 求函数的解析式 | `type-function-formula` | `planned` |
| FR-T2 函数图像及其应用 | `type-function-graph` | `planned` |
| FR-T3 分段函数常规问题 | `type-piecewise-function` | `planned` |
| FR-T4 复合型分段函数问题 | `type-piecewise-composition` | `planned` |

四个节点均已整理摘要、题型线索、易混淆任务和相关知识，`methods`、`rules`、`examples` 均为空。没有新增 recognition、selection、execution 契约或代表题课包。FR-T3 是待建设内容入口，后续仍优先复用求值、值域等已有任务的执行能力。

直接加载实际阶段二、阶段三注册表验证：8 个现行判型契约中没有上述节点；即使显式传入这四个类型的判型契约，`evaluate_types` 仍返回空列表。18 个执行契约正常加载，没有 FR-T1 的函数恢复方法。目录可见不等于拍题开放。

## 3. 题源与 FR-T1 设计

- [原图清单](../internal/senior-high/source-images/function-representations-planning-20261030/manifest.json)的 14 张图片 SHA-256 全部相符，原字节未修改。
- 根据用户后续确认，章节台账现为 35 道候选和 6 道上一章排除项。W07 已按用户要求补充“非零”条件，W10 的函数类型更正为二次函数，两题均不再暂缓；见[更正记录](../internal/senior-high/source-images/function-representations-planning-20261030/source-corrections.json)。W10 属于助手误读，不记作原题印刷错误。原图中的教材解说和手写答案不作为开发指令或自动金标。
- FR-T1 设计现覆盖 22 道候选、23 个目标，安排 A0—A3、B、C、D 批次；首批仍为 B05-v2 的根式换元恢复。W10 的解析式是中间结果，其原目标只有不等式解集一项。
- 后续设计明确了 5 个独立方法、1 个新技能“多项式恒等式比较系数”和 1 个选法判断节点；换元与配凑各自登记方法。此次只修订设计，这些节点与运行契约均尚未新增，不计入 P0 已实现能力。
- 首批冻结的是设计边界：固定有理系数的 `f(a√x+b)=ux+v√x+w`、a≠0，证明原域、整体输入范围、覆盖与原关系恒等。更大定义域的未覆盖部分保持不确定。
- 原 P0 用 SymPy 对 20 道题的候选式逐一做符号回代；一次函数复合的系数解集也独立求出并核对。本次更正另核对 W07 的倒数输入恒等关系，以及 W10 的全部二次系数、差分、初值和不等式解集：分别得到 `(4x²+3x+2)/(3x)`（x≠0）及 `(0,7/3)`。累计覆盖设计表 22 道题；这些是设计数学校核，没有调用生产求解器，也没有建立逐题提取金标或照片留出验收。

## 4. 构建与检查

在仓库根目录执行：

```sh
node tools/build-public-knowledge-graph.mjs
node tools/build-topic-overviews.mjs
node tools/build-public-knowledge-graph.mjs --check
node tools/build-topic-overviews.mjs --check
node tools/export-public-knowledge.mjs --check
node --test tools/tests/function-representations-topic.test.mjs tools/tests/topic-overviews.test.mjs tools/tests/public-knowledge-lifecycle.test.mjs tools/tests/function-knowledge-diagrams.test.mjs
git diff --check
```

结果：两项构建一致性检查均为 `changed: 0`；导出检查通过；相关自动化测试 **23 通过、0 失败**；差异空白检查通过。新测试验证同名知识与专题身份区分、新旧专题分别列入目录、零题空态、planned 无作答／练习关联及旧专题题目保留。

导出统计为 109 个节点、360 条边、68 道既有练习、82 条路线、597 个步骤、219 条提示、177 道知识练习。新增的是 4 个 planned 题型与独立零题专题，不新增已验收练习。

共用发布器会重写知识页及教学导出的内容版本；当前版本为 `bbd141f165fcef71f48b791ac3f74dffed1cf9d7be2b4a75daecbd47e0bf7797`。将 `content_version` 排除后，与 HEAD 对比的 68 份既有题目导出、3 份既有专题导出全部相同。这些生成文件的版本更新不代表旧题内容被混入新专题，也不代表已部署。

浏览器检查发现共用题型详情渲染器对没有 `example` 的线索显示“例中 undefined”。本次在 `tools/lib/public-knowledge-html.mjs` 修复缺省示例的渲染，并补回归断言；已有示例内容不变。生成器同时修复原有知识详情页中的同类显示问题。

## 5. 本地页面检查与范围

使用临时静态服务 `python3 -m http.server 8781 --bind 127.0.0.1 --directory site`，在真实浏览器中检查：

1. 专题目录分别显示“函数的概念”和“函数的表示法”；旧专题 29 题，新专题显示建设中。
2. 新专题首页具有四个题型、独立知识梳理与零题空态，没有旧专题题目链接或伪造进度。
3. 点击“求函数的解析式”的“了解题型”到达独立详情页，题型标记建设中；缺省示例不再出现 `undefined`。

截图见[专题目录](../internal/review-analysis/function-representations-p0-20261101/topic-catalog.png)。静态预览不能证明账号隔离、服务端评分、真实拍题、窄屏交互或日常后端服务已通过；这些随代表题双入口建设验证。本次预览服务在检查后关闭，未替换日常服务。

下一项工作为 FR-T1 A0 的 S0 能力探针、S1 原题冻结和后续实现；本次完成不自动将任一 planned 题型标记为可执行。
