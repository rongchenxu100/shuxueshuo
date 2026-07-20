# 高中导数题型与方法

## 题型标签

| pattern ID | 名称 | 典型特征 |
|---|---|---|
| `tangent-line` | 切线方程 | 已知切点或切线条件，求斜率、切线或参数 |
| `common-tangent` | 公切线 | 一条直线同时与两个函数图像相切 |
| `monotonicity-extrema` | 单调性与极值 | 由导函数符号求单调区间、局部或全局极值 |
| `parameter-range-by-derivative` | 导数求参数范围 | 消元得到单变量参数函数，再用导数求值域 |

## 解题方法

### method: derivative-rule-application

**名称**：按求导法则计算导函数

先声明定义域，再逐项使用和、积、商、复合函数求导法则。复杂导函数应在进入符号分析前化简或因式分解。

### method: tangent-line-at-point

**名称**：点斜式写切线

在 `x=t` 处依次求 `(t,f(t))`、斜率 `f'(t)`，再写 `y-f(t)=f'(t)(x-t)`。需要比较系数时再展开。

### method: tangent-through-fixed-point

**名称**：把定点代入切线方程

先用切点横坐标写出切线方程，再将切线经过的固定点代入。消去非零公因子后，得到切点横坐标与待求参数之间的方程。

### method: root-count-parameter-range

**名称**：用方程实根个数表示切线条数

证明每个有效实根对应一个切点后，将“有几条切线”转化为“关于切点横坐标的方程有几个不同实根”。边界重根只对应一个切点，必须单独检查。

### method: quadratic-discriminant

**名称**：用判别式控制二次方程实根个数

当切线条件化为关于切点横坐标的一元二次方程时，用 `Δ>0`、`Δ=0`、`Δ<0` 分别判断两个不同实根、一个重根和无实根。

### method: common-tangent-parameterization

**名称**：双切点参数化公切线

分别设两个切点横坐标，比较两条切线的斜率和截距。不得默认两个切点横坐标相同。

### method: eliminate-contact-parameter

**名称**：消元得到参数函数

用斜率条件先表示第二切点，再用截距条件将待求参数写成生成变量的函数 `a=A(t)`。

### method: derivative-sign-analysis

**名称**：导函数符号分析

求出全部临界点与定义域分界点，在每个区间判断导函数正负，并据此写单调区间和局部极值。

### method: global-extremum-comparison

**名称**：比较候选求全局极值

比较局部极值、端点值和其他可能的候选值，区分局部最值与全局答案。

### method: endpoint-and-infinity-check

**名称**：检查端点与无穷趋势

在开区间、半无限区间或全实数域上补充端点极限与无穷远趋势，完成值域证明。
