# 河西 25 Method Solver V1.5 运行结果

## Summary

- problem_id: `tj-2026-hexi-yimo-25`
- status: `ok`
- solver_family: `QuadraticWeightedPathMinimumSolver`
- checks: `30/30 passed`

## 原题

- 已知抛物线 y=ax²-bx+c，（a，b，c 为常数，b＞0）。
- （Ⅰ）当 a=1，b=2，c=3 时，求该抛物线顶点 P 的坐标；
- （Ⅱ）当 a=2 时，点 A(-1,0) 和点 D 在该抛物线上，点 C 为抛物线与 y 轴的交点，且 ∠CAD=90°，AC=AD，求点 D 的坐标；
- （Ⅲ）当 a=1 时，点 A(-1,0) 在该抛物线上，且有点 M(b+1/2,y_M) 在抛物线上，点 N(n,0) 是 x 轴正半轴上的动点，当 √2·MN+AN 的最小值为 21/4 时，求 b 的值。

## 最终答案

### i

- P: `(1, 2)`

### ii

- D: `(sqrt(2), 1)`

### iii

- b: `2`

## Methods Used

1. `quadratic_from_constraints`
2. `quadratic_vertex_point`
3. `quadratic_from_constraints`
4. `quadratic_y_axis_intercept_point`
5. `right_angle_equal_length_candidates`
6. `filter_point_candidates_by_quadratic_curve`
7. `select_curve_point_candidate_and_solve_coefficients`
8. `quadratic_from_constraints`
9. `point_on_parabola_at_x`
10. `weighted_axis_path_triangle_transform`
11. `linked_broken_path_geometric_minimum`

## 推导步骤

### 1. 由约束求抛物线

- 目标：确定当前问的二次函数系数
- 理由：代入已知系数。
- 计算：`a=1, b=2, c=3`
- 结论：`y=x**2 - 2*x + 3`
- Method：`quadratic_from_constraints`

### 2. 求二次函数顶点

- 目标：确定 P 的坐标
- 理由：二次函数顶点横坐标为 -B/(2A)，纵坐标代回解析式。
- 计算：`P=(1, 2)`
- 结论：`P(1, 2)`
- Method：`quadratic_vertex_point`

### 3. 由约束求抛物线

- 目标：确定当前问的二次函数系数
- 理由：代入已知系数；把曲线点代入抛物线；联立额外系数方程。
- 计算：`a=2, c=-b - 2`
- 结论：`y=-b*x - b + 2*x**2 - 2`
- Method：`quadratic_from_constraints`

### 4. 求 y 轴交点

- 目标：确定 C 的坐标
- 理由：抛物线与 y 轴交点满足 x=0，代入解析式即可。
- 计算：`C=(0, -b - 2)`
- 结论：`C(0, -b - 2)`
- Method：`quadratic_y_axis_intercept_point`

### 5. 由直角等腰条件列出 D 候选点

- 目标：列出 D 的候选坐标
- 理由：直角等腰三角形的另一条直角边可由已知直角边顺、逆时针旋转 90° 得到。
- 计算：`D1=(-b - 3, -1), D2=(b + 1, 1)`
- 结论：`D 有 2 个候选点`
- Method：`right_angle_equal_length_candidates`

### 6. 用抛物线条件筛选候选点

- 目标：筛选 D 的可行候选
- 理由：把每个候选点代入当前问的二次函数，并结合参数约束判断是否可能在曲线上。
- 计算：`D1: 无满足 b>0 的解；D2: b=-1 + sqrt(2)`
- 结论：`保留 1 个候选点`
- Method：`filter_point_candidates_by_quadratic_curve`

### 7. 代入 D 候选并求系数

- 目标：确定 D 及抛物线系数
- 理由：直角等长给出两个候选点；已知曲线点条件已在上一步代入，所以这里只需逐个把候选 D 代入当前问抛物线，再用参数约束筛选。
- 计算：`b=-1 + sqrt(2), c=-sqrt(2) - 1`
- 结论：`D(sqrt(2), 1)，y=2*x**2 - sqrt(2)*x + x - sqrt(2) - 1`
- Method：`select_curve_point_candidate_and_solve_coefficients`

### 8. 由约束求抛物线

