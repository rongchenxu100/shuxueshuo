# 函数定义域 Q01：零次幂与约分前限制验收

更新：2026-10-26。Q01 已接入共同拍题求解链，并加入本地“函数的概念”专题。专题按 Q15 → Q01 排列：先练根式和分母，再练零次幂与约分前限制。原有代码已先提交为 `c1d0d398`，没有 push；本次 Q01 扩展保留在工作区，未部署生产。

题目：求 $y=(x+4)^0\frac{x^2-1}{x-1}$ 的定义域。

原式要求 $x+4\ne0$ 且 $x-1\ne0$，因此定义域为

$$(-\infty,-4)\cup(-4,1)\cup(1,+\infty)=\mathbb R\setminus\{-4,1\}.$$

即使分式可以约分，也不能补回原式的禁取点 $x=1$；零次幂不能先化成常数而丢掉 $x=-4$。

## 共同能力与边界

- 新知识节点 `integer-power` 属于初中知识集合，包含 `positive-exponent` 与 `zero-exponent` 条目。T2、M1 与 S3 沿用已有节点，没有为本题硬编码一条新方法。
- Stage1 准入扩展到固定非负整数指数 0～12，嵌套幂预算为 64；正整数幂保留底式限制，零次幂增加底数非零条件。零次幂底数、分母和根式限制仍须满足现有仿射范围。
- 新条件 `zero_power_base_nonzero` 使用 `integer-power#zero-exponent` 依据，经 `domain_zero_power_conditions` 正式能力进入同一条件求解、求交集和原式独立验证链。
- Q01 的两个原式位置分别为 `[1,1,1]` 和 `[2]`，均来自 `/root/definitions/0`。条件、位置高亮、解集和端点检查持续保留零次幂／分母的各自来源。
- 读题允许原文 `y=...` 对应规范函数 `f(x)=...`，并允许乘法与分式的等结构分组。比较保留每个原始除数和幂，不允许约分、删掉零次幂或改变指数；`x^{1}2` 不会被误读成 `x^12`。
- 四个数学交互为找限制位置、列条件、解条件、取交集。两个禁取点都有具体原因；限制位置、条件和解集用并列项目展示，不用箭头误示两项之间的推导关系。
- 参数、建模、负整数幂、分数幂、变量指数及二次限制条件仍未开放；本次完成不代表整个定义域题型全部可执行。

## 真实图片与求解证据

用户本轮上传的图片原样保存于[来源目录](../internal/senior-high/source-images/function-concepts-q01/manifest.json)，未重绘、裁切或注入 OCR 答案。图片 SHA-256：`d0882cf0c523a8f4773276d4e02e49d7fa03603fac6f604a284d690195a34405`。

[真实照片录制](../server/tests/search/fixtures/function-domain/q01-recorded-20261026/recording.json)完成 extract + review **两次语义调用、两次网络尝试**，总耗时 **15.378 秒**。结果通过 reviewed candidate 与特征校验，原文保留 `y=(x+4)^0\frac{x^2-1}{x-1}`，规范定义为 `f(x)=(x+4)^0*(x^2-1)/(x-1)`。

随后将该录制交给正式照片 API 与共享 PostgreSQL 执行链，结果为 **solved，4 个数学步骤、4 个数学交互**。最终导出运行 ID：`a0828f4cbe654cc9bcc5686e8c05d9bc`。后续自动化使用录制重验，不计作额外模型调用；本轮没有另做拍题浏览器上传验收。

冻结的[执行与教学证据](../site/data/graph-walk/function-concepts-q01.evidence.json)由正式课程导出器产生，生成[专题课包](../site/data/graph-walk/function-concepts-q01.json)、[AI 回放](../site/data/graph-walk/function-concepts-q01.replay.json)和[题目页面](../site/topics/function-concepts/q01/index.html)。专题与拍题共享同一数学步骤及交互协议。

版本记录：

