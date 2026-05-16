# 案例目录

本目录只收录已发布且有完整 JSON 规格的题目。`lesson-data.json.meta.classification` 是 pattern / methods ID 的 source of truth；本目录提供给模型快速浏览的人工摘要。

## Part 1：按题型标签 (pattern)

### path-minimum

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `tj-2026-hexi-yimo-25` | 25 | `√2MN+AN`，构造等腰直角三角形转化 `AN` 后折线最短 | `coefficient-from-point-on-parabola`, `right-triangle-congruence-coordinate`, `isosceles-right-triangle-transform`, `horse-drinking` |
| `tj-2026-binhai-yimo-25` | 25 | `BE+DF`，平移一段线段后求折线最短 | `coefficient-from-point-on-parabola`, `translation-path-transform` |
| `tj-2026-nankai-yimo-25` | 25 | `EG+FG`，先证 `EG=DG`，再对称拉直 | `right-triangle-congruence-coordinate`, `isosceles-right-triangle-transform`, `horse-drinking` |
| `tj-2026-heping-yimo-25` | 25 | `OM+BN`，由等长构造把 `BN` 转化后求最小 | `coefficient-from-point-on-parabola`, `tangent-definition-in-right-triangle`, `horse-drinking` |
| `tj-2026-xiqing-yimo-25` | 25 | `2DM+AM` 含权重路径，30° 构造吸收权重后拉直 | `known-root-factorization`, `coefficient-from-point-on-parabola`, `weighted-path-segment-transform`, `horse-drinking` |
| `tj-2026-hedong-yimo-25` | 25 | `AG+GH+FH`，等腰直角与对称构造得到最短路 | `known-root-factorization`, `right-triangle-congruence-coordinate`, `isosceles-right-triangle-transform`, `horse-drinking` |
| `tj-2026-beichen-yimo-25` | 25 | `2AH+√2BH`，构造等腰直角三角形把权重转为折线，再用垂线段最短 | `coefficient-from-point-on-parabola`, `known-root-factorization`, `rotation-by-congruence`, `isosceles-right-triangle-transform`, `weighted-path-segment-transform`, `horse-drinking` |
| `tj-2026-hedong-ermo-25` | 25 | `BG+CG` 反射拉直，`∠OHB=90°` 识别隐圆并由 `HF` 最小值反求 `a` | `coefficient-from-point-on-parabola`, `horse-drinking`, `rotation-by-congruence`, `hidden-circle-minimum` |
| `tj-2026-hongqiao-ermo-25` | 25 | `AG+GF+FE`，由平行四边形转为 `AG+DG+√5`，再用 `A,G,D` 共线求最短；直角条件用距离公式与勾股定理求参 | `coefficient-from-point-on-parabola`, `known-root-factorization`, `coordinate-distance-pythagorean`, `translation-path-transform`, `horse-drinking` |
| `tj-2026-heping-ermo-25` | 25 | `HF+FM+MG`，由正方形中心与全等直角三角形关系化为 `AG+MG`，再反射拉直求最短 | `known-root-factorization`, `right-triangle-congruence-coordinate`, `horse-drinking` |

### distance-difference-maximum

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `tj-2026-nankai-ermo-25` | 25 | 由抛物线对称轴把距离差转成三角形两边差最大 | `known-root-factorization`, `rotation-by-congruence`, `axis-symmetry-distance-difference` |

### coefficient-constraint

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `tj-2026-hexi-jieke-25` | 25 | 抛物线过 `A(-1,0)`，结合 `2a+b=0`、线段/角度条件求参数 | `coefficient-from-point-on-parabola`, `known-root-factorization` |
| `tj-2026-hebei-yimo-25` | 25 | `2a-b=0` 固定对称轴，`P(3,3)` 化简解析式；由 `NI=7a` 和 `15NI−7MH=7` 得 `H(15a+2,5)`，代入抛物线提取公因式求 `a` | `coefficient-from-point-on-parabola`, `axis-parallel-segment-coordinate` |
| `tj-2026-hongqiao-yimo-25` | 25 | 已知根因式分解，倍角构造求 `a`，等角直线和铅垂面积求 `M` | `known-root-factorization`, `coefficient-from-point-on-parabola`, `angle-doubling-isosceles-construction`, `equal-angle-reflection-line`, `vertical-area-decomposition` |

