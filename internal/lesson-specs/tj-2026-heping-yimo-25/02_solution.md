# 解题过程

## （I）① 求抛物线解析式

由 \(A(-1,0)\) 在抛物线上：

\[
a-b-3=0
\]

即

\[
b=a-3
\]

因为 \(D=(2,-3)\)，且 \(D\) 在抛物线上：

\[
4a+2b-3=-3
\]

\[
4a+2b=0
\]

\[
b=-2a
\]

联立 \(b=a-3\) 与 \(b=-2a\)，得

\[
a=1,\quad b=-2
\]

所以抛物线解析式为

\[
\boxed{y=x^2-2x-3}
\]

## （I）② 求点 E 的坐标

由第（I）①得 \(B=(3,0)\)，\(C=(0,-3)\)。

在直角三角形 \(ACO\) 中：

\[
\tan \angle ACO=\frac{AO}{CO}=\frac13
\]

设直线 \(BE\) 与 \(OC\) 交于点 \(F\)。

因为 \(B(3,0)\)，\(C(0,-3)\)，所以 \(\triangle BOC\) 是等腰直角三角形：

\[
\angle OBC=45^\circ
\]

又因为 \(F\) 在 \(BE\) 上，所以

\[
\angle CBF=\angle CBE
\]

已知

\[
\angle CBE+\angle ACO=45^\circ
\]

因此

\[
\angle OBF=\angle ACO
\]

在直角三角形 \(BOF\) 中：

\[
\tan\angle OBF=\frac{OF}{OB}
\]

又 \(\tan\angle ACO=\frac13\)，所以

\[
\frac{OF}{OB}=\frac13
\]

而 \(OB=3\)，故

\[
OF=1
\]

于是

\[
F=(0,-1)
\]

直线 \(BF\) 过 \(B(3,0)\)、\(F(0,-1)\)，所以

\[
BF: y=\frac13x-1
\]

联立直线 \(BF\) 与抛物线 \(y=x^2-2x-3\)：

\[
x^2-2x-3=\frac13x-1
\]

\[
3x^2-7x-6=0
\]

\[
(x-3)(3x+2)=0
\]

一个交点是 \(B(3,0)\)，另一个交点就是 \(E\)。又 \(-1<m<0\)，所以

\[
m=-\frac23
\]

代入 \(BF: y=\frac13x-1\)，得

\[
y=-\frac29-1=-\frac{11}{9}
\]

所以

\[
\boxed{E\left(-\frac23,-\frac{11}{9}\right)}
\]

## （II）由最小值求 a

由 \(A(-1,0)\) 在抛物线上：

\[
a-b-3=0
\]

\[
b=a-3
\]

设另一个交点 \(B=(r,0)\)。两根为 \(-1,r\)，根的乘积为

\[
-r=\frac{-3}{a}
\]

所以

\[
r=\frac3a
\]

即

\[
B\left(\frac3a,0\right)
\]

在射线 \(CD\) 上取点 \(G\)，使

\[
CG=CB
\]

因为 \(M\) 在线段 \(BC\) 上，\(N\) 在射线 \(CD\) 上，所以

\[
\angle BCN=\angle GCM
\]

又因为

\[
CN=CM,\quad CB=CG
\]

所以

\[
\triangle CBN\cong\triangle GCM
\]

于是

\[
BN=MG
\]

原式转化为

\[
OM+BN=OM+MG
\]

这是单动点 \(M\) 在线段 \(BC\) 上的最短路径问题。因为 \(O\) 与 \(G\) 在直线 \(BC\) 的两侧，所以

\[
OM+MG\ge OG
\]

当 \(O、M、G\) 三点共线时取到最小值。

因为

\[
CB=\frac{3\sqrt{1+a^2}}{a}
\]

且 \(CG=CB\)，所以

\[
CG=\frac{3\sqrt{1+a^2}}{a}
\]

在直角三角形 \(OCG\) 中：

\[
OG^2=OC^2+CG^2
\]

因此

\[
\min(OM+BN)^2=9+\left(\frac{3\sqrt{1+a^2}}{a}\right)^2=18+\frac9{a^2}
\]

已知最小值为 \(\sqrt{34}\)，故

\[
18+\frac9{a^2}=34
\]

\[
\frac9{a^2}=16
\]

又 \(a>0\)，所以

\[
\boxed{a=\frac34}
\]
