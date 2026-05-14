# 解题过程

## 第（1）问

### Step 1
- 标题：由对折的中垂线性质得 AH = BH
- 目标：先证 EF 是 AB 的中垂线，进而 AH = BH。
- 推导：
  - ∵ 对折正方形 ABCD，折痕 EF 是中线
  - ∴ AE = BE，EF ⊥ AB
  - ∴ 直线 EF 是 AB 的中垂线
  - ∵ H 在 EF 上
  - ∴ AH = BH
- 当前结论：
  - EF 是 AB 的中垂线
  - AH = BH

### Step 2
- 标题：由折叠 △ABG ≅ △HBG 得 BA = BH
- 目标：用折叠等量关系把 BA 与 BH 连起来。
- 推导：
  - ∵ 沿 BG 折叠把 △ABG 翻到 △HBG（A → H）
  - ∴ △ABG ≅ △HBG
  - ∴ BA = BH，∠ABG = ∠HBG = ½∠ABH
- 当前结论：
  - BA = BH
  - ∠ABG = ½∠ABH

### Step 3
- 标题：由三段相等证 △ABH 等边，求 ∠ABG
- 目标：合并前两步得 △ABH 等边，进而求 ∠ABG。
- 推导：
  - ∵ AH = BH（Step 1）
  - ∵ BA = BH（Step 2）
  - ∴ AH = BH = BA
  - ∴ △ABH 是等边三角形
  - ∴ ∠ABH = 60°
  - ∵ ∠ABG = ½∠ABH
  - ∴ ∠ABG = 30°
- 当前结论：
  - △ABH 是等边三角形
  - ∠ABG = 30°

## 第（2）问

### Step 1
- 标题：由对折得 ∠ACB = ∠ACD = 45°
- 目标：建立角度基础（正方形对角线平分直角）。
- 推导：
  - ∵ 沿 AC 对折正方形 ABCD（图 5）
  - ∴ △ABC ≅ △ADC
  - ∴ ∠ACB = ∠ACD = ½ ∠BCD = ½ × 90° = 45°
  - 等价说法：在等腰直角 △ACD 中，∠ADC = 90°、AD = CD，所以两底角各 45°
- 当前结论：
  - ∠ACB = ∠ACD = 45°

### Step 2
- 标题：列出两次折叠产生的全等与等角关系
- 目标：把折叠 ⇒ 全等 ⇒ 等角的所有信息一次性整理出来，作为后续推理的"工具箱"。
- 推导：
  - ∵ 把 AB 折至 BF（图 6，折痕 BE，E 在 AD 上）
  - ∴ △ABE ≅ △FBE
  - ∴ ∠ABE = ∠FBE，∠BAE = ∠BFE = 90°，BA = BF
  - ∵ 把 BC 折至 BF（图 7，折痕 BG，G 在 CD 上）
  - ∴ △CBG ≅ △FBG
  - ∴ ∠CBG = ∠FBG，∠BCG = ∠BFG = 90°，BC = BF
- 当前结论：
  - 在 F 处：∠BFE = ∠BFG = 90°
  - 在 B 处：∠ABE = ∠FBE，∠CBG = ∠FBG
  - 折叠保距：BF = BA = BC

### Step 3
- 标题：由 F 处两个直角证 E、F、G 三点共线
- 目标：把"折叠像 F"附近的几何关系简化——E、F、G 实际上在一条直线上。
- 推导：
  - ∵ ∠BFE = 90°
  - ∴ 直线 FE ⊥ 直线 BF
  - ∵ ∠BFG = 90°
  - ∴ 直线 FG ⊥ 直线 BF
  - ∵ 过定点 F、垂直于定直线 BF 的直线只有一条
  - ∴ 直线 FE 与直线 FG 是同一条直线
  - ∴ E、F、G 三点共线
  - 等价说法：∠BFE + ∠BFG = 90° + 90° = 180°（平角），所以 E、F、G 在 F 处构成一条直直的线段
- 当前结论：
  - E、F、G 三点共线
  - F 在线段 EG 上

