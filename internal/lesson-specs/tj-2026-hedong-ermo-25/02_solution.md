# 第（Ⅰ）①问：求顶点 P

当 \(a=-1,\ b=4,\ c=-3\) 时，

\[
y=-x^2+4x-3=-(x-2)^2+1.
\]

所以顶点

\[
P(2,1).
\]

# 第（Ⅰ）②问：求点 G

由 \(a=-1,\ A(-2,0),\ C(0,2)\)，可得

\[
y=-x^2+bx+2.
\]

因为 \(A(-2,0)\) 在抛物线上，

\[
0=-4-2b+2.
\]

所以

\[
b=-1.
\]

于是

\[
y=-x^2-x+2=-(x+2)(x-1).
\]

所以另一个交点

\[
B(1,0).
\]

又因为 \(AC\) 的方向是从 \((-2,0)\) 到 \((0,2)\)，横、纵都增加 \(2\)，所以直线 \(AC\) 与 \(x\) 轴成 \(45^\circ\)。

\[
\angle CAD=90^\circ
\]

说明 \(AD\) 与 \(AC\) 垂直，因此 \(AD\) 的方向为向右下的 \(45^\circ\)，直线 \(AD\) 为

\[
y=-x-2.
\]

点 \(D\) 在抛物线上，也在直线 \(AD\) 上：

\[
-x^2-x+2=-x-2.
\]

所以

\[
x^2=4.
\]

其中 \(x=-2\) 对应点 \(A\)，另一点为

\[
D(2,-4).
\]

因为 \(\triangle BCG\) 的周长为

\[
BC+BG+CG.
\]

其中 \(BC\) 是定长，所以只需使

\[
BG+CG
\]

最小。

