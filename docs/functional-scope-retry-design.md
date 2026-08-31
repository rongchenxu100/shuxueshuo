# FunctionalPlan Scope Retry 设计

当前生产协议为 `functional-annotated-plan/v1` →
`functional-scope-repair/v1`。

相关设计：[路径最值原子 Macro](path-minimum-macro-redesign.md)。

## 1. 核心原则

Scope 是 LLM 唯一的 Retry 编辑边界。代码识别根因并打开最小必要 Scope；LLM 对每个
开放 Scope 返回完整 authored body；runtime 负责 authority、引用、checkpoint、restore、
validation 和 transaction。

LLM 只需要理解：

1. 哪些 Scope 的 `retry_editable` 为 `true`；
2. 这些 Scope 内完整的 `scope_steps` 和直属 Goal steps 应该是什么；
3. 每个直属 Goal 的答案由哪个 Step return 提供。

LLM 不负责：

- Goal/Step 级编辑权限；
- checkpoint 可复用性；
- placement bookkeeping；
- 局部 step patch 合并；
- authority ID 或 Plan hash 回显；
- Macro 内部 Method、candidate 或 witness。

简化 wire 不降低代码验证强度。所有 replacement 仍需通过严格 Schema、Scope/Goal
identity、引用可见性、capability contract、DAG、答案类型、runtime、restore signature
和最终 Goal closure。

## 2. 所有权

### 2.1 代码持有

- Scope 树、父子关系和 Scope ID；
- required Goal 集合及其 owner、目标对象和答案类型；
- Problem facts、conditions 和初始 SourceRef；
- capability 与 Macro 契约；
- 本轮开放 Scope 集合；
- base Plan、checkpoint、attempt 和内部 authority envelope。

这些内容不能由 Retry response 新建、删除、移动或重命名。

### 2.2 LLM 持有

开放 Scope 的 authored body：

```text
Scope authored body
├── scope_steps[]
└── 全部直属 Goals
    ├── steps[]
    └── answer_from
```

Child Scope 不属于父 Scope replacement；它在 Annotated Plan 中仍作为独立节点存在。

## 3. 输入：`functional-annotated-plan/v1`

Annotated Previous Plan 与 canonical Plan 的 Scope/Goal/Step 树同构，只增加只读执行注解：

```text
functional-annotated-plan/v1
├── schema_version
├── previous_response_error?       # 无法归属到树节点的上一轮响应错误
└── root_scope
    ├── scope_ref
    ├── retry_editable
    ├── diagnostics[]
    ├── scope_steps[]
    │   └── authored step + execution
    ├── goals{goal_ref}
    │   ├── required_answer
    │   ├── execution
    │   ├── steps[]
    │   └── answer_from
    └── children[]
```

所有 Scope 集合字段显式存在，允许为空。`execution`、`retry_editable`、
`required_answer` 和 `diagnostics` 只属于 prompt projection，不进入 canonical Plan、Plan
hash 或 replacement。

### 3.1 Step execution

Step 只有三种公开状态：

```json
{
  "status": "succeeded | failed | not_run",
  "outputs": {},
  "partial_outputs": {},
  "error": {},
  "blocked_by": []
}
```

字段规则：

- `succeeded`：`outputs` 包含本轮实际物化的全部公开 runtime results；未执行的 optional return 不出现。
- `failed` 且 `stage=validation`：没有 runtime output。
- `failed` 且 `stage=runtime`：可以有只读 `partial_outputs`。
- `not_run`：没有 outputs；因上游级联时使用 `blocked_by` 指出直接阻塞源。
- 没有值的空字段可以按 Schema 省略；不得用字段缺失伪装已经物化但无法投影的结果。

每个 output 使用：

```json
{
  "runtime_type": "ExactNumber",
  "value": {"kind": "rational", "numerator": 3, "denominator": 2}
}
```

表达式、精确数值、几何对象、候选集和 witness 必须使用无损、prompt-safe 的公开表示。
如果一个已物化结果无法完整投影，返回非重试型
`functional.retry_runtime_output_projection_invalid`，不能静默截断、替换或省略值。

`partial_outputs` 只用于解释 runtime 失败；事务已经回滚，它不能成为下一版 Plan 的合法
StepResultRef，也不能进入 checkpoint restore seed。

### 3.2 Goal execution

Goal 同样只使用 `succeeded | failed | not_run`：

```json
{
  "status": "succeeded",
  "answer": {
    "runtime_type": "MinimumExpression",
    "value": {"kind": "expression", "expression": "2*sqrt(5)"}
  }
}
```