### Step 4
- 标题：由 ∠ABC = 90° 拆分证 ∠EBG = 45°
- 目标：求出折痕 BE 与 BG 在 B 处的夹角。
- 推导：
  - 设 ∠ABE = ∠FBE = α（折叠对称），∠CBG = ∠FBG = β（折叠对称）
  - ∵ B 处由射线 BE、BF、BG 把直角 ∠ABC 顺次拆成 4 块
  - ∴ ∠ABC = ∠ABE + ∠EBF + ∠FBG + ∠GBC = α + α + β + β = 2(α + β)
  - ∵ ∠ABC = 90°
  - ∴ α + β = 45°
  - ∵ ∠EBG = ∠EBF + ∠FBG = α + β
  - ∴ ∠EBG = 45°
- 当前结论：
  - ∠EBG = 45°

### Step 5
- 标题：由 AA 相似得 △BQH ∽ △CQG（"X 同侧"相似）
- 目标：建立第一对相似三角形，得到边比例 BQ/CQ = HQ/GQ。
- 推导：
  - 先把两个 45° 角"翻译"到 △BQH 与 △CQG 的对应顶角：
    - ∵ H = BE ∩ AC ⇒ H 在射线 BE 上 ⇒ 射线 BH 与射线 BE 相同
    - ∵ Q = BG ∩ AC ⇒ Q 在射线 BG 上 ⇒ 射线 BQ 与射线 BG 相同
    - ∴ ∠QBH = ∠GBE = ∠EBG = 45°
    - ∵ Q 在 AC 上 ⇒ 射线 CQ 与射线 CA 相同；G 在 CD 上 ⇒ 射线 CG 与射线 CD 相同
    - ∴ ∠QCG = ∠ACD = 45°
  - ∴ ∠QBH = 45° = ∠QCG
  - 又 ∠BQH = ∠CQG（对顶角）
  - ∴ △BQH ∽ △CQG（AA：两组对应角相等）
  - ∴ BQ/CQ = HQ/GQ = BH/CG
- 当前结论：
  - △BQH ∽ △CQG
  - BQ/CQ = HQ/GQ

### Step 6
- 标题：由比例换边得 △BQC ∽ △HQG（"X 跨侧"相似），证 ∠BHG = 90°
- 目标：用第二对相似三角形把比例转回新的等角，得到关键的直角 ∠BHG。
- 推导：
  - ∵ BQ/CQ = HQ/GQ
  - ∴ 重组比例：BQ/HQ = CQ/GQ
  - ∵ ∠BQC = ∠HQG（对顶角）
  - ∴ △BQC ∽ △HQG（SAS：两边对应成比例，夹角相等）
  - ∴ ∠BCQ = ∠HGQ
  - ∵ Q 在 AC 上 ⇒ 射线 CQ 与射线 CA 相同
  - ∴ ∠BCQ = ∠BCA = ∠ACB = 45°
  - ∴ ∠HGQ = 45°
  - ∵ Q = BG ∩ AC ⇒ B、Q、G 共线，从 G 看 ⇒ 射线 GQ 与射线 GB 相同
  - ∴ ∠HGB = ∠HGQ = 45°
  - ∵ 在 △BHG 中 ∠HBG + ∠HGB + ∠BHG = 180°
  - ∴ ∠BHG = 180° − 45° − 45° = 90°
- 当前结论：
  - △BQC ∽ △HQG
  - ∠BHG = 90°

### Step 7
- 标题：由 Rt△BHG 得 BH/BG = √2/2，由对称的 Rt△BQE 得 BQ/BE = √2/2
- 目标：得到两组关键直角三角形比例。
- 推导：
  - ∵ 在 Rt△BHG 中，∠BHG = 90°，∠HBG = 45°
  - ∴ BH/BG = cos 45° = √2/2
  - 配置中 △BQE 与 △BHG 完全对称（A ↔ C、E ↔ G、H ↔ Q 互换），用与 Step 5、Step 6 平行的推理可得 ∠BQE = 90°
  - ∴ Rt△BQE 中 ∠QBE = 45°，BQ/BE = cos 45° = √2/2
