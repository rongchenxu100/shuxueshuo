# Scope 事实复用与分层证明搜索

`RuntimeOrchestrator` 默认使用 `scoped-facts/v2`。原始 `RuntimeContext` 仍保留 `bound-conditions/v1` 默认值供直接内核调用和历史测试使用；编排器显式设置运行协议。新证明由分层调度生成，历史证书由独立 checker 回放，不恢复旧单体搜索器。

## 职责

| 层 | 实现入口（相对 `server/shuxueshuo_server/solver/`） | 职责 |
| --- | --- | --- |
| 类型与规则 | `math_kernel/proof_types.py`、`proof_rule_registry.py` | 证明节点、预算和规则契约 |
| 独立检查 | `math_kernel/proof_checker.py` | 校验证书，不调用搜索 |
| 搜索 | `math_kernel/proof_search.py`、`real_proof_strategies.py` | 注册策略、候选排序、分层回退 |
| 证明会话 | `math_kernel/method_proof_session.py`、`proof_search_session.py` | 有界请求、预算与依赖 |
| 事实与索引 | `math_kernel/proof_facts.py`、`proof_fact_index.py` | 已验证事实、相关前提检索 |
| 运行授权 | `runtime/scoped_proof_facts.py`、`proof_fact_transactions.py` | Scope、依赖、版本、登记与恢复 |
| Method 接入 | `runtime/method_proof_integration.py`、`method_proof_backends.py` | 契约内消费事实和发布证据 |

## 事实、身份与授权

事实属于有效 Scope，来源 Method 保留在证据中。复用须同时满足 Scope 可见、调用依赖获准、StateVersion 有效及分支假设成立。未来、失败、过期或未登记的结果不能成为前提。

辅助前提可按目标检索；target、确切前序界和状态输入仍由类型化绑定决定。搜索不能替换调用输入，不能以字符串名称、题号、答案或页面文案决定数学身份。

输入题设经 authenticated 入口接纳；派生事实必须有检查通过的证书与合法发布来源。索引是已验证状态的派生视图，不是另一份权限权威。

## 执行与恢复

一次求解尝试共用一个上下文，Method 按依赖执行。正常调用不逐次复制完整 RuntimeContext 或事实库。输出校验后直接登记已验证记录，并核对调用授权、前序版本及记录未被修改。

失败调用从原始上下文和此前验证通过的公开输出重建，清除失败输出和证明会话；无依赖的调用可以继续。宏内部不同数学候选仍可使用独立上下文。`commit` 等既有字段表示已登记的验证结果，不意味着每次调用都创建分支事务。

磁盘或外部 checkpoint 的恢复须独立回放、核对协议和授权，不复用进程内的“已验证”信任。Scope Retry 的开放范围及恢复签名见[Retry 规范](functional-scope-retry-design.md)。

## 搜索、预算与诊断

策略按确定性顺序提出候选，先使用直接前提、简单结构与授权片段，再进入较昂贵推导。检索保留实际依赖闭包，不把完整历史无条件塞入归约器。失败候选不得污染成功证书，也不退还已消耗工作量。

分支配额与调用方共享预算分开；能力不足、数学不成立、候选预算耗尽和共享预算耗尽分开诊断。不得靠提升预算掩盖循环、权限错误或无关搜索。M11 最小值 effect 的私有配对额度耗尽可尝试下一配对；最大值 effect 及后续正性证明的调用方额度耗尽必须停止。

成功子目标复用绑定完整数学上下文、规则与策略指纹，并保留事实读取依赖。证书节点计数按实际依赖去重；缓存命中不免除外部证据回放或授权检查。上下文改变后必须重新验证适用性。

## Method 与教学

M01 验证完整等价关系及原始定义域；M11 验证本次不等式应用，不能从复用证书中的任意旧 AM-GM 节点猜本次配对；M12/M13 保留原目标、条件、取等和可达性证据。共享事实不改变公开 Method 参数的身份边界。

教学消费已验证的本次应用与公开结果，不能从搜索候选、失败分支或整份证书扫描猜出学生步骤。规则和组件规范见[基本不等式 Method 设计](basic-inequality-method-discussion.md)及[学生步骤绑定](student-step-visual-binding-design.md)。

## 产物与验证

compact/full 产物模式只改变存储与呈现，不改变数学接受条件。序列化的事实及证书按内容哈希复用；完整上下文、授权和恢复材料仍须可核验。性能检查关注重复复制、重复证明、产物编码和索引开销，不以单次机器耗时代替门禁。

历史搜索工具 `server/tools/proof_search_legacy.py` 仅供基线或特定旧证书测试，生产不导入。冻结回归资产见[验证数据](validation/README.md)，测试入口为 `server/tests/solver/test_scoped_proof_search_*.py`，运行分级见[测试策略](solver-test-strategy.md)。
