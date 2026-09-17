# Repair 空路径授权漏洞修复

2026-09-17。P1 已复现并修复。只使用离线、录制响应和独立 PostgreSQL；没有新增付费模型调用。

## 原因与复现

JSON Pointer 的空字符串 `""` 指向整个候选，而 `/root` 指向题目数学分问。此前为补充缺失的 `original_text` 放开空路径，但仅对 `wrong_transcription` 检查目标，没有限制其他 finding。

修复前的两个回归用例实际失败：`wrong_expression` 的空路径生成整题 `source_edit`；`wrong_scope` 的空路径生成整题 `subtree`。顶层不直接包含 facts/children，前者绕过按内容键识别的分问保护；后者把顶层当作内容为空的分问，比较空 inventory 后放行。两种情形均可在改动保护层接受整题重写。

因此不能只补 prompt 或只修 `source_edit` 分支。

## 修复边界

1. **复核契约**：Schema 条件约束规定空路径只允许 `wrong_transcription`。运行时进一步要求候选确实缺失 `original_text`；字段已存在时必须指向 `/original_text`。其他空路径返回 `review.invalid_response`，保留当前候选，不发起 repair。
2. **授权生成**：review 使用经过检查的精确路径。不存在的路径不能沿编译诊断的父路径回退规则扩展权限。即使调用者绕过复核协议校验，非法 review 诊断也不会产生授权。
3. **最终 guard**：拒绝空路径的 `source_edit`、`subtree`、`replace`、`append`；已有可用基准候选时也拒绝 `reextract`。只有没有可用候选时，明确的整题重新抽取仍允许。
4. **稀疏分问容器**：`source_edit` 按 `/root`、`/root/children/N` 等路径识别分问容器，即使只有 label、没有 facts/children，也不能整块替换。
5. **正常行为保留**：缺失原文的空路径转录诊断仍仅授权 `/original_text`；局部数学表达纠错、追加遗漏条件、保留数学内容的分问迁移，以及无候选时的重新抽取继续可用。

外置 review/repair 模板同步说明空路径适用边界。测试检查实际 review 请求所携带的 Schema 与该条件约束一致。没有新增模型输出字段、模型侧 ID 或补丁协议。

## 验证

| 检查 | 结果 |
|---|---|
| 修复前攻击复现 | `wrong_expression`、`wrong_scope` 两例均复现 guard 错误放行 |
| 授权、工作流和诊断定向回归 | [144 passed](repair-authority-targeted.xml) |
| 数学记法及产品题意相关回归 | [676 passed，7 deselected，0 skipped](repair-authority-regression.xml) |
| 最终 affected 门禁映射 | [31 passed](repair-authority-gates.xml) |
| 修改文件 Ruff、git diff --check | 通过 |

测试集合有重叠，不累计。7 项明确排除的是 live 模型测试。产品数据库测试使用真实独立实例 `understanding-p1-test`，目录 `/private/tmp/shuxueshuo-understanding-p1-20260917`，端口 55437，迁移版本 `0003_problem_understanding`。

新增 35 个授权回归覆盖全部非转录 kind 的空路径、uncertain/correction_required、不存在路径向父节点扩权、绕过授权生成直接传入全局 grant、稀疏分问容器、非法 review 停止、正常局部纠错及无候选重新抽取。已有转录补充与修复后再复核用例继续通过。产品录制测试增加两例非法空路径 review：完整原始响应和初始候选保留，调用数停在两次，任务标为复核响应失败。

`test_math_notation_repair_authority.py` 已加入 `solver_test_profiles.py` 的 affected 所有权映射；修改复核契约、授权生成、guard 或相关 Schema/模板时都会选中该门禁。

## 版本影响

本次确实修改了复核 Schema、模板和提取/复核实现文件，故按现有冻结规则，旧运行的复核不能充当当前配置的确认结论。历史候选、响应和复核记录不改写，界面显示复核失效；重新复核仍由用户明确发起，不自动付费重跑。不需要数据库迁移，不改变预算、Files API 或 Solver 准入。

本地整套服务于 16:05（Asia/Shanghai）重启，版本 `fd185e0aba739536f8b7eac81cb96b945dafdff599d4c87baa1ba218dacb65aa`。`services-doctor` 检查通过，四个应用进程、数据库、消息代理和心跳正常，待发布消息及过期租约均为 0。只读核验当前南开题接口：原候选仍为 `parse_status=valid`，`source_status=stale`、`review_stale_reason=configuration_changed`，并保持 `candidate_only=true`、`solver_ready=false`。

## P3：空路径诊断的重复候选

同日继续修复 `review_diagnostics` 将 `pointer(candidate, "")` 放入 `source` 的请求膨胀。空路径诊断现在保存 `source: null`；完整候选仍由 repair 请求的 `base_candidate` 提供，每条缺失原文诊断不再重复携带一份整题 JSON。后续 `repair_permissions` 补全缺少 source 的诊断时，也不会重新填入整份候选。

具体路径的诊断继续保留对应原文或数学表达。finding 的空路径、原图短证据、原文补充授权和越界检查均保持不变；不添加模型输出字段，不更改 budget 或发起模型调用。

修复前已在实际构造的 repair 请求中复现重复 source。修复后 [145 项相关离线回归通过](repair-diagnostic-payload.xml)，覆盖原文缺失/已存在两种完整闭环、诊断补全和数学内容越界拒绝；Ruff 与补丁检查通过。这是请求结构回归，没有宣称实际模型 token 或耗时改进。

本地四个应用服务于 16:21（Asia/Shanghai）重启完成，启动健康检查通过，版本为 `5c802263a7916e9f0e2a7bf8970d9c92f8ea8c7b305a211bc09f71f378abc46c`。