- 当前结论：
  - BH/BG = √2/2
  - BQ/BE = √2/2

### Step 8
- 标题：由 SAS 得 △BQH ∽ △BEG，求 HQ/GE
- 目标：求 HQ/GE 的最终值。
- 推导：
  - ∵ BH/BG = BQ/BE = √2/2（Step 7）
  - ∵ ∠QBH = ∠EBG（同一角，公共顶角）
  - ∴ △BQH ∽ △BEG（SAS：两边对应成比例，夹角相等）
  - ∴ HQ/GE = BH/BG = √2/2
- 当前结论：
  - HQ/GE = √2/2

## 第（3）问

### Step 1
- 标题：设 CG = n 并由折叠得 EG = m + n
- 目标：建立 m、n 之间的初步关系。
- 推导：
  - 设 CG = n
  - ∵ 正方形 ABCD 边长为 1
  - ∴ DG = 1 − n
  - ∵ 折叠后 E、F、G 三点共线，EG 由折叠保留长度：EF = AE = m，FG = CG = n
  - ∴ EG = EF + FG = m + n
- 当前结论：
  - DG = 1 − n
  - EG = m + n

### Step 2
- 标题：在 Rt△DEG 中由勾股定理求 n
- 目标：用 m 表示 n。
- 推导：
  - ∵ E 在 AD 上，AE = m
  - ∴ DE = AD − AE = 1 − m
  - ∵ ∠EDG = 90°（正方形角）
  - ∴ Rt△DEG 中 DE² + DG² = EG²
  - ∴ (1 − m)² + (1 − n)² = (m + n)²
  - 展开：1 − 2m + m² + 1 − 2n + n² = m² + 2mn + n²
  - ∴ 2 − 2m − 2n = 2mn
  - ∴ 1 − m − n = mn
  - ∴ n(1 + m) = 1 − m
  - ∴ n = (1 − m) / (1 + m)
- 当前结论：
  - n = (1 − m) / (1 + m)

### Step 3
- 标题：由（2）问结论求 HQ
- 目标：用 m 表示 HQ。
- 推导：
  - ∵ HQ/GE = √2/2（第（2）问）
  - ∴ HQ = (√2/2) · GE = (√2/2) · (m + n)
  - ∵ m + n = m + (1 − m)/(1 + m) = [m(1 + m) + (1 − m)] / (1 + m) = (1 + m²) / (1 + m)
  - ∴ HQ = (√2/2) · (1 + m²) / (1 + m)
- 当前结论：
  - HQ = (√2/2) · (1 + m²) / (1 + m)

### Step 4
- 标题：由 AB ∥ CD 平行截比求 QC
- 目标：用 m 表示 QC。
- 推导：
  - ∵ AB ∥ CD（正方形对边）
  - ∴ CG/AB = QC/QA（平行线分线段成比例）
  - ∴ CG/(CG + AB) = QC/(QC + QA) = QC/AC
  - ∵ AC = √2，AB = 1，CG = n
  - ∴ n/(1 + n) = QC/√2
  - ∴ QC = √2 · n/(1 + n)
  - ∵ 1 + n = 1 + (1 − m)/(1 + m) = 2/(1 + m)
  - ∴ n/(1 + n) = [(1 − m)/(1 + m)] / [2/(1 + m)] = (1 − m)/2
  - ∴ QC = √2 · (1 − m)/2 = (√2/2) · (1 − m)
- 当前结论：
  - QC = (√2/2) · (1 − m)

### Step 5
- 标题：合并求 HQ/QC
- 目标：求 HQ/QC 的最终代数式。
- 推导：
  - ∵ HQ = (√2/2) · (1 + m²) / (1 + m)
  - ∵ QC = (√2/2) · (1 − m)
  - ∴ HQ/QC = [(1 + m²)/(1 + m)] / (1 − m)
  - ∴ HQ/QC = (1 + m²) / [(1 + m)(1 − m)]
  - ∴ HQ/QC = (1 + m²) / (1 − m²)
- 当前结论：
  - HQ/QC = (1 + m²) / (1 − m²)
