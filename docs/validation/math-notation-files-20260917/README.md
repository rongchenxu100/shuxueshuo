# DeepSeek Files API 与 review Schema 验证

日期：2026-09-17。当前独立数学记法抽取入口已默认使用 Files API，原图上传后在抽取、review、repair 间复用；继续保持 candidate_only，不接入生产 API、Planner 或 Solver。

## Review Schema 实际发送位置

[review 模板](../../../internal/llm-prompts/problem-math-notation-review.md) 是 system 消息。[review_contract.py](../../../server/shuxueshuo_server/problem_understanding/review_contract.py) 将[完整复核 Schema](../../../internal/schemas/problem-math-source-review-v1.schema.json) 注入 user 消息的 `response_schema`。这条传输路径此前已存在，本次补明模板说明，并测试最终 `chat.completions.create(messages=...)` 的实际内容。

测试不仅检查字段名，还将发送的完整 Schema 与文件逐项比较，包含字段说明、枚举、required 和 status/findings 联动约束。`candidate_contract` 是输入候选的摘要；模型应输出的结构由 `response_schema` 定义。DeepSeek 使用 `response_format=json_object`，业务 Schema 由提示词提供并由本地校验器执行。

## Files 接入

- 单次抽取和 review-repair 的 DeepSeek 工厂默认启用图片缓存；按 endpoint、API Key 哈希与图片 SHA-256 隔离。
- 图片原字节不变。缓存以文件锁和原子写入支持并发与重启，远程文件有效期为 24 小时。
- 上传在语义调用预算预留后发生；请求准备、图片检查和版本冻结不会触发上传。
- 实际请求使用 `{"type":"file","file_id":"file-api-…"}`。每次尝试记录 file_id 与图片哈希，文件操作单独记录 `file_api_calls` 与耗时。
- 临近过期刷新；服务器明确报告文件失效时，只在既有第二次尝试内刷新。其他错误不自动上传或回退供应商。失败/未知的已预留流程不会自动再调用。

文件引用与过期参数依照 [DeepSeek 官方 Files API 文档](https://api-docs.deepseek.com/guides/files_api/)。文件复用解决重复上传，不直接减少图片理解或 thinking token。

## 验证结果

**离线回归：592 passed，13 deselected，19.61 秒。** 跳过的是真实模型测试。本次新增 23 项 Files 测试，覆盖：

- 抽取 → review → repair → review 四次推理请求仅上传一次，完整 Schema 进入最终消息；完成后恢复不再调用。
- 跨 provider 实例复用，图片/密钥/endpoint 隔离，并发去重，过期刷新和失效旧引用不覆盖新缓存。
- 上传失败、无效响应、错误图片哈希在推理前停止；失败账本记录 0 次模型网络尝试及已经发生的文件操作。
- 明确文件错误与普通 400/404、超时的分流；持续失效也不超过两次推理网络尝试。
- 使用真实 OpenAI SDK + 模拟 HTTP 端点，核对 multipart 文件内容、过期字段和最终 JSON 文件引用。
- 多页顺序、现有 DeepSeek base64、Doubao 对比入口、数学记法及旧格式回放回归。

运行命令（`server` 目录）：

```bash
uv run pytest -q tests/solver/test_math_notation*.py \
  tests/solver/test_deepseek_files.py tests/solver/test_deepseek_vision.py \
  tests/solver/test_deepseek_vision_empty_retry.py \
  tests/solver/test_problem_domain_retry.py tests/solver/test_problem_domain_recorded.py \
  tests/solver/test_solver_test_profiles.py -m 'not live_llm'
```

**真实 Files API：通过；没有模型推理调用。** 使用准备好的和平一模原图：

| 检查 | 结果 |
| --- | --- |
| 上传原图 | 1 次，347,214 字节，792 毫秒 |
| 新建 provider 实例后再次解析 | 命中同一 file_id，新增上传 0 次 |
| 查询远程文件元数据 | 1 次，ID、字节数与 purpose 校验通过 |
| 文件 API 总请求 | 2 次（上传 + 查询） |
| 总耗时 | 0.898 秒 |
| Chat/模型调用 | 0 次 |

原图 SHA-256：`ee27bd669ca741fe90cd42438f4a78db86f433e42a1432e42a819df0ae2c514d`。

证据：[结果 JSON](../../../internal/solver-runs/math-notation-files-probe-20260917/result.json)、[文件操作](../../../internal/solver-runs/math-notation-files-probe-20260917/file-operations.json)、[验证脚本](../../../internal/solver-runs/math-notation-files-probe-20260917/runner.py)。远程测试文件保留至设置的到期时间，后续同图调用可直接复用。

真实上传与复用验证不等同于新一轮模型提取验收。本次未新增付费推理或重跑七题，历史批次、成绩和冻结文件均未改写。