### folding-ratio-expression

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `sh-2026-yangpu-ermo-25` | 25 | 正方形折纸，证明角度、定比 `HQ/GE`，再用 `m` 表示 `HQ/QC` | `folding-congruence-relations`, `perpendicular-bisector-from-fold`, `similar-triangle-ratio-transfer`, `pythagorean-algebraic-expression`, `parallel-line-segment-ratio` |

### moving-point-translation-area

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `tj-2026-binhai-yimo-24` | 24 | 菱形水平平移，与矩形重叠面积分段 | `translation-overlap-area`, `area-piecewise-by-overlap` |
| `tj-2026-dongli-yimo-24` | 24 | 等腰直角三角形平移，与平行四边形重叠面积分段 | `translation-overlap-area`, `area-piecewise-by-overlap`, `isosceles-right-triangle-transform` |
| `tj-2026-hexi-yimo-24` | 24 | 三角形平移，与固定图形重叠面积和范围 | `translation-overlap-area`, `area-piecewise-by-overlap` |

### moving-point-folding-area

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `tj-2026-hedong-ermo-24` | 24 | 正方形折叠后求重合面积和参数 | `folding-overlap-area`, `area-piecewise-by-overlap` |
| `tj-2026-heping-ermo-24` | 24 | 梯形折叠后求重叠面积范围 | `folding-overlap-area`, `area-piecewise-by-overlap` |
| `tj-2026-nankai-ermo-24` | 24 | 四边形折叠与重叠面积范围 | `folding-overlap-area`, `area-piecewise-by-overlap` |

### moving-point-rotation-area

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `tj-2026-nankai-yimo-24` | 24 | 三角形旋转后求线段、范围与重叠面积 | `rotation-overlap-area`, `area-piecewise-by-overlap` |

### parameter-range-inequality

| problem-id | 题位 | pattern 补充 | 使用的 methods |
|---|---|---|---|
| `bj-2026-chaoyang-yimo-26` | 26 | 由函数值同号和大小关系求参数 `a` 范围 | `parameter-range-by-sign-and-order` |
| `bj-2026-haidian-yimo-26` | 26 | 铅直距离 `m=a|t²-t-2|`，由恒成立条件求 `a` 范围 | `coefficient-from-point-on-parabola`, `vertical-distance-absolute-value` |

## Part 2：按解题方法 (method)

