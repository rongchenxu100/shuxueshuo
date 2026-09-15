# DeepSeek 视觉切换：第一步验收

2026-09-15，正式批次 **`deepseek-vision-20260915-05`，5/5 通过**。五题在同一实现版本、同一完整批次中完成真实图片抽取，均 accepted，题型、领域语义哈希与现有金标一致，Solver 输入投影语义比较通过。未修改领域契约、数学金标、哈希算法或投影比较器。

| 题目 | 草稿／修复调用 | 独立复核 | 语义调用 | 网络尝试 | 金标／投影 |
| --- | ---: | ---: | ---: | ---: | --- |
| 和平一模 | 2 | 1，confirmed | 3 | 3 | 通过 |
| 和平二模 | 1 | 1，confirmed | 2 | 2 | 通过 |
| 河西一模 | 1 | 1，confirmed | 2 | 2 | 通过 |
| 南开一模 | 1 | 1，confirmed | 2 | 2 | 通过 |
| 西青一模 | 1 | 1，confirmed | 2 | 2 | 通过 |

全部请求使用 `deepseek-flash`、`https://api.deepseek.com` Chat Completions、thinking enabled、reasoning_effort low、JSON object、非流式、16,384 输出 tokens、300 秒 timeout，SDK retries=0。每题均在 3/3/6/12 预算内，未回退供应商。五题使用仓库匹配原图和实际 Paddle 观察夹具，经过真实观察适配器、证据包、默认领域校验器、提取服务与投影器；本批没有 OCR、Planner、Solver 求解或页面生成的外部调用。

独立图像依赖测试保持提示相同、关闭 OCR，仅更换图片内数字，真实模型分别返回 37 和 82。没有将答案放入提示、文件名或发送给模型的元数据。

## 记录与核验

- [summary.json](summary.json)：五题结果、具体语义哈希、图片哈希、调用数、复核触发原因和实现文件哈希。
- [evidence.tar.gz](evidence.tar.gz)：原始模型返回、实际请求的脱敏表示、完整图片字节、复核请求和结果、差异报告、领域草稿、Solver 投影及图像依赖 smoke。约 7 MiB。
- [verify.py](verify.py)：无需模型、OCR 或数据库，核验归档与图片字节、领域金标哈希、预算和当前源码版本。

归档保留模型响应原文；只将顶层报告中的本机目录替换成 `<batch>` / `<repo>`。包含本机 locator 的 checkpoint 不作为公开验收记录收录；内容寻址产物不重写。重复图片按 SHA-256 收录一次，`manifest.json.image_files` 给出图片位置。归档用于审计，不作为产品恢复 checkpoint。

从仓库根目录执行：

```bash
python3 docs/validation/deepseek-vision-step1-20260915/verify.py --check-source
```

正式验收使用以下 CLI。重跑须指定新的 batch-id；pytest 五题用例与该 CLI 共用 `_run_sample`，不要为同一次验收重复执行两个付费入口。

```bash
cd server
RUN_LLM_INTEGRATION=1 uv run python -m shuxueshuo_server.solver.extraction.problem_domain_smoke \
  --case all --samples-per-case 1 --concurrency 5 --provider deepseek \
  --batch-id NEW_UNIQUE_BATCH_ID
```

过程批次 01–04 分别为 0/5、3/5、4/5、3/5，未计入最终通过数。修复集中在提示词的作用域转录、交点表示、坐标归属、禁止推导条件和表达式格式，以及复核对无用纵坐标占位符的误判；没有从不同批次拼接成功样本。

## 离线与产品回归

相关离线与隔离产品测试 285 项通过，覆盖图像完整性、首轮／修复／复核参数和审计一致性、非法 JSON／领域对象、429／5xx／超时、复核结果、持久化预算及崩溃恢复。图像依赖真实 smoke 单独通过。测试中的产品九阶段链使用录制下游响应，仅验证产物登记和 checkpoint；不计作真实九阶段模型构建验收。

本步骤只完成抽取与投影；未部署生产、未清空历史数据、未提前实现通用几何或 unsupported 终态。
