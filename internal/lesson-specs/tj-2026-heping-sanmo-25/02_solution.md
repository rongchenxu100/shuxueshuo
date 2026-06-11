# 解题过程

## 第（Ⅰ）问

### Step 1：代入系数化简函数，再求顶点

- 目标：先把 \(a=-2,\ c=6\) 代入原函数，再配方求顶点。
- 推导：
  - ∵ \(a=-2,\ c=6\)
  - ∴ \(y=-2x^2+8x+6\)
  - ∴ \(y=-2(x^2-4x)+6\)
  - ∴ \(y=-2(x-2)^2+14\)
  - ∴ \(D(2,14)\)
- 当前结论：
  - \(D(2,14)\)

## 第（Ⅱ）①问

### Step 1：用 30° 求直线 \(A'C'\)

- 目标：先由 \(A'(8,0)\)、\(C'\) 在 \(y\) 轴和 \(30^\circ\) 角确定辅助直线。
- 推导：
  - ∵ \(A'(8,0)\)，\(C'\) 在 \(y\) 轴正半轴
  - ∵ \(\angle OA'C'=30^\circ\)
  - ∴ 在 \(Rt\triangle OA'C'\) 中，\(\tan30^\circ=\dfrac{OC'}{OA'}\)
  - ∴ \(OC'=8\cdot\dfrac{\sqrt3}{3}=\dfrac{8\sqrt3}{3}\)
  - ∴ \(C'(0,\dfrac{8\sqrt3}{3})\)
  - ∴ \(A'C':\ y=\dfrac{\sqrt3}{3}(8-x)\)
- 当前结论：
  - \(C'(0,\dfrac{8\sqrt3}{3})\)
  - \(A'C':\ y=\dfrac{\sqrt3}{3}(8-x)\)

### Step 2：联立求 \(Q\)，由面积和等长确定 \(M,D\)

- 目标：把 \(DQ=MQ\) 与 \(\triangle MDQ\) 面积转化成可读长度。
- 推导：
  - ∵ 抛物线 \(y=ax^2-4ax+c\) 的对称轴为 \(x=2\)
  - ∵ \(Q\) 是 \(A'C'\) 与对称轴的交点
  - ∴ 将 \(x=2\) 代入 \(A'C':y=\dfrac{\sqrt3}{3}(8-x)\)
  - ∴ \(Q(2,2\sqrt3)\)
  - 过点 \(M\) 作 \(MG\perp x=2\)，垂足为 \(G\)
  - ∵ \(A'C'\) 与 \(x\) 轴夹角为 \(30^\circ\)
  - ∴ \(MQ=\dfrac{2MG}{\sqrt3}\)
  - ∵ \(DQ=MQ\)
  - ∴ \(DQ=\dfrac{2MG}{\sqrt3}\)
  - ∵ \(S_{\triangle MDQ}=\dfrac12\cdot DQ\cdot MG=3\sqrt3\)
  - ∴ \(\dfrac{MG^2}{\sqrt3}=3\sqrt3\)
  - ∴ \(MG=3\)
  - ∴ \(M(5,\sqrt3)\)，且 \(DQ=2\sqrt3\)
  - ∵ \(Q(2,2\sqrt3)\)，且 \(D,Q\) 都在 \(x=2\) 上
  - ∴ \(D(2,0)\) 或 \(D(2,4\sqrt3)\)
  - ∵ 若 \(D(2,0)\)，开口向下时抛物线上的点纵坐标不大于 \(0\)，与 \(M_y=\sqrt3\) 矛盾
  - ∴ \(D(2,4\sqrt3)\)
- 当前结论：
  - \(Q(2,2\sqrt3)\)
  - \(M(5,\sqrt3)\)
  - \(D(2,4\sqrt3)\)

### Step 3：点 \(M\) 在抛物线上求解析式

- 目标：由顶点和点 \(M\) 求 \(a,c\)。
- 推导：
  - ∵ 顶点 \(D(2,c-4a)=(2,4\sqrt3)\)
  - ∴ 抛物线可写为 \(y=a(x-2)^2+4\sqrt3\)
  - ∵ \(M(5,\sqrt3)\) 在抛物线上
  - ∴ \(\sqrt3=9a+4\sqrt3\)
  - ∴ \(a=-\dfrac{\sqrt3}{3}\)
  - ∵ \(c-4a=4\sqrt3\)
  - ∴ \(c=4\sqrt3+4a=\dfrac{8\sqrt3}{3}\)
  - ∴ \(y=-\dfrac{\sqrt3}{3}x^2+\dfrac{4\sqrt3}{3}x+\dfrac{8\sqrt3}{3}\)
- 当前结论：
  - \(a=-\dfrac{\sqrt3}{3},\ c=\dfrac{8\sqrt3}{3}\)
  - \(y=-\dfrac{\sqrt3}{3}x^2+\dfrac{4\sqrt3}{3}x+\dfrac{8\sqrt3}{3}\)

## 第（Ⅱ）②问

### Step 1：设点 \(A\)，读出 \(AA'\) 并求点 \(P\)

- 目标：先保留一个横坐标参数，读出后面最短路要用的水平距离，并确定等边三角形顶点 \(P\)。
- 推导：
  - 设 \(A(r,0)\)，其中 \(r>0\)
  - ∵ 直线 \(A'C'\) 向下平移与直线 \(AC\) 重合
  - ∴ \(AC\parallel A'C'\)，且 \(\angle OAC=30^\circ\)
  - ∵ \(A'(8,0)\)，且 \(A,A'\) 都在 \(x\) 轴上
  - ∴ \(AA'=8-r\)
  - ∵ \(\triangle OAP\) 是等边三角形，点 \(P\) 在第一象限
  - ∴ \(P\left(\dfrac r2,\dfrac{\sqrt3 r}{2}\right)\)
- 当前结论：
  - \(A(r,0)\)
  - \(AA'=8-r\)
  - \(P\left(\dfrac r2,\dfrac{\sqrt3 r}{2}\right)\)

### Step 2：构造平行四边形和直角三角形，将两动点问题转化为单动点问题

- 目标：先把目标式中的两段变成同一条折线。
- 推导：
  - ∵ \(AC\parallel A'C'\)，且 \(EF\perp A'C'\)
  - ∴ \(EF\) 是两条平行线间的距离，是固定值，与动点 \(E,F\) 的位置无关
  - ∵ \(A'A=8-r\)，两条平行线与 \(x\) 轴夹角为 \(30^\circ\)
  - ∴ \(EF=(8-r)\sin30^\circ=4-\dfrac r2\)
  - 构造平行四边形 \(PEFP_1\)：将点 \(P\) 沿 \(EF\) 方向平移到 \(P_1\)，使 \(PP_1\parallel EF,\ PP_1=EF\)
  - ∴ 四边形 \(PEFP_1\) 是平行四边形
  - ∴ \(PE=P_1F\)
  - 构造直角三角形 \(A'NF\)：在 \(A'F\) 的同侧作 \(30^\circ\!-\!60^\circ\!-\!90^\circ\) 三角形，使 \(A'N=\dfrac12A'F\)
  - ∴ \(FN=\dfrac{\sqrt3}{2}A'F\)
  - ∴ \(PE+EF+\dfrac{\sqrt3}{2}FA'=P_1F+FN+EF\)
  - ∴ 原来的 \(P,E\) 两个动点，转化为只研究动点 \(F\) 的折线 \(P_1F+FN\)
- 当前结论：
  - \(EF=4-\dfrac r2\)
  - \(PE=P_1F\)
  - \(FN=\dfrac{\sqrt3}{2}FA'\)

### Step 3：将军饮马求最小值表达式

- 目标：把 \(P_1F+FN\) 拉直，再用点到直线的垂线段最短。
- 推导：
  - ∵ \(P_1F+FN\ge P_1N\)
  - ∴ 当 \(P_1,F,N\) 三点共线时，折线最短
  - ∵ \(N\) 在过 \(A'\) 的固定射线上运动
  - ∴ \(P_1N\) 最短时，\(P_1N\perp A'N\)
  - ∵ \(P\left(\dfrac r2,\dfrac{\sqrt3 r}{2}\right)\)
  - 由上一步平行四边形的平移关系，可得 \(P_1(2+\dfrac r4,\ 2\sqrt3+\dfrac{\sqrt3 r}{4})\)
  - 过 \(P_1\) 作 \(P_1H\perp A'N\)，垂足为 \(H\)，并设 \(P_1H\) 与 \(x\) 轴交于 \(J\)，\(P_1K\perp x\) 轴于 \(K\)
  - ∵ \(P_1H\) 与 \(x\) 轴夹角为 \(60^\circ\)，且 \(P_1K=2\sqrt3+\dfrac{\sqrt3 r}{4}\)
  - ∴ \(P_1J=4+\dfrac r2\)
  - ∵ \(KJ=2+\dfrac r4\)，\(K\) 的横坐标为 \(2+\dfrac r4\)
  - ∴ \(J(4+\dfrac r2,0)\)，\(A'J=8-(4+\dfrac r2)=4-\dfrac r2\)
  - ∵ \(A'H\) 与 \(x\) 轴夹角为 \(30^\circ\)，且 \(P_1H\perp A'H\)
  - ∴ \(Rt\triangle A'JH\) 中，\(JH=\dfrac12A'J=2-\dfrac r4\)
  - ∴ \(P_1H=P_1J+JH=6+\dfrac r4\)
  - ∴ 原式最小值为
    \[
    EF+P_1H=\left(4-\dfrac r2\right)+\left(6+\dfrac r4\right)=10-\dfrac r4
    \]
- 当前结论：
  - \(PE+EF+\dfrac{\sqrt3}{2}FA'\) 的最小值为 \(10-\dfrac r4\)

### Step 4：由最小值反求 \(a\)

- 目标：用给定最小值确定 \(r\)，再把 \(A\)、\(C\) 代回抛物线求 \(a\)。
- 推导：
  - ∵ 题给最小值为 \(\dfrac{17}{2}\)
  - ∴ \(10-\dfrac r4=\dfrac{17}{2}\)
  - ∴ \(r=6\)
  - ∴ \(A(6,0)\)
  - ∵ \(AC\parallel A'C'\)，\(\angle OAC=30^\circ\)
  - ∴ 在 \(Rt\triangle AOC\) 中，\(\tan30^\circ=\dfrac{OC}{OA}=\dfrac c6\)
  - ∴ \(c=2\sqrt3\)
  - ∵ \(A(6,0)\) 在 \(y=ax^2-4ax+c\) 上
  - ∴ \(0=36a-24a+2\sqrt3\)
  - ∴ \(a=-\dfrac{\sqrt3}{6}\)
- 当前结论：
  - \(a=-\dfrac{\sqrt3}{6}\)