- 目标：确定当前问的二次函数系数
- 理由：代入已知系数；把曲线点代入抛物线；联立额外系数方程。
- 计算：`a=1, c=-b - 1`
- 结论：`y=-b*x - b + x**2 - 1`
- Method：`quadratic_from_constraints`

### 9. 由横坐标求曲线上点

- 目标：确定 M 的坐标
- 理由：点在抛物线上，已知横坐标时把横坐标代入解析式。
- 计算：`x_M=b + 1/2`
- 结论：`M(b + 1/2, -b/2 - 3/4)`
- Method：`point_on_parabola_at_x`

### 10. 构造辅助三角形转化加权路径

- 目标：将 sqrt(2)*MN+AN 转化为 sqrt(2)*(MN+QN)
- 理由：构造等腰直角三角形 AQN，把加权项 AN 改写成同倍率下的 QN，从而把加权路径转成普通折线路径。
- 计算：`Q=(n/2 - 1/2, n/2 + 1/2)，AN=sqrt(2)*QN`
- 结论：`sqrt(2)*MN+AN=sqrt(2)*(MN+QN)`
- Method：`weighted_axis_path_triangle_transform`

### 11. 用折线拉直求加权路径最值

- 目标：由 sqrt(2)*(MN+QN) 的最短状态反求 b
- 理由：构造 Q 后，原目标等价于同倍率下的 MN+QN；折线拉直后，最短值就是 M 到 Q 运动射线的垂线段长度。
- 计算：`垂足=(b/4 - 5/8, b/4 + 3/8)，n=b/2 - 1/4，最小值=3*b/2 + 9/4`
- 结论：`b=2，n=3/4`
- Method：`linked_broken_path_geometric_minimum`

## 验算

- `known_coefficients_preserved`: passed，已知系数被保留
- `vertex_x_derivative_zero`: passed，顶点横坐标使一阶导数为 0
- `known_coefficients_preserved`: passed，已知系数被保留
- `extra_equation_0_satisfied`: passed，额外方程约束成立
- `curve_point_0_on_parabola`: passed，曲线点满足求得的抛物线
- `y_axis_x_is_zero`: passed，y 轴交点的横坐标为 0
- `candidate_1_right_equal_length`: passed，D 候选 1 与已知直角边等长
- `candidate_1_right_angle`: passed，D 候选 1 与已知直角边垂直
- `candidate_2_right_equal_length`: passed，D 候选 2 与已知直角边等长
- `candidate_2_right_angle`: passed，D 候选 2 与已知直角边垂直
- `at_least_one_candidate_kept`: passed，至少有一个候选点能满足曲线条件
- `candidate_filter_completed`: passed，所有候选点都已完成曲线条件验证
- `unique_curve_candidate`: passed，只有一个候选点满足曲线与系数约束
- `primary_constraint_satisfied`: passed，b 满足题设约束
- `selected_point_on_parabola`: passed，D 在求得的抛物线上
- `known_coefficients_preserved`: passed，已知系数被保留
- `extra_equation_0_satisfied`: passed，额外方程约束成立
- `curve_point_0_on_parabola`: passed，曲线点满足求得的抛物线
- `point_on_parabola`: passed，点坐标满足抛物线解析式
- `triangle_is_right_angle`: passed，AQ 与 QN 垂直
- `triangle_equal_legs`: passed，AQ 与 QN 等长
- `weighted_segment_replaced`: passed，AN 可以替换为 sqrt(2)*QN
- `auxiliary_point_on_fixed_ray`: passed，Q 在由 A 引出的 45 度射线上
- `straightened_points_collinear`: passed，最短状态下 M、N、Q 共线
- `auxiliary_point_on_locus`: passed，最短状态下辅助点仍在声明的运动射线上
- `auxiliary_point_is_locus_foot`: passed，最短状态下辅助点是曲线点到运动射线的垂足
- `straightened_line_perpendicular_to_locus`: passed，拉直后的 MQ 垂直于 Q 的运动射线
- `parameter_constraint_satisfied`: passed，b 满足题设约束
- `dynamic_constraint_satisfied`: passed，n 满足动点范围
- `minimum_value_matches`: passed，几何最小值等于题设给定值
