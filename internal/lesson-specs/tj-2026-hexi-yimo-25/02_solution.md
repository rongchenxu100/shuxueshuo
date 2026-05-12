# （Ⅰ）求顶点 P

当 \(a=1，b=2，c=3\) 时，

\[
y=x^2-2x+3=(x-1)^2+2.
\]

∴ 顶点 \(P(1,2)\)。

# （Ⅱ）求点 D

当 \(a=2\) 时，抛物线为

\[
y=2x^2-bx+c.
\]

∵ \(A(-1,0)\) 在抛物线上，

\[
0=2+b+c.
\]

∴ \(c=-b-2\)。

∴ \(C(0,-b-2)\)。

作 \(DH\perp x\) 轴，垂足为 \(H\)。

∵ \(C(0,-b-2)\)，

\[
AO=1,\quad OC=b+2.
\]

∵ \(\angle CAD=90^\circ\)，\(AC=AD\)，

∴ 可由直角三角形全等得到

\[
Rt\triangle AOC\cong Rt\triangle DHA.
\]

∴

\[
AH=OC=b+2,\quad DH=AO=1.
\]

∴

\[
H(b+1,0),\quad D(b+1,1).
\]

将 \(D(b+1,1)\) 代入抛物线：

\[
1=2(b+1)^2-b(b+1)-b-2=b^2+2b.
\]

∴ \(b^2+2b-1=0\)。

∵ \(b>0\)，

\[
b=\sqrt2-1.
\]

∴

\[
D(b+1,1)=(\sqrt2,1).
\]

∴ \(D(\sqrt2,1)\)。

# （Ⅲ）求 b

当 \(a=1\) 时，抛物线为

\[
y=x^2-bx+c.
\]

∵ \(A(-1,0)\) 在抛物线上，

\[
0=1+b+c.
\]

∴ \(c=-b-1\)。

∵ \(M\left(b+\frac12,y_M\right)\) 在抛物线上，

\[
y_M=\left(b+\frac12\right)^2-b\left(b+\frac12\right)-b-1
=-\frac{2b+3}{4}.
\]

设

\[
K\left(b+\frac12,0\right),
\quad h=KM=\frac{2b+3}{4}.
\]

点 \(N(n,0)\) 在 \(x\) 轴正半轴上。

若 \(0<b<\frac12\)，取 \(N=K\) 时已有

\[
\sqrt2MN+AN=\sqrt2h+b+\frac32<\sqrt2+2<\frac{21}{4},
\]

不可能使最小值为 \(\frac{21}{4}\)。因此只需考虑 \(b\ge\frac12\) 的情形，此时取等号位置会落在 \(x\) 轴正半轴上。

## 构造等腰直角三角形，转化 \(AN\)

在 \(x\) 轴上方作点 \(Q\)，使 \(\triangle AQN\) 是等腰直角三角形，且

\[
AQ=QN,\quad \angle AQN=90^\circ.
\]

于是

\[
AN=\sqrt2\,QN.
\]

所以

\[
\sqrt2MN+AN=\sqrt2(MN+QN).
\]

当 \(N\) 在 \(x\) 轴正半轴上运动时，点 \(Q\) 在过 \(A\)，且经过 \(y\) 轴正半轴点 \((0,1)\) 的 \(45^\circ\) 固定射线上运动。

\[
MN+QN\ge MQ.
\]

当 \(M,N,Q\) 三点共线时取等号。

又因为 \(Q\) 在固定射线 \(AQ\) 上，最短时 \(MQ\perp AQ\)。

过 \(M\) 作 \(MH\perp x\) 轴。

∵ \(AQ\) 与 \(x\) 轴成 \(45^\circ\)，且最短时 \(MQ\perp AQ\)，

∴ \(\triangle MHN\) 是等腰直角三角形。

由

\[
M\left(b+\frac12,-\frac{2b+3}{4}\right)
\]

得

\[
MH=HN=\frac{2b+3}{4}.
\]

所以

\[
MN=\sqrt2\cdot\frac{2b+3}{4}.
\]

又因为

\[
AN=AH-HN=\frac{2b+3}{4},
\quad AN=\sqrt2\,QN,
\]

所以

\[
QN=\frac{2b+3}{4\sqrt2}
=\sqrt2\cdot\frac{2b+3}{8}.
\]

于是

\[
\min(MN+QN)=\frac{3\sqrt2(2b+3)}{8}.
\]

因此原式的最小值为

\[
\sqrt2\cdot \frac{3\sqrt2(2b+3)}{8}
=\frac{6b+9}{4}.
\]

由题意

\[
\frac{6b+9}{4}=\frac{21}{4}.
\]

∴ \(6b+9=21\)，

∴ \(b=2\)。

此时最短位置 \(n=\frac{2b-1}{4}=\frac34>0\)，符合 \(N\) 在 \(x\) 轴正半轴上。
