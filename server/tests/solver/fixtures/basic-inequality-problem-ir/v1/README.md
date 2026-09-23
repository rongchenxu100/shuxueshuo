# 代表 10 题的阶段 1 输入

范围固定为 q01、q03、q07、q08、q12、q17、q20、q25、q30、q31。
另外 21 题只在后续页面泛化阶段进入，不在这里预建 gold、ProblemIR 或答案。

## 冻结证据

真实提取批次：`internal/solver-runs/basic-inequality-stage1-unified-20260923`，
同一新版显式乘号 Prompt 下 20/20 样本通过。选中样本的完整离线证据位于
`../../math-notation-v1/basic-inequality/samples/`；index.json 记录实际版本、
response ID 和文件字节 hash。回放不依赖原始运行目录，也不跟随 parsed.json
中保留的历史绝对 locator；这些 locator 仅供审计。

旧 live-samples.json 的摘要记录已由完整冻结目录替代。gold/image 的 hash
针对原始字节计算；语义 hash 单独记录。相同响应内容允许来自独立调用，
但同一个 provider response ID 不能当作两份样本。版本变更不会静默覆盖基线；
新基线必须先完成完整独立批次，再显式替换冻结资产并重新生成。

## 离线重建

在 server 目录执行：

```bash
uv run python tools/build_basic_inequality_problem_ir.py --check
uv run pytest -q tests/solver/test_basic_inequality_problem_ir.py
```

去掉 --check 可确定性重建 problem-ir.json 与 provenance.json。
首次建立尚不存在的冻结目录时，可使用：

```bash
uv run python tools/build_basic_inequality_problem_ir.py --freeze-batch ../internal/solver-runs/<完整通过批次>
```

冻结工具在写入前验证全部 20 份样本；文件入口拒绝缺少样本、gold 漂移、
版本漂移、hash 错误、语义比较失败或重用同一次调用。

## 输入与断言

input 只包含题面实体、条件、目标与来源，不包含答案或路线。family_match
是 authoring-only 验证结果，不授权生产执行。定义域义务标记 unverified，
不能作为题面新增事实。

family gate 要求目标非空且每一个目标都属于支持的最值、范围或单参数求值类型；
混入一般表达式求值（ScalarExpression）也会拒绝整题。

定义域义务是逐表达式的实数域必要条件，不是已经求解、消重或验证的完整定义域。
幂目前只支持数字常量、其负号及常量分式形式的有理指数（按最简分数判定）：
偶数分母要求底数非负；负指数要求底数非零，两者同时出现时要求底数为正。
奇数分母的正指数允许负底数；指数中的常数分母不产生变量定义域义务。
符号指数及其他指数运算形式直接拒绝；幂底数中的除法、根号仍递归收集义务。

expected.json 和 route-metadata.json 是审定文档对应的测试侧数据；
教学步骤数不等于 Method 数。q01 文档只描述基础编排，其 3 步基线取自
现有 lesson-data.json；其余步骤数按方法讨论文档第 4 节。q17 的区间验收
同时保存全区间参数化，不能仅靠端点取等验收。
