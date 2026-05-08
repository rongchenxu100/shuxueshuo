# 解题过程

## 第（I）问

### Step 1
- 标题：由相似三角形联系两个锐角
- 目标：先看出 △BDE 和 △BAC 相似，再把 ∠CAB 转移到 △ADE 中。
- 推导：
  - ∵ Rt△ABC 中，∠C＝90°，D 是斜边 AB 的中点
  - ∴ DA＝DB＝DC
  - ∵ E 在 BC 上，D 在 AB 上，ED⊥AB
  - ∴ △BDE∽△BAC
  - ∴ DE/AC＝BD/BC
  - ∵ D 是 AB 中点
  - ∴ BD＝AD
  - ∴ AD/DE＝BC/AC
  - ∵ Rt△ADE 与 Rt△ABC 的两条直角边成比例
  - ∴ ∠DEA＝∠CAB
- 当前结论：∠DEA＝∠CAB。

### Step 2
- 标题：由等角传递求 ∠EFD
- 目标：用 F 在线段 AE 上，把 69° 传给 ∠EFD。
- 推导：
  - ∵ F 在线段 AE 上
  - ∴ ∠DEF＝∠DEA
  - ∵ ∠DEF＝69°
  - ∴ ∠CAB＝69°
  - ∵ ∠CAB＝∠EFD
  - ∴ ∠EFD＝69°
- 当前结论：∠EFD＝69°。

## 第（II）问

### Step 1
- 标题：由相似三角形表示 CE
- 目标：先用一个比值 x＝BC/AC 表示 CE。
- 推导：
  - 设 AC＝a，BC＝xa（x＞1）
  - ∵ D 是 AB 中点
  - ∴ AB＝a√(1＋x²)，AD＝BD＝a√(1＋x²)/2
  - ∵ E 在 BC 上，D 在 AB 上，ED⊥AB
  - ∴ △BDE∽△BAC
  - ∴ BE/AB＝BD/BC，DE/AC＝BD/BC
  - ∴ BE＝a(1＋x²)/(2x)，DE＝a√(1＋x²)/(2x)
  - ∴ CE＝BC－BE＝a(x²－1)/(2x)
- 当前结论：CE＝a(x²－1)/(2x)。

### Step 2
- 标题：由等腰三角形表示 EF
- 目标：不用硬套公式，通过垂线和相似求 EF。
- 推导：
  - ∵ ∠DEF＝∠EFD
  - ∴ DE＝DF
  - 过 D 作 DP⊥EF，垂足为 P
  - ∴ P 是 EF 的中点，EF＝2EP
  - ∵ ∠DEP＝∠DEF＝∠CAB，∠DPE＝∠C＝90°
  - ∴ △DEP∽△ACB
  - ∴ EP/DE＝AC/AB
  - ∵ DE＝a√(1＋x²)/(2x)，AB＝a√(1＋x²)
  - ∴ EP＝a/(2x)
  - ∴ EF＝a/x
- 当前结论：EF＝a/x。

### Step 3
- 标题：由 CE＝3EF 求形状比
- 目标：求出 x＝BC/AC。
- 推导：
  - ∵ CE＝3EF
  - ∴ a(x²－1)/(2x)＝3a/x
  - ∴ x²－1＝6
  - ∴ x²＝7
  - ∵ x＞1
  - ∴ x＝√7
- 当前结论：BC/AC＝√7。

### Step 4
- 标题：由勾股定理求 BD
- 目标：求斜边一半 BD。
- 推导：
  - ∵ AC＝2√7，BC＝√7·AC＝14
  - ∴ AB＝√(AC²＋BC²)＝√(28＋196)
  - ∴ AB＝√224＝4√14
  - ∵ D 是 AB 中点
  - ∴ BD＝AB/2＝2√14
- 当前结论：BD＝2√14。
