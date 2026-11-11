# FP-T2：原照片重新调用与正式页面验收

日期：2026-11-11。范围：A17 与待发布的 C01–C06，覆盖已实现的 R0–R3。用户确认没有新图，因此本轮重新调用 A17 原照片的真实 OCR、模型提取和复核，不将其计为独立新照片留出。题源、人工开发样例与浏览器检查分别记录。

## 1. 结论与发布边界

- A17 的真实识别、课程生成和重新打开通过，答案为 $m=2$。
- 七道题使用正式页面生成器、正式学习 API 和独立 PostgreSQL 验收；桌面、手机各完成 56 个步骤。桌面逐题验证答错不推进、后退重做、中途刷新、完成后刷新、账号记录及自评保存。
- 截图复核发现 C05 将内部 `True` 直接显示在板书中，已在展示代码修复；修复后的 C05 在桌面和手机上重新完成作答，账号保存与刷新恢复通过。数学答案仍为 $p\le0$。
- **这不是公开发布。** 仓库内公开页面、课包和 prompt 共 3,175 个文件逐个比对，无新增、删除或内容变化。公开专题仍只有 A17；C01–C06 继续等待 T2–T5 完成后的统一重建。
- 日常站点 `http://127.0.0.1:8779/topics/function-parity/q17/` 的 HTML 返回 200，但 `/api/learning/content/problems/function-parity-a17` 返回 404：`本题尚未发布或已更新，仍可在当前页面练习。` 因此日常站点目前不能保存 A17；本轮没有修改日常学习库或重启日常服务。统一发布必须同步课程目录与学习库，不能只重启服务。

机器可读汇总及文件哈希见 [summary.json](validation/function-parity-t2-20261111/summary.json)。

## 2. A17 真实调用

沿用用户原图《奇偶性 2.jpg》，整页上传后选取印刷题干与原手写痕迹，未擦除答案、未重绘图片。OCR、DeepSeek 提取与复核均使用已配置的真实服务；登录使用测试短信，课程和私有记录使用隔离数据库。没有向模型传入人工候选或金标。

| 项目 | 记录 |
| --- | --- |
| 搜题记录 | `ded7ee8d5028` |
| 模型阶段 | extract、review 各一次，共两次网络尝试 |
| 题意 | $f(x)=x^2+(2-m)x+m^2+12$ 为偶函数，求 $m$ |
| 关键条件 | 正确保留 `parity(f,even)`；未把手写的 2 变成已知条件 |
| 结果 | `type-parity-parameter`；独立核验 $m=2$；五张方法卡均可交互 |
| 恢复 | 再次打开保持相同 stream 与 snapshot |
| 耗时 | 选框提交到课程就绪 26.283 秒，模型提取／复核流程 17.639 秒；不含整页 OCR，不作为性能保证 |

完整录制见 [r3-acceptance](../server/tests/search/fixtures/function-parity-parameter/r3-acceptance/)，包含原裁片、OCR、模型请求响应、调用账本、API 结果及哈希。之前 `initial` 和 `fixed` 两次记录保留。本轮展示修复后，再以该录制运行禁止真实模型调用的确定性课程回归。

## 3. 正式页面与账号流程

隔离站点没有设置 `preview=true`，使用正常 `/topics/function-parity/q17/` 与 `/topics/function-parity/variant1/` 至 `variant6/` 地址、课包、专题登记、公开教学摘要和后端学习接口。只有文件根与数据库指向临时验收目录；作答、判分、兼容性检查和保存服务没有 mock。短信登录使用本地测试模式，没有发送真实短信或写入日常账号。

| 课程 | 独立核对的结果 | 页面检查 |
| --- | --- | --- |
| A17，二次式偶性求参 | $m=2$ | 桌面、手机、保存及恢复通过 |
| C01，含参域端点 | $a=1$，定义域 $[-2,2]$ | 同上 |
| C02，四次式中的一次项 | $p=0$ | 同上 |
| C03，原分式孔洞 | $p=0$，孔洞不被约分补回 | 同上 |
| C04，分段函数零点条件 | $p=0$ | 同上 |
| C05，$\sqrt{px^2}$ 的自然定义域与奇性 | $p\le0$ | 展示问题修复后重新通过 |
| C06，有限域上的联合参数 | $a=-b$，$b\in\mathbb R$ | 同上 |

