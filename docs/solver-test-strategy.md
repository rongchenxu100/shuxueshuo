# Solver 测试分级策略

本文档是 Solver 测试入口、分级、并行和 generated gate 维护的唯一规范。

## 目标与基线

改造前，`tests/solver`串行全量基线为：

```text
2186 passed, 12 skipped in 974.03s (16:14)
```

日常开发不再默认运行全量测试。测试按风险分为五级：

| 级别 | Profile | 适用场景 | 目标耗时 |
|---|---|---|---:|
| L0 | `affected` | 当前工作区直接影响的测试 | 通常不超过 60 秒 |
| L1 | `fast` | 每次正常代码修改后的离线回归 | 不超过 2 分钟 |
| L2 | `contract` | authority、retry、checkpoint、transaction 变更 | 不超过 5 分钟 |
| L3 | `full` | 合并前或生成式 oracle 变更后的完整离线门禁 | 不超过 8 分钟 |
| L4 | `live` | 阶段验收时的真实 DeepSeek 冒烟 | 独立计时与付费 |

耗时目标用于发现测试结构退化，不作为不同机器之间的硬性断言。测试不能通过减少场景覆盖来满足耗时目标。

首次启用4-worker门禁的实测结果：

| Profile | 通过数 | 耗时 |
|---|---:|---:|
| `fast` | 1,902 | 1:57 |
| `contract` | 2,206 | 2:49 |
| `full` | 2,260 | 5:31 |

同一版本的Full串行对照为`2,260 passed, 12 deselected in 17:00`，与4-worker结果一致。分片后pytest case数量会增加；Full中的底层语义场景数量与改造前保持一致。

## 本地命令

统一从`server`目录运行：

```bash
uv run python tools/run_solver_tests.py affected
uv run python tools/run_solver_tests.py affected --base origin/main
uv run python tools/run_solver_tests.py fast
uv run python tools/run_solver_tests.py contract
uv run python tools/run_solver_tests.py full
```

常用选项：

```bash
# 查看实际pytest命令，不执行
uv run python tools/run_solver_tests.py contract --list

# 修改worker数量；0表示串行
uv run python tools/run_solver_tests.py full --workers 8

# 输出最慢的40个测试
uv run python tools/run_solver_tests.py contract --durations 40

# 将额外参数传给pytest
uv run python tools/run_solver_tests.py fast -- -x -vv
```

`fast`、`contract`和`full`默认使用4个worker。标记为`serial`的测试由runner自动拆成第二次串行执行。

所有L0-L3 profile都会强制排除`live_llm`，并从子进程环境移除真实provider开关和API key。即使当前shell已经设置`RUN_LLM_INTEGRATION=1`，普通runner也不得调用网络。

## 何时运行哪一级

| 修改内容 | 开发中 | 提交或合并前 |
|---|---|---|
| 单个Method、纯函数、局部parser | `affected`，随后`fast` | `contract` |
| Goal retry、checkpoint、scope、F5-C binding | `affected`，随后`contract` | `full` |
| Macro preparation、transaction、state authority | `affected`，随后`contract` | `full` |
| Prompt、schema、content assembly | `affected`，随后`contract` | `full` |
| generated oracle、scenario generator、adapter | 对应单文件和单scenario | `full` |
| Explanation或Visual局部逻辑 | `affected`，随后`fast` | `contract` |
| 文档 | 不运行Solver测试 | 视关联代码决定 |
| 阶段关闭或真实模型契约变化 | L0-L3 | 额外运行L4冒烟 |

L4仍使用显式命令，例如：

```bash
RUN_LLM_INTEGRATION=1 uv run python -m \
  shuxueshuo_server.solver.scoped_functional_plan_smoke \
  --case all --samples-per-case 3 --concurrency 15 \
  --max-attempts 3 --thinking low --batch-id <batch-id>
```

真实LLM测试不属于普通pytest profile，也不由L3隐式触发。

## Marker 语义