- `bundleVersion`：`["stream","8f3a0463814094246c4b4d3a9b4becf23468bbe2de452444aa9fe8626d0de1b4","90682692a67de142b65331abeee3ba9ffac9bcfbfcde0cb4facea7b883105aaf","a0828f4cbe654cc9bcc5686e8c05d9bc","/root/goals/0"]`。
- Q01 native `contract_hash`：`a6247acf31a3c4e08e98c3dbabd2211e7b9ad7b1eb9b0997d1f9ff329a897847`。
- 公共 `content_version`：`32dd1d8a3c7f123ad379dda7ae2c0592480a34751761bc4c19085aec3fbab21f`。
- 当前公共图谱 **93 节点、288 条边**，公共内容 **41 道题、52 条路线、273 步**。函数专题仍为 5 个题型分组，其中定义域组有 Q15、Q01 两题，其余组未加入练习。

Q15 的 evidence 与 replay 未修改；bundle 仅同步共享技能摘要中的“零次幂底数”措辞，数学及交互版本不变。Q15 native `contract_hash` 仍为 `90ac818ed6f449351e329fa4d23060c876789badb7c30e364687d5483cf14094`。原 [Q15 验收记录](function-domain-q15-acceptance.md)保留历史范围与计数，以本记录及专题计划为当前扩题状态。

## 验证记录

下列定向套件有重叠，不累计成一个独立测试总数。

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| 数学准入、执行与独立验证 | 119 passed | 零次幂、正整数幂、原分母限制、漏掉任一禁取点的错误结果拒绝、伪造特征不能绕过准入 |
| 新教学投影与既有定义域交互 | 42 passed | 条件来源、位置、答案、端点与幂底数括号 |
| 知识与特征契约 | 95 passed | 新节点、依据操作、可选特征兼容与 schema |
| 主线程最终后端集成 | 25 passed | Q01 原图重验、原文结构反例，Q15/Q01 照片 API、正式导出与两题登录学习记录 |
| 主线程最终前端回归 | 274 passed | 搜索流程、课程 UI、Q01 两位置与端点、共享数学卡、双题专题目录及公共导出 |
| 公共图谱与生命周期 | 30 passed | 93 节点、集合及生成产物一致性 |
| 原生发布内容校验 | 1 passed | 41 道题、52 条路线、273 步及双题课程合同 |
| 构建与静态检查 | 通过 | 课包、公共图谱、专题目录三个构建器 `--check` 均 `changed: 0`，公共导出、Ruff 与 `git diff --check` 通过 |

最终后端集成命令（`server/`）：

```sh
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-function-domain-q01-20261026 PRODUCT_TEST_INSTANCE=function-domain-q01 uv run pytest -q tests/search/test_function_domain_q01.py tests/search/test_function_domain_api.py tests/search/test_function_domain_lesson.py tests/solver/test_graph_stage_three_course_export.py tests/auth/test_function_domain_topic.py
```

最终前端命令（仓库根目录）：

```sh
node --test tools/tests/search-flow.test.mjs tools/tests/graph-walk-ui.test.mjs tools/tests/graph-walk-topic.test.mjs tools/tests/function-domain-powers.test.mjs tools/tests/public-knowledge-export.test.mjs tools/tests/topic-overviews.test.mjs tools/tests/graph-walk-math-dom.test.mjs
```

浏览器在本地预览页确认自己做 **7/7**、AI 回放 **7/7**，切换后各自进度保留。目检原题公式、三条数轴、$-4$ 和 $1$ 的空心点及对应禁取理由正确。普通专题题页可打开并从 D1 开始；专题目录显示两题且顺序正确。

登录后的七步确认、拒绝越步、重试幂等、服务端恢复与已练标记由真实数据库 API 集成测试证明，未另做浏览器登录和真手机验收。截图位于 ignored 的本地审查目录：[完成状态](../internal/review-analysis/function-domain-q01-20261026/topic-complete.png)、[数轴与端点](../internal/review-analysis/function-domain-q01-20261026/number-lines-endpoints.png)，不承诺随 Git 提交保留。

本地静态预览 `8843` 保留。专用测试数据库 `function-domain-q01` 已在验收后正常停止，不修改用户既有题目或生产发布。