把点 \(C\) 关于直线 \(AD:x+y+2=0\) 对称到点 \(C'\)。

因为 \(C(0,2)\)，对称后

\[
C'(-4,-2).
\]

对于 \(G\in AD\)，有

\[
CG=C'G.
\]

所以

\[
BG+CG=BG+C'G\ge BC'.
\]

当 \(B,G,C'\) 三点共线时取等号。

直线 \(BC'\) 过 \(B(1,0)\)、\(C'(-4,-2)\)，可写成

\[
y=\frac25(x-1).
\]

与 \(AD:y=-x-2\) 联立：

\[
\frac25(x-1)=-x-2.
\]

解得

\[
x=-\frac87,\quad y=-\frac67.
\]

因此

\[
G\left(-\frac87,-\frac67\right).
\]

# 第（Ⅱ）问：求 a

设

\[
OB=OC=m\quad (m>0).
\]

点 \(B\) 在 \(x\) 轴正半轴，所以 \(B(m,0)\)。由于 \(C\) 在 \(y\) 轴上且 \(OC=m\)，需要分两种情况。

## 情况一：\(C\) 在 \(y\) 轴负半轴

此时

\[
B(m,0),\quad C(0,-m).
\]

于是

\[
c=-m.
\]

设另一个 \(x\) 轴交点为 \(A\)，则由 \(C(0,-m)\)、\(B(m,0)\) 可写

\[
y=a(x-m)\left(x+\frac1a\right).
\]

这是因为常数项为

\[
a\cdot(-m)\cdot\frac1a=-m.
\]

展开得

\[
y=ax^2+(1-am)x-m.
\]

由 \(BC=4BE\)，可知

\[
BE=\frac14BC.
\]

点 \(E\) 从 \(B\) 向 \(C\) 走了 \(\frac14\) 个 \(BC\)，所以

\[
E\left(\frac{3m}{4},-\frac m4\right).
\]

因为 \(OE\perp OF\)，且 \(OE=OF\)，所以以 \(OE,OF\) 为直角边的三角形是等腰直角三角形。

结合点 \(F\) 落在抛物线上，可取

\[
F\left(-\frac m4,-\frac{3m}{4}\right).
\]

将 \(F\) 代入

\[
y=ax^2+(1-am)x-m
\]

得

\[
-\frac{3m}{4}
=a\cdot\frac{m^2}{16}+(1-am)\left(-\frac m4\right)-m.
\]

化简：

\[
-\frac{3m}{4}=\frac{5am^2}{16}-\frac{5m}{4}.
\]

因为 \(m>0\)，所以

\[
5am=8.
\]

接着看点 \(H\)。

\[
\angle OHB=90^\circ
\]

说明点 \(H\) 在以 \(OB\) 为直径的圆上。这个圆的圆心为

\[
K\left(\frac m2,0\right),
\]

半径为

\[
\frac m2.
\]

点 \(H\) 在第四象限，所以下半圆弧是它的运动轨迹。

要求 \(HF\) 的最小值，就是从定点 \(F\) 到这段圆弧的最短距离。

因为

\[
F\left(-\frac m4,-\frac{3m}{4}\right),\quad K\left(\frac m2,0\right),
\]

所以

\[
FK=\sqrt{\left(\frac{3m}{4}\right)^2+\left(\frac{3m}{4}\right)^2}
=\frac{3\sqrt2}{4}m.
\]

又圆的半径为 \(\frac m2\)，因此

\[
HF_{\min}=FK-\frac m2
=\left(\frac{3\sqrt2}{4}-\frac12\right)m
=\frac{3\sqrt2-2}{4}m.
\]

题给最小值为 \(3\sqrt2-2\)，所以

\[
\frac{3\sqrt2-2}{4}m=3\sqrt2-2.
\]

因此

\[
m=4.
\]

由

\[
5am=8
\]

得

\[
a=\frac{8}{5m}=\frac25.
\]

所以

\[
a=\frac25.
\]

## 情况二：\(C\) 在 \(y\) 轴上半轴

此时

\[
C(0,m),\quad c=m.
\]

由 \(B(m,0)\) 和常数项 \(m\)，可写

\[
y=a(x-m)\left(x-\frac1a\right)
=ax^2-(am+1)x+m.
\]

因为 \(BC=4BE\)，点 \(E\) 从 \(B\) 向 \(C\) 走了 \(\frac14\) 个 \(BC\)，所以

\[
E\left(\frac{3m}{4},\frac m4\right).
\]

又因为 \(OE\perp OF\)，且 \(OE=OF\)，并且 \(H\) 在第四象限时对应的 \(F\) 取在第四象限，

\[
F\left(\frac m4,-\frac{3m}{4}\right).
\]

将 \(F\) 代入

\[
y=ax^2-(am+1)x+m
\]

得

\[
-\frac{3m}{4}
=a\cdot\frac{m^2}{16}-(am+1)\frac m4+m.
\]

化简得

\[
am=8.
\]

同样，点 \(H\) 在以 \(OB\) 为直径的圆上，圆心

\[
K\left(\frac m2,0\right),
\]

半径为 \(\frac m2\)。

此时

\[
F\left(\frac m4,-\frac{3m}{4}\right),\quad K\left(\frac m2,0\right),
\]

所以

\[
FK=\sqrt{\left(\frac m4\right)^2+\left(\frac{3m}{4}\right)^2}
=\frac{\sqrt{10}}4m.
\]

因此

\[
HF_{\min}=FK-\frac m2
=\frac{\sqrt{10}-2}{4}m.
\]

题给最小值为 \(3\sqrt2-2\)，所以

\[
\frac{\sqrt{10}-2}{4}m=3\sqrt2-2.
\]

于是

\[
m=\frac{4(3\sqrt2-2)}{\sqrt{10}-2}.
\]

由 \(am=8\)，得

\[
a=\frac8m
=\frac{2(\sqrt{10}-2)}{3\sqrt2-2}.
\]

综上，

\[
a=\frac25
\quad\text{或}\quad
a=\frac{2(\sqrt{10}-2)}{3\sqrt2-2}.
\]
