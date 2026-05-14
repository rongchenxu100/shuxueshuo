# 解题过程

## 第（Ⅰ）问：化简函数表达式

∵ 抛物线经过 \(A(-1,0)\)，  
∴

\[
a-b+c=0.
\]

∵ \(b=2,\ c=4\)，  
∴

\[
a-2+4=0.
\]

∴

\[
a=-2.
\]

∴

\[
y=-2x^2+2x+4.
\]

顶点横坐标

\[
x_P=-\frac{b}{2a}=-\frac{2}{2(-2)}=\frac12.
\]

代入得

\[
y_P=-2\cdot\left(\frac12\right)^2+2\cdot\frac12+4=\frac92.
\]

∴

\[
P\left(\frac12,\frac92\right).
\]

## 第（Ⅱ）①问：代入 c 并化简函数表达式

∵ \(A(-1,0)\) 是抛物线与 \(x\) 轴的交点，  
∴ \(x=-1\) 是方程 \(ax^2+bx+c=0\) 的一个根。

又 \(a-b+c=0\)，即 \(b=a+c\)，所以

\[
y=ax^2+(a+c)x+c.
\]

∵ \(c=\frac43\)，  
∴

\[
y=ax^2+\left(a+\frac43\right)x+\frac43.
\]

直接因式分解：

\[
y=(x+1)\left(ax+\frac43\right).
\]

∴ 另一个 \(x\) 轴交点为

\[
B\left(-\frac{4}{3a},0\right).
\]

\[
C\left(0,\frac43\right),\quad AO=1,\quad CO=\frac43,\quad AC=\frac53.
\]

## 第（Ⅱ）①问：构造等腰三角形求解

设 \(\angle ABC=\theta\)。  
∵ \(\angle CAB=2\angle ABC\)，  
∴ \(\angle CAB=2\theta\)。

作点 \(A'\) 为 \(A\) 关于 \(y\) 轴的对称点，连接 \(CA'\)。  
则

\[
A'(1,0),\quad CA'=CA=\frac53.
\]

又 \(CA=CA'\)，所以 \(\triangle ACA'\) 是等腰三角形。  
结合 \(\angle CAB=2\angle ABC\)，可得

\[
\angle CA'A=\angle CAB=2\angle ABC.
\]

由于 \(A'B\) 是 \(A'A\) 的反向延长线，  
∴

\[
\angle CA'B=180^\circ-2\angle ABC.
\]

在 \(\triangle CA'B\) 中，

\[
\angle A'CB=\angle ABC.
\]

∴ \(\triangle CA'B\) 是等腰三角形，

\[
A'C=A'B.
\]

∴

\[
A'B=\frac53.
\]

∴

\[
BO=OA'+A'B=1+\frac53=\frac83.
\]

即

\[
B\left(\frac83,0\right).
\]

由化简函数表达式得到

\[
B\left(-\frac{4}{3a},0\right).
\]

∴

\[
-\frac{4/3}{a}=\frac83.
\]

∴

\[
a=-\frac12.
\]

## 第（Ⅱ）②问：由 BO=4CO 化简函数表达式

由第（Ⅱ）①的因式分解思路，

\[
y=(x+1)(ax+c).
\]

另一个交点仍为

\[
B\left(-\frac ca,0\right).
\]

∵ \(BO=4CO\)，  
∴

\[
-\frac ca=4c.
\]

∵ \(c\neq 0\)，  
∴

\[
a=-\frac14.
\]

又 \(b=a+c\)，  
∴

\[
c=b+\frac14.
\]

∴

\[
y=-\frac14x^2+bx+b+\frac14,
\]

\[
B(4b+1,0),\quad C\left(0,b+\frac14\right).
\]

## 第（Ⅱ）②问：由等角确定 M 所在直线

作直线 \(BM\) 交 \(y\) 轴于点 \(C'\)。

∵ \(\angle ABM=\angle ABC\)，且 \(A,B\) 在 \(x\) 轴上，  
∴ \(\triangle BOC'\) 与 \(\triangle BOC\) 关于 \(x\) 轴成镜像位置，  
∴

\[
C'O=CO=b+\frac14.
\]

∴

\[
C'\left(0,-b-\frac14\right).
\]

又 \(B(4b+1,0)\)，由 \(B\) 与 \(C'\) 两点可得

\[
BM:\ y=\frac14(x-4b-1).
\]

与抛物线

\[
y=-\frac14x^2+bx+b+\frac14
\]

联立，整理得

\[
x^2+(1-4b)x-8\left(b+\frac14\right)=0.
\]

这个方程的一个根是 \(x_B=4b+1\)，  
∴ 另一个根为

\[
x_M=-2.
\]

代回 \(BM\)，得

\[
y_M=-b-\frac34.
\]

∴

\[
M\left(-2,-b-\frac34\right).
\]

## 第（Ⅱ）②问：用铅垂面积求 b 和 M

由上一步可知 \(C'\) 在 \(BM\) 上，且

\[
C'O=CO=b+\frac14.
\]

所以

\[
CC'=2b+\frac12.
\]

用竖直线 \(CC'\) 把 \(\triangle MBC\) 分成左右两个三角形。  
点 \(B\) 到 \(y\) 轴的水平距离为 \(4b+1\)，点 \(M\) 到 \(y\) 轴的水平距离为 \(2\)，因此

\[
S_{\triangle MBC}
=\frac12\cdot CC'\cdot(4b+1)+\frac12\cdot CC'\cdot2.
\]

即

\[
S_{\triangle MBC}
=\frac12\left(2b+\frac12\right)(4b+3)
=4b^2+4b+\frac34.
\]

∵ \(S_{\triangle MBC}=8b+6\)，  
∴

\[
4b^2+4b+\frac34=8b+6.
\]

∴

\[
16b^2-16b-21=0.
\]

∴

\[
b=\frac74\quad \text{或}\quad b=-\frac34.
\]

∵ \(b>0\)，  
∴

\[
b=\frac74.
\]

代回 \(M\left(-2,-b-\frac34\right)\)，得

\[
M\left(-2,-\frac52\right).
\]
