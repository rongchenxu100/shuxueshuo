# 南开 25 Method Solver V1.5 运行结果

## Summary

- problem_id: `tj-2026-nankai-yimo-25`
- status: `ok`
- solver_family: `QuadraticPathMinimumSolver`
- checks: `36/36 passed`

## 原题

- 已知抛物线 y＝ax²＋bx＋c（a＞0）与 y 轴交于点 C，且满足 2a＋b＝0，对称轴与 x 轴的交点为 D。
- （Ⅰ）当 a＝2，c＝−5 时，求点 D 的坐标及抛物线的解析式；
- （Ⅱ）设 M(m,1)（m＞2）在抛物线上，N 在抛物线上且在第四象限，∠MDN＝90°，DM＝DN。E 在线段 DM 上，G 在线段 MN 上，F 为 DN 的中点，且 DE＝√2·NG。
- ① 当 MN＝√10 时，直接写出抛物线的解析式及 EG＋FG 的最小值；
- ② 当 EG＋FG 的最小值为 5√10/2 时，求抛物线解析式及此时 G 的坐标。

## 最终答案

### i

- D: `(1, 0)`
- parabola: `2*x**2 - 4*x - 5`

### ii_1

- parabola: `x**2 - 2*x - 2`
- min_value: `5/2`

### ii_2

- parabola: `x**2/6 - x/3 - 7`
- G: `(4, -13/3)`

## Methods Used

1. `quadratic_axis_from_relation`
2. `quadratic_from_constraints`
3. `right_angle_equal_length_candidates`
4. `select_point_by_quadrant_constraint`
5. `parameter_from_segment_length`
6. `quadratic_from_constraints`
7. `midpoint_point`
8. `two_moving_points_path_reduction`
9. `broken_path_straightening_candidates`
10. `select_straightening_candidate`
11. `distance_between_points`
12. `parameter_from_minimum_value`
13. `quadratic_from_constraints`
14. `line_intersection_point`

## 推导步骤

### 1. 由系数关系确定 D

- 目标：确定对称轴与 x 轴交点
- 理由：二次函数对称轴为 x=-b/(2a)，再代入题设系数关系。
- 计算：`x=1`
- 结论：`D(1, 0)`
- Method：`quadratic_axis_from_relation`

### 2. 由约束求抛物线

- 目标：确定当前问的二次函数系数
- 理由：代入已知系数；联立额外系数方程。
- 计算：`a=2, c=-5, b=-4`
- 结论：`y=2*x**2 - 4*x - 5`
- Method：`quadratic_from_constraints`

### 3. 由直角等腰条件列出 N 候选点

- 目标：列出 N 的候选坐标
- 理由：直角等腰三角形的另一条直角边可由已知直角边顺、逆时针旋转 90° 得到。
- 计算：`N1=(2, 1 - m), N2=(0, m - 1)`
- 结论：`N 有 2 个候选点`
- Method：`right_angle_equal_length_candidates`

### 4. 由象限与参数约束筛选 N

- 目标：确定唯一的 N 坐标
- 理由：把候选点分别放到题设象限和参数范围下判断。
- 计算：`N1=(2, 1 - m), N2=(0, m - 1); N 在第四象限，且 m>2`
- 结论：`N(2, 1 - m)`
- Method：`select_point_by_quadrant_constraint`

### 5. 由长度条件求参数

- 目标：求 m 的值
- 理由：两点距离平方等于题设值，解一元方程并按定义域筛选。
- 计算：`m=3`
- 结论：`m=3`
- Method：`parameter_from_segment_length`

### 6. 由约束求抛物线

- 目标：确定当前问的二次函数系数
- 理由：把曲线点代入抛物线；联立额外系数方程。
- 计算：`a=1, b=-2, c=-2`
- 结论：`y=x**2 - 2*x - 2`
- Method：`quadratic_from_constraints`

### 7. 求中点 F

- 目标：由两端点坐标确定中点
- 理由：中点坐标等于两端点横纵坐标的平均值。
- 计算：`F=(3/2, 1/2 - m/2)`
- 结论：`F(3/2, 1/2 - m/2)`
- Method：`midpoint_point`

### 8. 把两动点路径转化为单动点路径

- 目标：将 EG+FG 转化为 DG+FG
- 理由：利用两个动点的线段绑定关系，把原路径中的两动点线段替换成等长的固定点到动点线段。
- 计算：`DE=√2·NG，可得 EG=DG`
- 结论：`EG+FG=DG+FG`
- Method：`two_moving_points_path_reduction`

### 9. 列出折线拉直候选

- 目标：为 DG+FG 生成可选的将军饮马转化
- 理由：动点在同一直线上时，可以把折线一端关于动点所在直线作对称，把折线最短问题转成两定点距离问题。
- 计算：`反射 D 得 D_prime(m + 1, 2 - m)，候选最短线段 D_primeF；反射 F 得 F_prime(m/2 + 3/2, 3/2 - m)，候选最短线段 F_primeD`
- 结论：`得到 2 个拉直候选`
- Method：`broken_path_straightening_candidates`

### 10. 选择折线拉直候选

- 目标：确定使用哪个对称点构造 D_prime
- 理由：比较候选反射点坐标复杂度，优先选择后续距离和交点计算更简单的候选。
- 计算：`D_prime 坐标复杂度=210；F_prime 坐标复杂度=516`
- 结论：`选择 D_prime(m + 1, 2 - m)，最小路径转化为 D_primeF`
- Method：`select_straightening_candidate`

### 11. 计算路径最小值表达式

- 目标：把折线路径转为最短线段距离
- 理由：路径转化后，折线最短值等于两个固定端点之间的距离。
- 计算：`d=sqrt(5*m**2 - 10*m + 10)/2`
- 结论：`最小值表达式为 sqrt(5*m**2 - 10*m + 10)/2，代入后为 5/2`
- Method：`distance_between_points`

### 12. 由最小值反求参数

- 目标：求 m 的值
- 理由：题目给出最小值，代入最小值表达式解方程。
- 计算：`m=8`
- 结论：`m=8`
- Method：`parameter_from_minimum_value`

### 13. 由约束求抛物线

- 目标：确定当前问的二次函数系数
- 理由：把曲线点代入抛物线；联立额外系数方程。
- 计算：`a=1/6, b=-1/3, c=-7`
- 结论：`y=x**2/6 - x/3 - 7`
- Method：`quadratic_from_constraints`

### 14. 求交点 G

- 目标：确定最短位置对应点
- 理由：最短时目标点同时位于两条约束直线上。
- 计算：`G=(4, -13/3)`
- 结论：`G(4, -13/3)`
- Method：`line_intersection_point`
