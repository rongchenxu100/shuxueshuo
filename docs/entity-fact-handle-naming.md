# ProblemIR 引用与 Typed Identity 规范

## 原则

ProblemIR 的 `semantic_ref` 是 wire/display 引用，不是数学身份权威。生产 identity 链为：

```text
semantic_ref
  -> MathObjectRegistry
  -> MathObjectId
  -> LogicalStateKey
  -> StateVersionId
```

名称、handle、StateSlot 字符串、runtime path 或实际值都不能决定对象等价、状态版本或 call 合并。

## Entity 与 Fact

- Entity 表示稳定数学对象：Point、Line、Function、Symbol、Segment 等。
- Fact 表示题设或推导事实：坐标、表达式、长度、角关系、定义域、参数值等。
- 对象从未知到含参再到确定，仍是同一 MathObject；变化由不同 StateVersion 表示。
- 等坐标、等长度或等表达式不自动合并 Entity。
- Answer 是已有 StateVersion 的 projection destination，不是新对象或新 writer。

## Wire 命名

推荐：

```text
point:problem:D
function:problem:parabola
symbol:problem:m
fact:ii:right_angle_DMN
answer:ii.minimum_value
```

规则：

- namespace 与 value type 一致；
- scope 使用 ProblemIR scope id；
- label 稳定、简洁，不编码运行时状态；
- 不在名称中写 open/closed、版本号、runtime path 或 method id；
- question goal 使用唯一 answer ref。

## 解析边界

- 旧 payload 只允许在 load boundary 一次性迁移为 typed identity。
- In-flight Functional 执行不得从字符串重新恢复 MathObject 或 StateVersion。
- Identity-only 参数读取 MathObjectId；materialized 参数读取 exact StateVersionId。
- Latest read 使用 LogicalStateKey 与 scope visibility，不扫描同名 handle。
- Compiler 只能把已选 typed version 投影到 runtime path，不能反向推断身份。

## 歧义

同名对象、同 scope 多版本或一条 wire ref 对应多个 MathObject 时必须 fail loud。允许的 alias 只能来自显式 registry/projection，并在解析后统一到 typed ID。

## 测试重点

- 同名不同对象不合并；
- 同对象不同版本精确读取；
- answer/object projection 共享一个版本；
- sibling-private version 不可见；
- runtime path 相同不代表同一 logical state；
- legacy migration 歧义失败。

详细状态语义由生产 dataclass、B1–B5 测试和 `scope-native-c0-c5-executable-gate.md` 共同约束。
