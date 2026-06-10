# 03_visual_steps

## 整体图形策略

- 本题原图只有题面文字，没有印刷图形，因此不添加 `originalFigures`。
- 第（Ⅰ）问只显示代入后的抛物线、对称轴和顶点。
- 第（Ⅱ）问先用一个未求解的代表状态显示 \(AB=\sqrt\Delta\)、\(DM=\Delta/4\) 的来源；解出 \(\Delta=4\) 后，再同时显示两个可行正方形状态。
- 第（Ⅲ）问先用代表性的 \(AD=L\) 状态讲菱形和平行四边形结构，不提前显示 \(AD=2\) 或最终曲线。
- 最短路径步骤使用局部控制拖动 \(E\)，并让 \(F\) 按 \(\overrightarrow{EF}=\overrightarrow{AM}\) 联动。
- 最后一步才显示最终抛物线 \(y=-\frac9{20}(x+1)(x-3)\) 和 \(F(\frac73,1)\)。

## Step 设计

### i1s1：配方求顶点

- 显示第（Ⅰ）问抛物线 \(y=-x^2+2x+3\)。
- 标出 \(A(-1,0)\)、\(B(3,0)\)、对称轴 \(x=1\)、顶点 \(P(1,4)\)。
- 不显示第（Ⅱ）、第（Ⅲ）问中的正方形、菱形或动点。

### q2s1：写出 DM 与 AB

- 显示代表性抛物线 \(y=-x^2-x+2\)，只用于承载当前代数状态。
- 标出 \(D(\frac b2,0)\)、\(P=M\)。
- 用线段标签显示 \(DM=\Delta/4\)、\(AB=\sqrt\Delta\)。
- 不画正方形，避免在尚未求出 \(\Delta=4\) 前显示一个假的正方形。

### q2s2：对角线相等求 b

- 显示两个求出的正方形状态：
  - \(b=4-2\sqrt5\)；
  - \(b=4+2\sqrt5\)。
- 每个状态都显示抛物线、对称轴、正方形 \(AMBN\)、两条对角线 \(AB\)、\(MN\)。
- 标出 \(AB=MN=2\)，并在顶点附近标出对应的 \(b\) 值。

### q3s1：构造平行四边形转化双动点为单动点

- 使用代表性图形，显示菱形 \(AMBN\) 与平行四边形 \(AEFM\)。
- 沿 \(BN\) 延长到 \(N'\)，使 \(NN'=MA\)；由菱形得 \(BN\parallel AM\)。
- 显示原来的 \(NF\) 与平移后的 \(EN'\)，标出 \(EN'=NF\)。
- 本步只讲 \(NE+NF=NE+EN'\)，不提前标出 \(N'\) 坐标。

### q3s2：将军饮马求最短

- 添加局部控制：拖动 \(E\) 在 \(AD\) 上运动，同时 \(F=E+\overrightarrow{AM}\)。
- 显示原来的 \(NE\)、\(NF\)，以及转化后的 \(ME\)、\(EN'\)。
- 标出 \(ME=NE\)、\(EN'=NF\)，说明 \(NE+NF=ME+EN'\)。
- 用浅色填充 \(\triangle MEN'\)，强调当 \(M,E,N'\) 共线时折线最短。
- 本步只放将军饮马关系，不放坐标计算。

### q3s3：代入路径最小值求E和F

- 设 \(M\) 的横坐标为 \(m\)，由 \(MN=2\) 得 \(M(m,1)\)、\(N(m,-1)\)。
- 由 \(A(-1,0)\)、\(AN'\parallel MN\) 且 \(AN'=MN\) 得 \(N'(-1,-2)\)。
- 由 \(MN'=\sqrt{13}\) 求出 \(m=1\)，切换到最终几何状态。
- 显示 \(M(1,1)\)、\(N'(-1,-2)\)、\(E(\frac13,0)\)、\(F(\frac73,1)\)。
- 画出 \(M,E,N'\) 共线，只标出核心长度 \(MN'=\sqrt{13}\)。
- 用直线 \(MN'\)：\(y=\frac32x-\frac12\)，令 \(y=0\) 得到 \(E(\frac13,0)\)。
- 用平行四边形平移关系标出 \(F(\frac73,1)\)，避免结论框遮挡 \(F\)。

### q3s4：点在抛物线上求 a

- 显示最终抛物线 \(y=a(x+1)(x-3)\) 在 \(a=-\frac9{20}\) 时的图像。
- 标出 \(A(-1,0)\)、\(B(3,0)\)、\(F(\frac73,1)\)。
- 保留平行四边形 \(AEFM\)，说明 \(F\) 的坐标来源。
- 推导区完成 \(1=a\cdot\frac{10}{3}\cdot(-\frac23)\)，图中不重复放公式卡。

## JSON 对齐

- `geometry-spec.curves`：
  - `parabolaPart1`：第（Ⅰ）问 \(y=-x^2+2x+3\)；
  - `parabolaSquareRep`：第（Ⅱ）问未求解代表状态；
  - `parabolaSquareLeft`、`parabolaSquareRight`：第（Ⅱ）问两个可行答案；
  - `parabolaFinal`：第（Ⅲ）问最终抛物线。
- `lesson-data.meta.classification.pattern`：`path-minimum`。
- `lesson-data.meta.classification.methods`：
  - `translation-path-transform`
  - `horse-drinking`
  - `known-root-factorization`
  - `coefficient-from-point-on-parabola`
