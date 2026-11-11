# FP-T1：真实 OCR、模型复核与课程 API 验收

日期：2026-11-11。已对用户提供的《奇偶性 1.jpg》第 1 题完整运行真实 OCR、模型提取与复核、题型识别、课程生成及重新打开验证。最终两问均通过，8 张方法交互卡全部可交互。**本轮未修改 prompt。**

这是原始开发照片的真实服务调用，不是录制回放，也不是未见过的新照片留出验收。接口通过带认证 Cookie 的 FastAPI TestClient 调用，使用真实隔离 PostgreSQL、Paddle OCR 与 DeepSeek；仅登录短信使用测试实现。本轮没有操作浏览器或逐步提交学生答案，不能将此记录称为浏览器端完整学习流程验收。

## 1. 题源与独立校核

原图：`/Users/haorong/projects/真题/函数奇偶性/奇偶性 1.jpg`。仓库中的[原样归档](../internal/senior-high/source-images/function-parity-planning-20261110/source-image-01.jpg)与该文件字节一致。

- 原图尺寸：1280 × 1706；SHA-256：`ba28d88ca97acf13cec7e64f36887e0af8fb3447de0214cd49f18ecfb4c437ae`。
- 上传整页后，OCR 返回正向图片和 11 个题目区域；这里只验收第 1 题，不据此认定其他题目识别正确。
- 手动选框像素坐标为 `[110, 103, 1065, 180]`，同一次提交包含两个小题。保留原有手写“奇／偶”答案，没有擦除笔迹或重绘公式。
- 金标来自印刷题干的独立阅读与计算，不传入 OCR、提取或复核请求。模型没有把手写答案添加成已知性质。

| 原题 | 独立校核 | 最终模型与代码结果 |
| --- | --- | --- |
| ① $f(x)=\dfrac{x}{x^2+1}$ | 定义域 $\mathbb R$，奇函数 | 原式正确；`type-function-parity`；`odd_only`；独立验证通过 |
| ② $f(x)=|x|+x^2$ | 定义域 $\mathbb R$，偶函数 | 原式正确；`type-function-parity`；`even_only`；独立验证通过 |

两个小题各有独立作用域，均可使用函数名 `f`，不能互相串用函数定义。课程的题意整理卡保留每问自己的源文绑定。

## 2. 真实调用与失败记录

共发起四次完整的新请求；每次均重新整页 OCR、提取及复核。每次各有 2 次模型语义调用、2 次网络尝试，即 `extract` 和 `review` 各一次。四次模型均正确读出两问，复核为 `confirmed`，没有修复调用。失败发生在下游代码接入或交互编译阶段。

| 归档目录 | 搜题记录 | 实际结果 |
| --- | --- | --- |
| `initial/a01` | `c8fb6080766f` | 提取／复核正确；目标重复携带的函数定义被准入当成额外条件，课程 `unsupported` |
| `method-admission/a01` | `e5aaff66bd9f` | 题型已识别；选法阶段仍拒绝重复定义，空方法结果触发执行错误；同时发现 T1 题意整理卡缺少投影 |
| `interaction-timeout/a01` | `60a8401c5ebe` | 两问求解、独立验证、重新打开通过；8 张卡中 1 张超过 5 秒编译预算，降级只读 |
| `fixed/a01` | `900837b56932` | 两问完整通过；8 张卡全部 `interactive`；题意来源定位通过；重新打开保持同一执行流与快照 |

第三次运行同时有 CPU 密集回归测试，超时卡的编译耗时为 5.004 秒。随后等待回归结束，单独完整重跑第四次通过。**没有放宽编译预算，也未证明并发负载下不再发生降级**；第三次结果按失败记录保留，不计为全卡验收通过。

最终一次从选框提交到课程就绪约 56.429 秒，其中提取与复核流程约 41.687 秒，不含此前的整页上传 OCR 耗时。上述时间是该次运行实测，不是性能承诺。

全部证据位于 [function-parity 录制目录](../server/tests/search/fixtures/function-parity/)：包含原始裁图、模型实际输入图、请求与响应、调用账本、源图及文件哈希、API 结果和课程快照。每次整页 OCR 与分题结果另存在对应 `page-01/`。`diagnostics/` 保留前两次原始阶段输出及哈希。已有失败响应没有用成功结果覆盖。

## 3. 代码修复

