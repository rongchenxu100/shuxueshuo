# 本地旧抽取输出路径清理

2026-09-16：按当前请求清理本地未提交的结构化 fact JSON 输出实现。独立 `problem_understanding` 入口只支持 `problem-math-notation/v1`；不再保留 `problem-domain/v2` 的解析、生成或自动回退路径。已提交的生产 `solver/extraction` 链不属于此次删除范围。

## 清理内容

- 删除 12 个旧专用实现模块：`acceptance.py`、`authoring.py`、`comparison.py`、`contracts.py`、`equivalence.py`、`geometry_consistency.py`、`intersections.py`、`measure.py`、`normalization.py`、`prompt.py`、`service.py`、`validation.py`。
- `wire.py` 删除旧契约分支；未知版本、旧版本、缺少版本都明确报错。`batch_smoke.py` 只准备新契约金标，CLI 不再接受旧版本。移除 `smoke.py` 中直接运行旧 K 题 fixture 的命令行入口；统一使用批次入口的 `--case` 选择单题或七题。
- 通用 JSON 严格解析、匹配校验和缺图阻断迁至 `candidate_common.py`；OCR 证据投影迁至 `observation.py`；证明预算迁至 `proof_budget.py`。它们不依赖旧 Schema 或旧 fact JSON。
- 数字坐标下的交点唯一性检查直接复用新路径的精确行列式工具，不再借用旧交点对象类。删除 `identity.py` 中只服务旧 DomainValidator 的语义哈希接口。
- 移除 9 个旧测试文件名，其中七题与多供应商测试迁名为 `test_math_notation_seven.py`、`test_math_notation_providers.py`；共享离线 provider 提取到 `_math_notation_test_support.py`。单次调用预算、失败留档、政策接受与严格比较区别、无效 JSON、匹配声明、缺图及候选状态保护测试迁至新契约。
- 新增 `test_math_notation_cleanup.py`：防止旧契约恢复为回退路径，检查请求在模型调用前被拒绝，以及新模块不再引用已删除模块。更新 affected 测试门禁中的文件映射。
- 新七题入口从 `fixtures/math-notation-v1/integration-images-20260916` 读取图片，图片准备工具输出同步迁移。图片来自原审核过的源文件，像素和哈希测试继续执行。
- 更新现行设计文档入口，将旧设计标为历史说明。

删除或迁移的 21 个旧 Python 文件原有 4,656 行，完整文件名及清理前哈希见 [记录](removed-code.json)。这是旧文件统计，包含迁移出去的通用代码和测试，不代表净减少行数。

历史金标、原始模型响应、冻结批次、源图片和验证报告均保留。旧 `understanding-v2` 目录作为历史材料保留，K 题与函数题的原始图片仍可作为图片准备工具的来源；它不再是可执行的旧输出测试入口。历史批次的哈希未改写。旧 v2 的可执行回放能力已随专用代码删除。

## 验证

- [离线测试日志](offline-tests.log)：**298 passed，7 deselected**。旧契约专属测试已移除，数量不再与清理前含旧契约的 469 项直接比较。
- [全部 Solver 测试收集](collection.log)：**2,963 tests collected**，没有悬空导入；这里只收集测试，不代表运行了全部 Solver 回归。
- 清理涉及模块和测试的 Ruff 检查通过；模块编译检查通过；全仓 Python 源码未发现对已删除旧模块的导入。
- [七题保存响应离线回放](replay-final/summary.json)：仍为 **6/7**，K 题仍失败；原批次真实结果仍为 **4/7**。此次网络／模型调用为零。清理没有改变原始响应验收结论。

## 当前入口

从 `server` 运行离线回归：

```sh
uv run pytest -q tests/solver/test_math_notation*.py tests/solver/test_solver_test_profiles.py tests/solver/test_deepseek_vision_empty_retry.py -m 'not live_llm'
```

新格式七题或单题集成测试入口是 `shuxueshuo_server.problem_understanding.batch_smoke`，`--case all` 或 `--case <题目ID>`；默认契约为 `problem-math-notation/v1`。真实调用仍受现有显式环境开关、次数、并发和超时限制，本次没有启动真实调用。