### known-root-factorization

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hexi-jieke-25` | 25 | 第（Ⅰ）问、第（Ⅱ）公共结论 | 由 `A(-1,0)` 在抛物线上化简解析式，并配合系数关系继续求参 |
| `tj-2026-nankai-ermo-25` | 25 | 第（I）问、第（II）① | 由 `x` 轴交点写分解式，再配合旋转条件求参数 |
| `tj-2026-xiqing-yimo-25` | 25 | 第（2）① | 由已知根 `A(-1,0)` 读出另一个交点和截距 |
| `tj-2026-hedong-yimo-25` | 25 | 第（Ⅱ）① | 由 `A(-1,0)` 与 `B(-c,0)` 写出交点关系和坐标 |
| `tj-2026-beichen-yimo-25` | 25 | 第（Ⅰ）问、第（Ⅱ）问 | 由已知根 `A(-2,0)` 确定 `b`，再读出另一个交点 `B(8,0)` |
| `tj-2026-hongqiao-ermo-25` | 25 | 第（Ⅱ）①② | 由已知根 `A(-2,0)` 写出 `B(2−4b,0)` 与 `C(0,2b−1)` |
| `tj-2026-hongqiao-yimo-25` | 25 | 第（Ⅱ）①② | 由 `A(-1,0)` 是根写 `y=(x+1)(ax+c)`，读另一个交点 |
| `tj-2026-heping-ermo-25` | 25 | 第（Ⅱ）公共结论 | 由 `A(-c,0)` 是根得到 `b=1-c`，读出另一个交点 `B(1,0)` 与对称轴交点 `M((1-c)/2,0)` |

### coefficient-from-point-on-parabola

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hexi-jieke-25` | 25 | 第（Ⅱ）①② | 由点在抛物线和线段/角度条件求参数 |
| `tj-2026-hexi-yimo-25` | 25 | 第（Ⅱ）问、第（Ⅲ）问 | 先几何求 `D` 或 `M` 坐标，再代入抛物线求系数 |
| `tj-2026-binhai-yimo-25` | 25 | 第（2）问 | 由 `A`、`D` 等点在抛物线上化简并求 `b` |
| `tj-2026-heping-yimo-25` | 25 | 第（Ⅰ）①、第（Ⅱ）问 | 由 `A`、`D` 在抛物线上求解析式，再由最值反求 `a` |
| `tj-2026-xiqing-yimo-25` | 25 | 第（2）①② | 由 `A(-1,0)` 在抛物线上化简，再由线段关系和最值反求 `b` |
| `bj-2026-haidian-yimo-26` | 26 | 第（1）问 | 由抛物线过 `O` 与 `(2,0)` 求 `c` 和 `b` |
| `tj-2026-beichen-yimo-25` | 25 | 第（Ⅰ）问、第（Ⅱ）问 | 代入 `A(-2,0)` 求解析式，再把旋转后的 `Q` 代入抛物线求 `P` |
| `tj-2026-hebei-yimo-25` | 25 | 第（Ⅱ）公共结论、第（Ⅱ）①② | 由 `P(3,3)` 在抛物线上得到 `c=3-15a`，再配合轴平行线段条件求参数 |
| `tj-2026-hedong-ermo-25` | 25 | 第（Ⅰ）②、第（Ⅱ）问 | 由 `A`、`C` 在抛物线上化简求 `B`；第（Ⅱ）由 `F` 在抛物线上得到 `am` 关系 |
| `tj-2026-hongqiao-yimo-25` | 25 | 第（Ⅰ）问、第（Ⅱ）② | 由点在抛物线上化简系数关系，并配合面积条件求参数 |
| `tj-2026-hongqiao-ermo-25` | 25 | 第（Ⅰ）问、第（Ⅱ）①② | 由 `A(-2,0)` 代入得到 `c=2b−1`，再配合直角条件或最短值求 `b` |

### coordinate-distance-pythagorean

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hongqiao-ermo-25` | 25 | 第（Ⅱ）① | 由 `A(-2,0)`、`B(2−4b,0)`、`C(0,2b−1)` 写三边平方，用 `AC²+BC²=AB²` 求 `b` |

### axis-parallel-segment-coordinate

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hebei-yimo-25` | 25 | 第（Ⅱ）公共结论、第（Ⅱ）② | 先由 `x=2` 得 `NI=7a`，再由 `15NI−7MH=7` 得 `MH=15a−1`，直接写 `H(15a+2,5)` 并代入抛物线提取 `15a+2` |

### right-triangle-congruence-coordinate

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hexi-yimo-25` | 25 | 第（Ⅱ）问 | 作垂线，证 `Rt△AOC≌Rt△DHA`，读出 `D(b+1,1)` |
| `tj-2026-nankai-yimo-25` | 25 | 第（Ⅱ）① | 作垂线，证直角三角形全等，确定 `N(2,1-m)` |
| `tj-2026-hedong-yimo-25` | 25 | 第（Ⅱ）① | 由直角等腰条件作辅助线，用全等读出点坐标 |
| `tj-2026-heping-ermo-25` | 25 | 第（Ⅰ）② | 过 `G` 作 `GQ⊥x轴`，填充并证明 `Rt△AEM≌Rt△GAQ`，读出 `G(t-3,-2)` |

### rotation-by-congruence

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-nankai-ermo-25` | 25 | 第（II）① | `AC` 绕 `C` 旋转 90° 得 `DC`，作垂线证全等求 `D` |
| `tj-2026-beichen-yimo-25` | 25 | 第（Ⅱ）问 | `BP` 绕 `P` 逆时针旋转 90°，由横纵距离交换读出 `Q(3+p,p+5)` |
| `tj-2026-hedong-ermo-25` | 25 | 第（Ⅱ）问 | 由 `OE⊥OF` 且 `OE=OF`，作坐标轴垂线，用全等直角三角形读出 `F` 坐标 |