成功 Goal 的 `execution.answer` 必须与其 `answer_from` 指向的实际 Step output 完全一致。
零个或多个匹配都是 authority/projection 错误。

### 3.3 诊断

诊断就地挂到最接近的 Step、Goal 或 Scope：

```json
{
  "stage": "validation",
  "code": "functional.symbolic_basis_mismatch",
  "message": "该表达式需要一个自由参数，但当前仍有两个独立未知量 b、c",
  "suggestion": "补充一个独立条件，或改用能够同时处理 b、c 的 capability",
  "expected": {"free_symbol_count": 1},
  "observed": {"free_symbols": ["b", "c"]}
}
```

诊断不得暴露 MathObjectId、StateVersion、CallResult、checkpoint、transaction、runtime path
或 Macro 内部 identity。Registry、binding authority、Schema drift 和未知内部异常归为
configuration/nonretryable，不启动 LLM repair。

## 4. Scope authority

### 4.1 打开规则

- Goal-local Step 或 `answer_from` 直接失败：打开该 Goal 的直接父 Scope。
- Scope-owned Step 失败：打开该 Step 的 owner Scope。
- placement/visibility 失败：根据 typed diagnostic 打开最小合法祖先 Scope。
- `not_run`/blocked 节点不单独扩大范围；范围由直接根因决定。
- configuration/nonretryable 错误不开放 Scope。

同一 Scope 中即使一个 Goal 已成功、另一个 Goal 失败，整个 Scope 仍开放；该 Scope 的
所有直属 Goal 都由 LLM 完整返回并重新执行。权限不再下沉到 Goal 或 Step。

### 4.2 影响闭包

- parent 打开不自动开放 child；child 在引用仍合法时保持原样。
- siblings 默认隔离；一个 sibling 失败不开放另一个。
- producer Scope 打开且 consumer 使用 producer Goal 的公开答案时，同轮打开必要的 consumer Scope。
- consumer 读取稳定 SourceRef 时不预先扩大范围；先重放验证，失败后下一轮再按根因开放。
- ancestor scope-owned producer 失败时，打开能合法修复 producer 的最小 Scope，并按真实消费关系扩张。

Annotated Plan 只公开每个 Scope 的 `retry_editable: true/false`。精确 editable 集合、base
Plan hash 和 checkpoint ID 由同步 orchestrator envelope 内部绑定。

## 5. 输出：`functional-scope-repair/v1`

```json
{
  "schema_version": "functional-scope-repair/v1",
  "scope_replacements": {
    "ii": {
      "scope_steps": [],
      "goals": {
        "ii.a": {
          "steps": [
            {
              "step_id": "ii_solve",
              "capability_id": "solve_equation",
              "args": {"equation": "equation_f"}
            }
          ],
          "answer_from": {
            "step_id": "ii_solve",
            "return": "solution"
          }
        }
      }
    }
  }
}
```

严格要求：

1. `scope_replacements` 的 key 精确等于全部 `retry_editable=true` Scope。
2. 每个 replacement 必须包含 `scope_steps` 和该 Scope 的全部直属 Goal。
3. Goal key 不能缺少、增加或重命名。
4. replacement 不能包含 child Scope。
5. 所有 `scope_steps`、Goal `steps` 和 `answer_from` 都必须显式存在。
6. response step 不能复制输入侧 `execution`、`required_answer`、`diagnostics` 或 `retry_editable`。
7. response 不回显 base Plan、checkpoint、attempt 或 authority ID。
8. 多个 Scope replacement 作为一个 candidate Plan 原子应用。

## 6. 引用与答案

正常引用只有两种：

- SourceRef：读取题面已有且在当前 Scope 可见的 Entity/Fact。
- StepResultRef：读取 canonical Plan 中某一步的公开 return。

跨 Goal 只允许引用 producer Goal 当前 `answer_from` 指向的公开 StepResultRef；不能读取另
一个 Goal 的内部 return。跨 Scope 引用仍需满足词法可见性和 typed dependency。

如果 producer 改变：

- 唯一兼容 producer 可由代码确定性重绑；
- 零候选或多候选时打开 Goal owner Scope，并把错误挂到该 Goal；
- LLM 通过完整 Scope replacement 修改 `answer_from`，不存在独立答案补丁协议。

## 7. Macro

Macro 在 Annotated Plan 与 replacement 中都只是一个普通原子 step：

- 输入展示公开 args；
- 成功时展示实际物化的公开 returns；
- 失败时只展示一个 Macro 级根诊断；
- 内部 Method、candidate、winner、shadow branch 和 witness 不成为可编辑 steps。

LLM 可以保留 Macro 并修正公开参数、改选另一个 Macro，或改用 catalog 中的 Functions；
不能编辑 Macro 内部 invocation。

