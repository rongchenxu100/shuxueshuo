# 第二步验收：独立题意契约与通用几何表达

实施范围为独立候选契约、校验、定向修改、文件产物和安全展示。生产 extraction
入口、数据库、公共 HTTP API 和产品终态没有切换；没有部署或清空历史数据。

## 已交付

- `server/shuxueshuo_server/problem_understanding/`：五个契约的单一 Schema 定义、
  三个子对象分别解析和保存、服务器身份/修订绑定、独立领域与匹配校验。
- 有类型几何量、精确有理数/根式的受控 AST、有序多边形、定义与 all/any 分支、
  实例私有交点、来源覆盖、待证明义务，以及受限 repair cone。
- `server/tests/solver/fixtures/understanding-v2/`：实际原图/OCR/观察/三轮失败返回、
  人工金标、五题 v2 表达夹具和生成的 Schema 快照。
- [候选渲染样例](candidate.html)、[独立金标校验](gold-validation.json)、
  [合法首包示例](legal-wire-example.json)。样例只展示题意，不生成答案或猜测图形。

独立模块放在 Solver 包之外。新进程测试禁止导入 family/runtime 后仍能完成
本题领域校验与 HTML 渲染；不用替换验证器来绕过独立性约束。

原图没有图 1–4；`□ABCD` 符号不明确。金标保留五个 source gaps，不能宣称
原图无歧义。`complete` 只表示全部可读、受支持内容已编码。

## 离线验证

```sh
cd server
.venv/bin/pytest -q tests/solver/test_understanding_v2.py \
  tests/solver/test_problem_domain_recorded.py \
  tests/solver/test_problem_source_review.py \
  tests/solver/test_deepseek_vision.py --tb=short
```

真实 smoke 前：**141 passed，6 skipped**。6 个 skip 是旧测试入口中未启用的
真实模型用例，不计作本步真实验收。smoke 前新增 65 个测试全部执行，包括 standalone
无 Solver、新旧五题、量纲/引用/覆盖、定义分支和资源上限、修订与 repair、
审计和一次调用预留恢复、转义 HTML 等检查。

最终离线回归：**145 passed，6 skipped**，包含新增69个全部执行的测试。
[完整测试输出](offline-tests.txt)已保存，Ruff 静态检查通过。最终补充了畸形形参选择器、
空领域图、未构造 witness 和 matched 不授予求解资格的回归；冻结的 Schema、提示词内容
及金标保持不变，没有重跑真实模型。

单次 smoke 的离线假 Provider 用例仅测试管线和防重复调用，不作为真实集成通过。
本题文字与金标的一致性验收也不等于任意题目的语义正确性证明。覆盖检查只保证
转录已有的条件/要求有图单元或明确缺口；引用本身不证明图单元正确解释了原文。

## 真实 DeepSeek 验收

本次冻结契约、提示词、金标后，仅执行一次语义调用：

```sh
cd server
env RUN_LLM_INTEGRATION=1 .venv/bin/python \
  -m shuxueshuo_server.problem_understanding.smoke \
  --output ../internal/solver-runs/understanding-v2-single-20260915
```

固定：DeepSeek `deepseek-flash`、enabled/low、json_object、非流式、16,384 tokens、
每次网络尝试 300 秒、SDK retries=0。一次语义调用，最多两次受控网络尝试；无修复、
无独立复核、无供应商回退。已有输出目录中的持久化 reservation 会拒绝再次调用。

结果：**真实门槛未通过**。一次语义调用，两次受控网络尝试，总耗时 121.902 秒。
两次都返回 `finish_reason=length`，`message.content` 为空；各自 16,384 个输出 tokens
全部用于 reasoning，尚未输出业务 JSON。未产生合法转录/领域/匹配，也没有采用候选。
没有追加调用、自动修复、独立复核或 fallback。

| 尝试 | 输入 tokens | 输出 tokens | reasoning tokens | 可见输出 | 耗时 |
| --- | ---: | ---: | ---: | --- | ---: |
| 1 | 25,844 | 16,384 | 16,384 | 空 | 58.743 秒 |
| 2 | 25,844 | 16,384 | 16,384 | 空 | 62.896 秒 |

合计 84,456 tokens。第二次命中 25,600 个输入缓存 tokens，不能据此称为未计费。
未提供金额，不推测费用。

[真实调用摘要](live-summary.json)、[冻结记录](frozen.json)和[完整审计包](live-audit.zip)纳入仓库；完整请求、图片字节、
两轮原始 provider payload（含 usage/finish_reason）和 reservation 保存在
`internal/solver-runs/understanding-v2-single-20260915/`，摘要包含对应文件哈希。
失败时没有业务 JSON，因此没有伪造 parsed/domain diff 产物来冒充已完成验收。

后续若调整请求大小或输出策略，应作为新的、明确授权的实验；本次失败记录不改写，
本步骤不得标记为全部完成。

## 后续边界

Solver readiness 是明确未实现的接口，本步任何匹配结果均不会授予执行资格。
匹配/修复/复核协调及五题新 adapter 验收留在第三步。产品展示与 unsupported
正常终态留在第四、五步。清空与统一发布留在第六步。