### isosceles-right-triangle-transform

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-dongli-yimo-24` | 24 | 第（1）问、第（2）问 | 平移等腰直角三角形，使用斜边与直角边关系读坐标/长度 |
| `tj-2026-hexi-yimo-25` | 25 | 第（Ⅲ）问 | 构造等腰直角三角形 `AQN`，把 `AN` 转化为 `√2·QN` |
| `tj-2026-nankai-yimo-25` | 25 | 第（Ⅱ）① | `△DMN` 是等腰直角三角形，辅助证明路径转化 |
| `tj-2026-hedong-yimo-25` | 25 | 第（Ⅱ）①② | 直角等腰条件确定点，再参与最短路径构造 |
| `tj-2026-beichen-yimo-25` | 25 | 第（Ⅲ）问 | 构造等腰直角三角形 `BHR`，把 `√2BH` 转化为 `2HR` |

### weighted-path-segment-transform

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-xiqing-yimo-25` | 25 | 第（2）② | 将 `2DM+AM` 改写为 `2(DM+1/2 AM)`，构造 30° 直角三角形吸收权重 |
| `tj-2026-beichen-yimo-25` | 25 | 第（Ⅲ）问 | 将 `2AH+√2BH` 转化为 `2(AH+HR)`，再研究折线 `A-H-R` |

### horse-drinking

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hexi-yimo-25` | 25 | 第（Ⅲ）问 | `√2MN+AN` 转为 `√2(MN+QN)`，`Q,N,M` 共线且垂直时最短 |
| `tj-2026-nankai-yimo-25` | 25 | 第（Ⅱ）①④、第（Ⅱ）② | 先转化 `EG=DG`，再用对称点 `D′` 拉直求 `EG+FG` 最小 |
| `tj-2026-heping-yimo-25` | 25 | 第（Ⅱ）问 | 把 `BN` 转化为等长线段，`O,M,G` 共线时取最小 |
| `tj-2026-xiqing-yimo-25` | 25 | 第（2）② | 权重转化后看折线 `D-M-N`，三点共线取最小 |
| `tj-2026-hedong-yimo-25` | 25 | 第（Ⅱ）② | 通过对称/构造把多段路径转成直线最短 |
| `tj-2026-beichen-yimo-25` | 25 | 第（Ⅲ）问 | 折线 `A-H-R` 拉直后，转为点 `A` 到定直线 `ℓ` 的垂线段最短 |
| `tj-2026-hedong-ermo-25` | 25 | 第（Ⅰ）② | 将 `C` 关于 `AD` 对称为 `C′`，把 `BG+CG` 拉直为 `BG+C′G` |
| `tj-2026-hongqiao-ermo-25` | 25 | 第（Ⅱ）② | `A`、`D` 在直线 `BC` 两侧，折线 `AG+DG` 在 `A,G,D` 共线时最短 |
| `tj-2026-heping-ermo-25` | 25 | 第（Ⅱ）问 | 将 `A` 关于 `G` 所在水平线反射为 `A′`，折线 `A′G+GM` 在 `A′,G,M` 共线时最短 |

### hidden-circle-minimum

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hedong-ermo-25` | 25 | 第（Ⅱ）问 | 由 `∠OHB=90°` 识别 `H` 在以 `OB` 为直径的圆上，画完整隐圆并拖动 `H`，用 `FK−半径` 求 `HF` 最小值；同时讨论 `C` 在 `y` 轴上下半轴两种情况 |

### translation-path-transform

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-binhai-yimo-25` | 25 | 第（2）② | 将 `DF` 平移成等长线段，转化 `BE+DF` 的最小值 |
| `tj-2026-hongqiao-ermo-25` | 25 | 第（Ⅱ）② | 用平行四边形得到 `GF=DE`、`FE=DG`，把 `AG+GF+FE` 转为 `AG+DG+√5` |

### axis-symmetry-distance-difference

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-nankai-ermo-25` | 25 | 第（II）② | 利用对称轴把距离差转为三角形两边差，三点共线取最大 |