```text
solver_contract  中等成本的authority/retry/checkpoint/transaction测试
solver_full      完整generated matrix或高成本离线回放
generated_gate   确定性生成式门禁
serial           依赖共享进程状态或固定文件位置，禁止xdist
live_llm         可能调用网络或付费模型
```

默认未标记测试属于L1。测试只因为真实成本或语义层级进入更高等级，不能为了隐藏失败而升级marker。

混合测试文件中的真实provider用例必须在函数上标记`live_llm`，不能将整个文件标记为live而丢掉其中的离线测试。

## Affected Ownership

`affected`读取：

1. 相对`HEAD`的staged、unstaged和untracked文件。
2. 传入`--base`时额外读取`base...HEAD`中的提交变更。
3. 显式ownership manifest选出的测试。
4. 固定的小型authority invariant集合。

Production模块按Goal retry、Macro/runtime、Method、Family、Math Kernel、Extraction、Explanation、Visual、Binding和Plan/schema等子系统映射测试。新增Solver子系统但没有ownership规则时必须fail loud，先补映射再继续。

文档和其他非Solver路径不会触发测试。修改测试support或generated fixture时会选择对应门禁。

## Generated Gate

每套大矩阵同时提供Quick和Full入口：

- Quick保留固定历史回归，并按维度优先确定性抽样。
- Full保留全部场景，按`sha256(scenario_id) % 8`分片。
- 8个shard互斥，并集必须等于原矩阵，scenario ID不得重复。
- 元数据测试独立验证场景总数、维度覆盖和分片完整性。

当前规模：

| Gate | Quick | Full |
|---|---:|---:|
| C0-C3 scope-native | 512 | 不少于 10,000 |
| Goal retry | 64 | 512 |
| Runtime authority view | 256 | 4,608 |
| Runtime authority lifecycle | 64 | 256 |
| Symbolic closure | 256 | 2,048 |
| Closure → retry | 64 | 256 |

Quick抽样只影响日常执行成本，不改变Full门禁或历史回归语义。

## 单场景重放

失败报告会输出稳定`scenario_id`和重放命令。可用以下变量精确执行一个场景：

```text
SCOPE_NATIVE_SCENARIO_ID
SCOPE_NATIVE_RETRY_SCENARIO_ID
SCOPE_NATIVE_RUNTIME_AUTHORITY_SCENARIO_ID
SCOPE_NATIVE_C5_SCENARIO_ID
```

例如：

```bash
SCOPE_NATIVE_RETRY_SCENARIO_ID=<id> uv run pytest \
  tests/solver/test_scope_native_goal_retry_generated_gate.py -q
```

设置单场景变量后，完整shard会跳过，只有Quick入口执行该场景，避免重复运行。

## 慢测试定位

1. 先运行对应profile并增加`--durations 40`。
2. 判断耗时来自单个pytest case、单个generated scenario，还是外部provider等待。
3. Generated失败优先用`scenario_id`重放，不重复运行整个矩阵。
4. 可并行的循环应拆为稳定shard，不能只在单个pytest函数内部循环。
5. 共享全局状态必须修复隔离；确实无法并行时才标记`serial`。
6. 不缓存production语义结果，也不降低scenario数量换取速度。

LLM输出超长、retry或sample逐轮问题仍按`llm-sample-failure-review-guide.md`分析；测试分级只负责缩小反馈周期，不替代证据分析。

## 新增测试检查清单

1. 选择最低但足够的层级；普通确定性单元测试保持L1。
2. 涉及authority生命周期时增加L2测试。
3. 新generated维度同时增加Quick覆盖和Full总量断言。
4. 新scenario必须有稳定ID和单场景重放入口。
5. 新Solver模块同步更新affected ownership。
6. 使用网络或真实模型的测试必须标记`live_llm`并默认skip。
7. 使用共享文件或全局registry前先尝试隔离，不能默认标记`serial`。
8. 合并前运行L3；只有阶段验收才运行L4。

本阶段不配置GitHub Actions，但所有profile命令均可直接作为后续CI job入口。