1. **重复定义准入。** 提取可能同时在小题 `definitions` 和目标 `expression` 中保留同一原式。题型与方法准入共用严格原式匹配：允许绑定变量改名，但函数名和原式 AST 必须一致。不会通过代数约分接受不同原式，不忽略额外限制、其他函数或冲突定义。
2. **执行与来源审计。** 独立验证确认重复定义与目标一致后，记录该条件已处理；两个小题各自执行、保存、恢复，互不覆盖。
3. **空方法结果。** 没有适用方法时保留 `no_applicable_method`，不再访问空的 D4。结果契约允许此状态的空分支，但禁止把空分支包装成已求解或带推荐方法的结果。
4. **题意整理。** 补齐 T1 的原式、任务和源文绑定；有题给定义域／输入范围时同时呈现，避免正文读到条件而整理卡漏掉。该卡不提前给出奇偶答案。
5. **可复用验收工具。** 录制器增加可配置题源目录，新增奇偶性入口；导出器保存真实整页 OCR 与分题记录。原单调性入口的默认值保持不变。

`internal/llm-prompts` 没有变更。规则和容错处理位于代码与契约，不把样题、答案或具体奇偶性算法加入 prompt。

## 4. 回归与复现

新增照片回归使用不可变的真实响应验证：题源／裁图／调用账本哈希、同名函数的两个子目标、手写答案不成为条件、题型与方法执行、D1 来源、独立答案验证、交互发布与重新打开。离线回放明确禁止发起真实模型请求，和上面的四次真实调用分别统计。

| 最终定向回归 | 结果 |
| --- | --- |
| 原图／调用证据、三个真实模型结果回放、双目标发布与恢复、题意整理 | 8 项通过 |
| 奇偶性四类结论发布、独立验证拦截、空方法结果处理 | 6 项通过 |
| 共享阶段三结果契约 | 33 项通过 |
| 本轮涉及的 12 个 Python 文件 Ruff、`git diff --check` | 通过 |

上述定向测试按用例去重共 **47 项通过**。首次此批次为 45 通过、2 失败：照片回归误要求可省略的空 `root.goals` 字段；错误结果测试在补上合法答案结构前被 Schema 提前拦截，未进入待测的空方法语义规则。修正测试后，整个照片模块和空方法用例重跑 9 项通过，没有放宽生产校验。最终日志：`/private/tmp/fp-t1-live-20261111-acceptance-tests.log`、`/private/tmp/fp-t1-live-20261111-acceptance-retest.log`。

从 `server/` 运行真实验收（需要已配置 OCR、模型凭据和隔离数据库；输出目录必须是新目录）：

```sh
RUN_LLM_INTEGRATION=1 \
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
.venv/bin/python -m tools.record_function_parity_photos \
  --output /private/tmp/fp-t1-live-new-run
```

工具保留失败并继续写完整记录，**进程退出码为零不等于验收通过**；必须检查 `summary.json` 中的课程状态、独立结论、全部交互状态及重新打开结果。

对应定向回归：

```sh
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
.venv/bin/python -m pytest -q \
  tests/search/test_function_parity_photo.py \
  tests/solver/test_graph_stage_three_function_parity.py \
  tests/solver/test_graph_stage_three_contracts.py
```

本轮验证了两个 T1 原图目标。其他常见变式的确定性数学与课程覆盖见 [T1 常见变式验收](function-parity-t1-generalization-acceptance.md)；这些离线测试不等价于那些变式的真实照片验收，也不涉及 T2–T6 的实现验收。

## 5. 提交前课包同步

最终修复改变了教学版本，提交前一致性检查发现静态课包需要同步。已通过公共执行器重新求解、独立校验并导出 38 份在用人工题源课包，没有再次调用 OCR 或模型，也没有改写上述真实调用归档。

新增题意整理卡改变了奇偶性两题的作答流程，旧课包 ID 的兼容性检查正确拒绝原地覆盖。因此新入口使用 `function-parity-a01-1-v2`、`function-parity-a01-2-v2`，旧课包与回放文件保留；两题都包含 D1 读题卡。专题总览和公开教学索引同步更新。

`build-graph-walk-topic.mjs --check`、知识图谱及专题总览的一致性检查通过。公开导出回归 7 项通过；新增两张读题卡使导出步骤从 1300 增至 1302，测试同步检查新课包身份和实际 D1 内容。日志：`/private/tmp/fp-precommit-course-refresh-v2-20261111.log`、`/private/tmp/fp-precommit-export-tests-final-20261111.log`。
