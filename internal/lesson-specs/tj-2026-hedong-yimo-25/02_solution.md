# 第（Ⅰ）问：求顶点 P

当 \(a=1,\ b=-2,\ c=-3\) 时，

\[
y=x^2-2x-3=(x-1)^2-4.
\]

所以顶点

\[
P(1,-4).
\]

# 第（Ⅱ）①问：求点 D

因为 \(A(-1,0)\) 在抛物线上，所以

\[
a-b+c=0.
\]

当 \(a=2\) 时，

\[
b=c+2.
\]

因此抛物线可化为

\[
y=2x^2+(c+2)x+c=(x+1)(2x+c).
\]

所以另一个交点与 \(y\) 轴交点分别为

\[
B\left(-\frac c2,0\right),\quad C(0,c).
\]

过点 \(D\) 作 \(DQ\perp x\) 轴，垂足为 \(Q\)。

因为 \(B\left(-\frac c2,0\right)\)，\(C(0,c)\)，且 \(c<0\)，所以

\[
BO=-\frac c2,\quad CO=-c.
\]

又因为 \(\angle CBD=90^\circ\)，\(BC=BD\)，且 \(\angle COB=\angle DQB=90^\circ\)，所以

\[
\angle CBO=\angle BDQ.
\]

因此

\[
Rt\triangle CBO\cong Rt\triangle BDQ.
\]

于是

\[
BQ=CO=-c,\quad DQ=BO=-\frac c2.
\]

所以

\[
Q\left(\frac c2,0\right),\quad D\left(\frac c2,-\frac c2\right).
\]
\]

又因为 \(D\) 在抛物线 \(y=(x+1)(2x+c)\) 上，

\[
-\frac c2=\left(\frac c2+1\right)\left(2\cdot\frac c2+c\right)=c(c+2).
\]

由于 \(c\ne0\)，

\[
c=-\frac52.
\]

因此

\[
D\left(-\frac54,\frac54\right).
\]

# 第（Ⅱ）②问：求点 E

由 \(A(-1,0)\) 和 \(B(-c,0)\) 是抛物线与 \(x\) 轴交点，且 \(C(0,c)\)，可得

\[
y=a(x+1)(x+c).
\]

常数项为 \(c\)，所以

\[
ac=c.
\]

因为 \(E\in OC\)，且 \(B(-c,0)\) 是另一个交点，故 \(c\ne0\)，于是

\[
a=1,\quad b=c+1.
\]

又 \(b<0\)，所以 \(c<-1\)。

因为 \(B(-c,0)\)，\(C(0,c)\)，且 \(c<-1\)，所以

\[
OB=OC=-c.
\]

所以 \(\triangle BOC\) 是等腰直角三角形，直线 \(BA\) 与 \(BC\) 的夹角为 \(45^\circ\)。

设 \(E(0,y)\)，其中 \(c\le y\le0\)。直线 \(BE\) 与 \(BA\) 的夹角为 \(\angle ABE\)，则

\[
\tan\angle ABE=\frac{-y}{-c}.
\]

由 \(\angle ABE=2\angle CBE\)，且

\[
\angle ABE+\angle CBE=45^\circ,
\]

可得

\[
\angle ABE=30^\circ.
\]

于是

\[
\frac{-y}{-c}=\tan30^\circ=\frac1{\sqrt3}.
\]

所以

\[
y=\frac c{\sqrt3},\quad E\left(0,\frac c{\sqrt3}\right).
\]

接着求最短路。设抛物线对称轴 \(l\) 与 \(BE\) 交于 \(F\)。

抛物线

\[
y=x^2+(c+1)x+c
\]

的对称轴为

\[
x=-\frac{c+1}{2}.
\]

直线 \(BE\) 为

\[
y=\frac{x+c}{\sqrt3}.
\]

因此

\[
F\left(-\frac{c+1}{2},\frac{c-1}{2\sqrt3}\right).
\]

把点 \(A\) 关于直线 \(BE\) 对称到 \(A'\)，把点 \(F\) 关于 \(BA\)（即 \(x\) 轴）对称到 \(F'\)。

因为 \(BE\) 垂直平分 \(AA'\)，所以 \(BA=BA'\)。又因为 \(\angle ABE=30^\circ\)，所以

\[
\angle ABA'=60^\circ.
\]

因此 \(\triangle ABA'\) 是等边三角形，\(A'\) 在 \(AB\) 的垂直平分线上，也就是抛物线对称轴

\[
x=-\frac{c+1}{2}.
\]

又 \(AB=1-c\)，所以等边三角形的高为

\[
\frac{\sqrt3(1-c)}2.
\]

由于 \(A'\) 在 \(x\) 轴下方，所以它的纵坐标为

\[
-\frac{\sqrt3(1-c)}2=\frac{\sqrt3(c-1)}2.
\]

即

\[
A'\left(-\frac{c+1}{2},\frac{\sqrt3(c-1)}2\right).
\]

由

\[
F\left(-\frac{c+1}{2},\frac{c-1}{2\sqrt3}\right)
\]

关于 \(x\) 轴对称，得

\[
F'\left(-\frac{c+1}{2},-\frac{c-1}{2\sqrt3}\right).
\]
\]

对于任意 \(G\in BE,\ H\in BA\)，有

\[
AG+GH+FH=A'G+GH+F'H\ge A'F'.
\]

当 \(A',G,H,F'\) 共线时取等号。由于 \(A'\) 与 \(F'\) 的横坐标相同，

\[
A'F'=-\frac{\sqrt3(c-1)}2-\frac{c-1}{2\sqrt3}
=-\frac{2(c-1)}{\sqrt3}.
\]

已知最小值为 \(5\sqrt3\)，所以

\[
-\frac{2(c-1)}{\sqrt3}=5\sqrt3.
\]

解得

\[
c=-\frac{13}{2}.
\]

于是

\[
E\left(0,\frac c{\sqrt3}\right)
=\left(0,-\frac{13}{2\sqrt3}\right)
=\left(0,-\frac{13\sqrt3}{6}\right).
\]