桌面宽度为 1106，手机宽度为 390。逐步检查数学渲染和页面横向溢出；所有页面无 KaTeX 错误和未捕获脚本错误。桌面保存请求无 HTTP 错误。七道题均在数据库中达到 `completed`，八步均有记录，自评 `mastered` 在刷新后仍可读取。每题额外试错一次并后退重做一次，错误选择不推进当前步骤。

正式构建与 `--check`、专题导出均通过。临时目录合计 143 道题；仅七道 T2 课程重新执行和构建，其他课程沿用已有产物。A17 的 `bundleVersion`、`practice_version` 均与仓库原正式课包一致，没有通过删除版本检查来通过验收。

首轮桌面记录见 [desktop-initial.json](validation/function-parity-t2-20261111/desktop-initial.json)，手机完整流程见 [mobile-initial.json](validation/function-parity-t2-20261111/mobile-initial.json)。C05 修复后分别见 [桌面复验](validation/function-parity-t2-20261111/desktop-c05-fixed.json)与[手机复验](validation/function-parity-t2-20261111/mobile-c05-fixed.json)。

## 4. 发现与修复

C05 的精确域条件会化简成 SymPy 布尔常量，原展示直接调用 `latex`，使 `True` 进入学生板书。这不改变数学结论，但不是可交付的教学文案。

修改 [parity_original_presentation.py](../server/shuxueshuo_server/graph_lesson/stage_three/parity_original_presentation.py)：恒真条件显示“条件恒成立，不增加参数限制”，恒假条件显示“条件不成立，没有参数满足”。应用于域条件、恒零条件和原参数条件；没有改数学求解、证明证书、判分或 prompt。

复核截图：[初始 C05](validation/function-parity-t2-20261111/c05-mobile-before.png)、[修复后 C05](validation/function-parity-t2-20261111/c05-mobile-fixed.png)。分段原式与联合参数展示分别见 [C04](validation/function-parity-t2-20261111/c04-mobile.png)、[C06](validation/function-parity-t2-20261111/c06-mobile.png)。

首次临时构建脚本缺少 Python 多进程入口保护，子进程重复创建目录而退出；补上入口保护后完成构建。这是验收脚本问题，不是课程算法问题；失败日志保留，没有放宽生产运行预算或错误检查。

## 5. 必要回归与留待事项

修复后运行以下两个模块，共 **14 passed**：

```sh
cd server
PRODUCT_TEST_DATA_DIR=/private/tmp/shuxueshuo-fm-review-20261109 \
PRODUCT_TEST_INSTANCE=fm-review-20261109 \
uv run pytest -q tests/solver/test_graph_stage_three_parity_original.py \
  tests/search/test_function_parity_parameter_photo.py
```

包含自然域根式、恒真／恒假条件的学生展示、原孔洞证书保护、课程导出与恢复，以及三次真实录制的不可变校验和两次成功录制的离线回放。定向 Ruff 与 `git diff --check` 通过。没有因只改展示而重复整个数学测试集。

完整临时站点分别位于 `/private/tmp/fp-t2-formal-pages-20261111`、`/private/tmp/fp-t2-formal-pages-fixed-20261111`；本地验收脚本和执行日志另保留在忽略目录 `internal/review-runs/function-parity-t2-pages-20261111/`。正式录制与本报告的摘要、截图纳入仓库。临时服务和测试数据库验收后停止，数据保留；日常站点不变。

仍未验收：独立新照片留出、A15／A20 的完整父任务、连续参数控件、实际部署和日常学习库同步。本轮不把开发样例的通过推广为所有 T2 题均可处理。未提交、未 push。
