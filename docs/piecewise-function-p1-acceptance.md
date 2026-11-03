# FR-T3 P1：例10分段求值本地验收

日期：2026-11-02。范围为例10本地课程与共享求值链路；自动裁框偏紧按用户指示暂缓，未修改相关逻辑。

## 交付

- 专题新增 `function-representations-b10`，页面 `/topics/function-representations/q10a/`，位于“分段函数常规问题 → 代入法”；专题累计 27 题。
- 题源为归档图8第97页例10，定义的 `x≤0`、`x>0` 及两层调用已核对。人工核对记录：`internal/senior-high/authored-courses/piecewise-p1-20261102/b10.json`，含原图 SHA-256。
- 复用 `type-function-evaluation` 和 M9 代入法；不新增方法、技能或选法节点。分段内容组织节点保持 planned，不冒充通用分段求解能力。
- 学生逐项完成内层选段、内层计算、按中间值重选段、外层计算；完成态保留原条件、当前输入和数学推导。最终结果 `f(f(√2))=f(-1)=0`。
- 受控分段语法、开闭条件、分界缺口、源定义绑定、冻结版本及独立回验已接入共享链路；读题能匹配原始 LaTeX 分段公式和 `\sqrt2` 写法。

## 验证证据

运行目录：`internal/solver-runs/piecewise-p1-20261102/b10-authored-final`；运行 ID `4dc7c6f98ffd4ea09ec85129dde71aac`。原题目标求解完成，结果为0；导出 D1 有来源行、无诊断，交互课程可编译。`source_admission=authored_topic`，不标记成真实图片提取通过。

必要单元测试共18项通过（1.23秒）：

```text
tests/solver/test_graph_piecewise_evaluation.py
tests/solver/test_graph_function_evaluation_math.py::test_bound_names_and_nested_order
tests/solver/test_graph_function_evaluation_runtime_contract.py::test_public_skill_outputs_are_consumed_and_original_conditions_survive
```

覆盖：内外层换段；0的闭端点；缺段与无定义传播；别段分母隔离；显式域冲突；重叠和超范围结构拒绝；选段证据篡改；来源条件匹配；冻结版本；共享技能及拆步卡；旧 M9 嵌套调用和分式限制。修改的数学、语法、教学投影和测试文件 Ruff 检查通过，`git diff --check` 通过。未运行全量测试或真实模型提取。

本地页面已检查：分段公式可见；AI 回放由内到外重新选段并到达结果0。专题入口按代入法分组。

## 后续

下一批 B10-v1：由分段函数值5反求输入，逐段解方程、与本段范围取交，再合并为 `{-3/2,2}`。先补分段方程合同，再接本地课程。P1 真实照片提取／复核、私有上传与独立留出仍待验收；FR-T2 裁框问题暂缓。
