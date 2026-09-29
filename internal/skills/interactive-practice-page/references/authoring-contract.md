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

节点的公共字段为 `id`、`title`、`question`、`interaction`、`expected_answer`、`feedback`。HTML 配置还包含 `submit_label`、`display`，选择组件可另有 `board`。`display` 是模板 ID，或 `{field, options: {选项值: 模板ID}}`，按已选思路展示。

HTML 模板是题目专属内容。当前简单替换支持 `first` / `second`（本步两个槽位）、`variable` / `other`（所选变量与另一个变量）、`choices` 中已有字段以及 `uid`。全部替换值先转义，不支持运行 JS、任意算式求值或复杂模板条件。重复渲染和历史路径中的 SVG 标题、详情折叠等 ID 使用 `uid` 避免冲突。

注意实际支持范围：当前 `variable` / `other` 面向两个变量；根号槽位及正项标记是二元基本不等式。若新题需要系数项、多个变量或自由表达式，先确定需要的输入形式，再扩展相关公共能力。不要把 `m` 换成一长段 LaTeX 就假定组件和校验都支持。

题干等固定数学内容可以直接使用 HTML；运行时目前对节点问题与选项的 `data-math-text` 使用公共 KaTeX。其他模板若要采用 `$...$`，应明确接入对应渲染，不能留下未渲染的公式定界符。

## 现有组件

| `interaction.type` | 配置 | 预期答案 |
| --- | --- | --- |
| `structure` | `terms`：两个槽位的候选数学项 | `{terms: [...], fixed: "sum"或"product", target: "product"或"sum"}` |
| `amgm` | `terms`：二元基本不等式正项候选 | `{terms: [...]}`，成对项顺序可交换 |
| `equality` | `terms`：取等的成对项候选 | `{terms: [...]}`，成对项顺序可交换 |
| `choice` | `field`：状态答案键；`options`：`{value,label}` 数组；可有 `description` 给老师解释值的含义 | `{one_of: [...]}`，列可接受的候选值 |

`structure` 当前视觉将定和对应求积最大、定积对应求和最小。这依赖正项等教学前提，不是所有极值题的通用规则。候选项与运算需与题意匹配。

当前 `terms` 同时用于候选与 AM-GM 正项展示；不要加入未经验证为正的干扰项。需要辨析错误可使用明确的 `choice`，或按实际需求扩展组件。

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

章节 `/1/` 的六种题型：直接法求最值、常规配凑法求最值、分式分离法求最值、配齐次式求最值、条件消元求最值、换元求最值。按主要训练目标归类，页面可提供多条可行路径。新增其他章节时检查静态入口与独立 API 开发服务的挂载范围，不要假设目前只挂载 `/1` 的开发服务会自动提供所有新章节。
