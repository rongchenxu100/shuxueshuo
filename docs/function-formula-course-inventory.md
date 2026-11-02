# FR-T1 课程与能力台账

更新：2026-11-01。独立“函数的表示法”专题已纳入本型收集的 **22 道题、23 个原始目标、5 个方法小组**。六道题同时开放换元、配凑，合计 28 条课包路线；同题多路线不重复计题。所有下列课包均已通过实际执行与数学验证生成，本地课程齐备；独立新照片 S7 验收仍待完成，尚未部署。

本台账逐项对照专题题目 ID、源配置、公开证据与编译课包。题号沿用[开发设计的题源表](function-formula-problem-type-design.md#22-全部-22-道候选题23-个目标)；原图中的解析及批注不作为开发指令。规范题源记录与各批验收记录分别保留，不重新转录已有题目。

## 正式课包清单

下面每一行的目标、方法及完成状态均已与实际课包核对。“其他路线”表示学生确实可以选择并完成的路线，不包含仅在数学上可能适用的方法。

| 题源 | 原始目标 | 默认方法 | 其他已执行路线 | 本地题页 |
| --- | --- | --- | --- | --- |
| B05-v2 | 求解析式及确定范围 | 换元法 | 配凑法 | `/topics/function-representations/variant02/` |
| W09 | 求解析式 | 换元法 | 配凑法 | `/topics/function-representations/q09/` |
| B05-v1 | 求解析式及确定范围 | 换元法 | — | `/topics/function-representations/variant01/` |
| W11 | 求解析式及确定范围 | 换元法 | 配凑法 | `/topics/function-representations/q11/` |
| B05 | 求解析式 | 配凑法 | 换元法 | `/topics/function-representations/q05/` |
| W02 | 求解析式 | 配凑法 | 换元法 | `/topics/function-representations/q02/` |
| B05-v3 | 先求 f(0)，再求解析式，两个独立目标 | 配凑法；前问用已有代入法 | — | `/topics/function-representations/variant03/` |
| W04 | 求解析式及确定范围 | 配凑法 | 换元法 | `/topics/function-representations/q04b/` |
| B04 | 求 f(1)，所有候选均须检查 | 待定系数法 | — | `/topics/function-representations/q04/` |
| W01 | 求全部合法解析式 | 待定系数法 | — | `/topics/function-representations/q01/` |
| W12 | 求全部合法解析式 | 待定系数法 | — | `/topics/function-representations/q12/` |
| B04-v | 求二次函数解析式 | 待定系数法 | — | `/topics/function-representations/variant04/` |
| W10 | 求 f(x)>0 的解集，恢复二次函数为内部步骤 | 待定系数法 | — | `/topics/function-representations/q10/` |
| B06 | 求解析式 | 构造方程组法 | — | `/topics/function-representations/q06a/` |
| B06-v | 求非零输入上的解析式 | 构造方程组法 | — | `/topics/function-representations/variant06/` |
| W03 | 求解析式 | 构造方程组法 | — | `/topics/function-representations/q03/` |
| W05 | 求非零输入上的解析式 | 构造方程组法 | — | `/topics/function-representations/q05b/` |
| W06 | 求解析式 | 构造方程组法 | — | `/topics/function-representations/q06/` |
| W07 | 求非零输入上的解析式，采用用户修订条件 | 构造方程组法 | — | `/topics/function-representations/q07/` |
| W14 | 求非零输入上的解析式，保留指数右式 | 构造方程组法 | — | `/topics/function-representations/q14/` |
| B07 | 由任意两个实数的关系求解析式 | 赋值法 | — | `/topics/function-representations/q07a/` |
| B07-v | 由任意两个实数的关系求解析式 | 赋值法 | — | `/topics/function-representations/variant07/` |

默认小组题数为：换元 4、配凑 4、待定系数 5、构造方程组 7、赋值 2。小条第 4 题使用 `q04b`，保留既有教材例 4 的 `q04` 路径。原“函数的概念”的题目与分组独立，不追加本表题目。

## 已实现能力及保留边界

| 范围 | 状态与证据 |
| --- | --- |
| 根式、仿射输入的换元与配凑 | 六题均有两条独立路线；数学、原范围、覆盖和终答已验证。见 [A0](function-formula-a0-acceptance.md)、[A1](function-formula-a1-acceptance.md)、[A3](function-formula-a3-acceptance.md)及下方补齐记录 |
| 分式输入换元 | B05-v1 已实现，保留约分前的禁取点；配凑步骤仍未开放，不误判为数学错误。见 [A2](function-formula-a2-acceptance.md) |
| 非单射输入配凑 | B05-v3 的整体恒等、实数覆盖与两个原目标独立完成；不开放一般代数反演。见 [A3](function-formula-a3-acceptance.md) |
| 待定系数 | 五题已实现，保留全部候选及原目标；只求出中间解析式不算完成 W10。见 [B](function-formula-b-acceptance.md) |
| 构造方程组 | 七题已实现，域封闭、合法替换与非退化消元均核验；退化输入按声明诊断。见 [C](function-formula-c-acceptance.md) |
| 赋值 | 两题已实现，保留二元全称量词并精确核验完整原关系；不开放任意函数方程。见 [D](function-formula-d-acceptance.md) |
| 交互及原生评分 | 使用共同读题、判型、五方法预连线、推导卡、范围数轴及回放；本批未新增运行时、方法、技能或判断节点 |
| 照片与发布 | 21 道题、22 个原始目标已有真实原图提取、复核与课程执行证据，覆盖五种方法；W07 原图冲突与批准修订课程分别保留。B05-v3 两问的拍题 API 与再次打开恢复已核对。独立新照片仍待补，当前未部署。见[原图拍题验收](function-formula-photo-acceptance.md) |

## 本批 W04、W11 补齐记录

- W04 原题 `f(√x+1)=x+2√x`。配成 `(√x+1)²−1`，得 `f(x)=x²−1，x≥1`。默认配凑，也可换元。
- W11 原题 `f(√x−2)=x−4`。令 `t=√x−2`，得到 `t≥−2`、`x=(t+2)²`，得 `f(x)=x²+4x，x≥−2`。默认换元，也可配凑。
- 两题均保留原变量自然范围 `[0,+∞)` 与恢复规则的范围，不把多项式的自然定义域当成已确定范围。函数完整定义域未给出，记录仍为 `null`；不擅自填为 R 或半轴。
- 题源：`internal/senior-high/authored-courses/function-formula-roots-20261101/{w04,w11}.json`，记录图 1／图 2 原图路径、SHA-256 和人工核对说明。
- 实际执行录制：`internal/solver-runs/function-formula-roots-20261101/`。W04 运行 ID `5015970197da4b0a9284762c1a13ec78`；W11 运行 ID `fb2c85ef4f8246238fd57ad515aea7b2`。两题各两条路线均验证通过，公开证据由共同导出器生成。
- 必要单元测试：16 项相关 Python 测试通过，覆盖两份题源的合法绑定、两种数学方法及全域／错域／开端点拒绝；31 项相关 Node 测试通过，覆盖课程评分、静态与流式回放、两种路线答案一致、负端点数轴及 22 题分组。没有执行数据库集成测试或全量套件；测试数据库仅用于真实课程执行与导出。
- 浏览器实走 W11 的 7 步，错误的 `x>−2` 不推进，反馈说明原变量 x=0 可取到端点；修正为 `x≥−2` 后完成。W04 的默认配凑回放单独核对。范围卡截图：`internal/review-analysis/function-formula-roots-20261101/w11-range-choice.png`。
- 课程、公共图谱、专题总览生成一致性及空白检查通过。图谱仍为 116 个节点、391 条边。

已知原题的拍题回归已补齐，详见[原图拍题验收](function-formula-photo-acceptance.md)。后续补足未参与开发的新题照片；现有 22 道均为公开开发题，不充作独立留出。W07 原图不含用户批准增加的“非零”条件，保留该差异不影响已完成的修订版课程。独立新照片、服务与发布范围继续分别跟踪，FR-T2 图像题型仍保持待建设状态。