### tangent-definition-in-right-triangle

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-heping-yimo-25` | 25 | 第（Ⅰ）② | 由 `∠CBE+∠ACO=45°` 转化角度，在直角三角形中用 tan 定义求点 |

### translation-overlap-area

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-binhai-yimo-24` | 24 | 第（2）①② | 菱形水平平移，与矩形重叠面积分段 |
| `tj-2026-dongli-yimo-24` | 24 | 第（2）①② | 平移等腰直角三角形，与平行四边形重叠面积分段 |
| `tj-2026-hexi-yimo-24` | 24 | 第（II）①② | 三角形平移，计算四边形面积和面积范围 |

### folding-overlap-area

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hedong-ermo-24` | 24 | 第（Ⅱ）问、第（Ⅲ）问 | 正方形折叠后重合区域分段求面积 |
| `tj-2026-heping-ermo-24` | 24 | 第（Ⅱ）①② | 梯形折叠后重叠区域和面积范围 |
| `tj-2026-nankai-ermo-24` | 24 | 第（II）①② | 四边形折叠，确定五边形阶段和面积范围 |

### rotation-overlap-area

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-nankai-yimo-24` | 24 | 第（II）①② | 三角形旋转后求关键线段、参数范围和重叠面积 |

### area-piecewise-by-overlap

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-binhai-yimo-24` | 24 | 第（2）①② | 由重叠五边形和阶段端点求面积范围 |
| `tj-2026-dongli-yimo-24` | 24 | 第（2）①② | 按平移阶段分析重叠区域面积 |
| `tj-2026-hedong-ermo-24` | 24 | 第（Ⅲ）问 | 折叠重合面积按阶段计算 |
| `tj-2026-heping-ermo-24` | 24 | 第（Ⅱ）② | 折叠重叠面积范围 |
| `tj-2026-hexi-yimo-24` | 24 | 第（II）② | 平移三角形重叠面积范围 |
| `tj-2026-nankai-ermo-24` | 24 | 第（II）② | 折叠四边形重叠面积范围 |
| `tj-2026-nankai-yimo-24` | 24 | 第（II）② | 旋转三角形重叠面积范围 |

### parameter-range-by-sign-and-order

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `bj-2026-chaoyang-yimo-26` | 26 | 第（2）问 | 由函数值同号和大小关系分情况求 `a` 范围 |

### vertical-distance-absolute-value

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `bj-2026-haidian-yimo-26` | 26 | 第（2）①② | 同一竖直线上的两交点距离写成绝对值，求零点和恒成立范围 |

### folding-congruence-relations

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `sh-2026-yangpu-ermo-25` | 25 | 第（1）问、第（2）问 | 由折叠得到三角形全等、对应边相等和对应角相等 |

### perpendicular-bisector-from-fold

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `sh-2026-yangpu-ermo-25` | 25 | 第（1）问 | 对折得到 `EF` 是 `AB` 的中垂线，从而 `AH=BH` |

### similar-triangle-ratio-transfer

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `sh-2026-yangpu-ermo-25` | 25 | 第（2）问 | 先证 `△BQH∽△CQG`，再重组比例证 `△BQC∽△HQG`，最终求 `HQ/GE` |

### pythagorean-algebraic-expression

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `sh-2026-yangpu-ermo-25` | 25 | 第（3）问 | 在 `Rt△DEG` 中列勾股方程，得到 `CG=(1-m)/(1+m)` |

### parallel-line-segment-ratio

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `sh-2026-yangpu-ermo-25` | 25 | 第（3）问 | 由 `AB∥CD` 的平行截比求 `QC`，再合并求 `HQ/QC` |

### angle-doubling-isosceles-construction

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hongqiao-yimo-25` | 25 | 第（Ⅱ）① | 作 `A` 关于 `y` 轴的对称点 `A'`，用等腰三角形处理 `∠CAB=2∠ABC` |

### equal-angle-reflection-line

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hongqiao-yimo-25` | 25 | 第（Ⅱ）② | 由 `∠ABM=∠ABC` 构造镜像点 `C'`，确定 `BM` 所在直线 |

### vertical-area-decomposition

| problem-id | 题位 | 涉及步骤 | 摘要 |
|---|---|---|---|
| `tj-2026-hongqiao-yimo-25` | 25 | 第（Ⅱ）② | 用竖直线 `CC'` 把 `△MBC` 分成左右两个三角形，列面积方程求 `b` |
