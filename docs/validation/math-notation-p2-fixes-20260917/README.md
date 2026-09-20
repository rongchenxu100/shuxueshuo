# 四项 P2 修复与验证

本轮修复用户指出的混合诊断、证明对象归属、错误码及图片传输统计问题。离线回归 **671 passed、13 live tests deselected，18.26 秒**；Ruff 通过。没有新增真实模型调用，没有改写历史候选、金标或冻结验收结果。

## 修复内容

| 问题 | 当前行为 | 验证 |
|---|---|---|
| `repair` 与 `code_gap` 同时出现时直接停止 | 先为独立可修字段生成修复权限；修复权限若与缺口路径或其父子路径重叠则移除。完成合法修复后重新诊断，剩余缺口仍以 `code_gap` 阻断。仅有代码缺口时不调用 repair。 | 混合语法/不支持关系、`unstructured` 来源缺口、越权删除缺口、父子权限重叠，以及恢复时不重复调用。 |
| `owners[target[1]]` 缺键抛异常 | 目标与动点的 owner 均用安全读取；缺失、空值或类型不正确时返回无法证明，保留原状态条件。 | 删除参数 owner、删除动点 owner、空字符串及非字符串 owner；编译保持合法但不签发等价证书。 |
| 错误码从消息首段拆出 | `NotationError(code, message=None, ...)` 独立保存机器码，所有生产调用点显式提供常量码；自由消息不参与分流。将误把整句消息当码的调用直接拒绝。 | 更换说明语言、空格、冒号、换行及误导性的其他错误前缀，路由仍只依赖 `reason_code`；旧断言改为校验结构化码和来源。 |
| 实验只支持 Files，KPI 混用 | 新增 `--image-transport files\|base64`。DeepSeek 默认仍为 Files，选择 base64 时不创建 Files 缓存；Doubao 仅支持 base64。冻结输入、单题及批次汇总记录模式，报告按原始请求重建历史模式并分组。 | 两种 DeepSeek 工厂配置、Doubao 非法模式、历史缺少模式标签、缺失请求、混合请求、零上传的缓存命中，以及质量/用量/耗时分组。 |

混合诊断示例：候选包含 `t > (0` 与不支持的 `t ~ 1` 时，只允许修复第一项。合法修复后的候选会保存，但第二项继续阻断，不会进入 review 或被标成通过。删除第二项的返回会被原子拒绝。明确缺图、不可辨认等需要用户确认的来源问题仍直接停止；修复预算、无进展和振荡检查保留。

`state_conditions` 审计与答案等价证明的职责不变：缺少归属信息时不能靠异常处理或省略状态来获得“等价”。

## 历史批次分组统计

根据各次冻结原始请求识别传输方式，没有按当前默认值推测，也没有用 Files API 调用数代替模式识别。Files 缓存命中可能产生零次上传。缺少依据归入 `unknown`，同一题混用方式归入 `mixed`，不会并入任一已知模式的 KPI。

| 冻结批次 | 传输 | 冻结闭环通过 | 语义调用 | Files API 调用 | 输入 token | 输出 token | 调用累计秒 |
|---|---|---:|---:|---:|---:|---:|---:|
| `20260916-222053` | base64 | 5 / 7 | 13 | 0 | 108,059 | 85,189 | 402.122 |
| `20260917-094219` | Files | 6 / 7 | 13 | 3 | 114,391 | 66,593 | 308.109 |

这两批同时存在契约、提示词及金标版本差异，**不是只改变传输方式的对照实验**；表中差异不能归因于 Files。耗时是 provider 调用累计时间，包含传输过程，不是并发墙钟时间；输出 token 已包含 reasoning。

- base64：[分组 KPI](base64/transport-kpi.json)、[逐题统计](base64/case-table.md)、[完整交互报告](base64/outputs.html)。
- Files：[分组 KPI](files/transport-kpi.json)、[逐题统计](files/case-table.md)、[完整交互报告](files/outputs.html)。

报告中冻结时的验收与当前代码离线重验分别显示。旧批次中含已移除目标字段的候选会被当前 Schema 拒绝，不能把该离线结果覆盖为历史真实成绩。本轮生产默认传输方式未改变，也未启用生产 Files。

## 验证命令

从 `server` 目录运行：

```bash
RUN_LLM_INTEGRATION=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -q tests/solver/test_math_notation*.py tests/solver/test_math_tree_audit.py tests/solver/test_deepseek_files.py tests/solver/test_deepseek_vision.py tests/solver/test_deepseek_vision_empty_retry.py tests/solver/test_solver_test_profiles.py -m 'not live_llm'
```

新增诊断路由及传输统计测试已加入 affected 测试选择，后续修改相关模块会自动选中。两个历史报告只读取现有批次，不触发上传或模型调用。