## 8. Apply、restore 与事务

应用顺序：

```text
校验 response Schema 与内部 authority envelope
  -> 对每个开放 Scope 整块替换 authored body
  -> 保留 child Scope 和关闭 Scope
  -> 重建全局 step ID、owner、visibility、DAG 和 answer contract
  -> 计算 restore seed
  -> 执行失效子图
  -> 验证全部 required Goals
  -> 原子 commit
```

Restore 规则：

1. 开放 Scope 内全部 scope steps 和直属 Goal steps 失效，包括上轮成功步骤。
2. 排除这些 calls 的所有 dependency descendants。
3. Scope 外调用只有在 exact read/write/publication signature 与新 Plan 一致时才能恢复。
4. producer 改动必须使相关 consumer checkpoint 失效。
5. child/closed Scope 因上游变化而失效时重放；引用结构失败后下一轮再开放对应 Scope。
6. runtime-failed `partial_outputs` 永远不恢复。

replacement 的任何 validation/runtime/final closure 失败都会回滚 candidate writes。不能出现
部分 Goal 使用新结果、部分 Goal 使用旧结果，或 checkpoint 指向未提交 step identity。

## 9. 多轮 Retry

- Schema/JSON 错误保持相同开放 Scope。
- 可归属错误挂入对应 Scope diagnostics；无法归属时使用 `previous_response_error`。
- 每轮 response 都针对该轮内部绑定的 base Plan 和 checkpoint；过期响应 fail loud。
- no-progress 使用 candidate Plan hash 与 typed issue signature 联合判断。
- 相同 Plan 遇到新的执行诊断仍可继续修复。
- retry budget 耗尽返回 Scope Retry exhausted，不提交失败 candidate Plan。

## 10. Debug

每个 semantic attempt 保存真实且互不覆盖的：

```text
attempt-N.prompt.system.md
attempt-N.prompt.user.md
attempt-N.response.raw.txt
attempt-N.response.parsed.json
attempt-N.annotated-previous-plan.llm.json
attempt-N.internal-scope-authority.json
attempt-N.candidate-plan.json
attempt-N.validation-result.json
attempt-N.runtime-result.json
attempt-N.llm-metadata.json
```

要求：

- `semantic_attempt` 与文件编号一致且连续；
- attempt 1 使用 `functional-plan-content/v2`；建立 canonical Plan 后的 retry 使用 `functional-scope-repair/v1`；
- Pass 1 JSON/Schema 在建立 canonical Plan 前失败时，下一轮仍可使用 Pass 1 协议；
- 每轮 prompt、raw response、parsed response 和 metadata 必须属于真实轮次；
- token、耗时、provider attempt 和最终失败分类可按 semantic attempt 审计。

## 11. 不变量与门禁

### 11.1 不变量

1. Scope 树和 required Goal identity 永远由代码持有。
2. response keys 等于全部且仅开放 Scope。
3. replacement Goal keys 等于对应 Scope 的全部直属 Goal。
4. 开放 Scope 整块替换；关闭 Scope 与 child Scope 不被静默修改。
5. 每个 Goal/Step 恰有一个三态 execution status。
6. 成功 Step 的 outputs 完整覆盖实际物化的公开 runtime results。
7. 成功 Goal 的 answer 等于 `answer_from` 指向的 runtime value。
8. 输入注解不进入 canonical Plan 或 Plan hash。
9. sibling visibility、Goal answer 边界和 Macro 原子性保持严格。
10. replacement 失败无 ghost write；只有全部 required Goals 通过才 commit。

### 11.2 自动化门禁

- Annotated Plan 同构、三态状态和完整 runtime output projection；
- Scope 一成一败、多失败、siblings、ancestor/child 和 placement LCA；
- 多 Scope replacement 原子应用及漏/多 Scope、漏/多 Goal 拒绝；
- 跨 Goal 公共答案、内部 return 拒绝和自动 answer rebind；
- checkpoint restore/invalidation 与 producer-consumer 传播；
- Macro 原子诊断；
- invalid response、no-progress、多轮 retry 和 debug attempt 不覆盖；
- generated Scope Retry 矩阵与 C0–C5 全量 gate；
- 全量 Solver 非 serial 测试优先并行运行。

### 11.3 Live 门禁

- 五题各三份并发运行，三轮内 `15/15` completion；
- protocol、Plan authority、compile、final contract 和 transaction 全通过；
- projection omission、internal identity leak、ghost write、authority drift 和未分类异常为 0；
- 每轮 editable Scope、attempt、restore、runtime output、token 和耗时均可审计。
