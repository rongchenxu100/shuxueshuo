# Method Solver V1.5 运行结果

- problem_id: `tj-2026-nankai-yimo-25`
- status: `ok`
- solver_family: `QuadraticPathMinimumSolver`
- checks: `29/29` passed

## 答案

- 第（Ⅰ）问：D=['1', '0']，抛物线 `2*x**2 - 4*x - 5`
- 第（Ⅱ）①问：m=`3`，抛物线 `x**2 - 2*x - 2`，最小值 `5/2`
- 第（Ⅱ）②问：m=`8`，抛物线 `x**2/6 - x/3 - 7`，G=['4', '-13/3']

## Method 顺序

1. `quadratic_axis_from_relation`
2. `quadratic_from_known_coefficients`
3. `right_angle_equal_length_candidates`
4. `select_point_by_quadrant_constraint`
5. `parameter_from_segment_length`
6. `quadratic_coefficients_from_curve_points`
7. `midpoint_point`
8. `two_moving_points_path_reduction`
9. `broken_path_straightening_candidates`
10. `select_straightening_candidate`
11. `distance_between_points`
12. `parameter_from_minimum_value`
13. `quadratic_coefficients_from_curve_points`
14. `line_intersection_point`

## 推导步骤

### 1. 由系数关系确定 D

- 目标：确定对称轴与 x 轴交点
- 理由：二次函数对称轴为 x=-b/(2a)，再代入题设系数关系。
- 计算：x=1
- 结论：D(1, 0)
- Method：`quadratic_axis_from_relation`

### 2. 代入已知系数求抛物线

- 目标：写出当前问的抛物线解析式
- 理由：已知系数直接代入，缺失系数由题设关系确定。
- 计算：a=2, c=-5, b=-4
- 结论：y=2*x**2 - 4*x - 5
- Method：`quadratic_from_known_coefficients`

### 3. 由直角等腰条件列出 N 候选点

- 目标：列出 N 的候选坐标
- 理由：直角等腰三角形的另一条直角边可由已知直角边顺、逆时针旋转 90° 得到。
- 计算：N1=(2, 1 - m), N2=(0, m - 1)
- 结论：N 有 2 个候选点
- Method：`right_angle_equal_length_candidates`

### 4. 由象限与参数约束筛选 N

- 目标：确定唯一的 N 坐标
- 理由：把候选点分别放到题设象限和参数范围下判断。
- 计算：N1=(2, 1 - m), N2=(0, m - 1); N 在第四象限，且 m>2
- 结论：N(2, 1 - m)
- Method：`select_point_by_quadrant_constraint`

### 5. 由长度条件求参数

- 目标：求 m 的值
- 理由：两点距离平方等于题设值，解一元方程并按定义域筛选。
- 计算：m=3
- 结论：m=3
- Method：`parameter_from_segment_length`

### 6. 由点在抛物线上求抛物线

- 目标：确定当前小问的二次函数系数
- 理由：先代入 m=3，再把点坐标代入抛物线，并联立系数关系。
- 计算：a=1, b=-2, c=-2
- 结论：y=x**2 - 2*x - 2
- Method：`quadratic_coefficients_from_curve_points`

### 7. 求中点 F

- 目标：由两端点坐标确定中点
- 理由：中点坐标等于两端点横纵坐标的平均值。
- 计算：F=(3/2, 1/2 - m/2)
- 结论：F(3/2, 1/2 - m/2)
- Method：`midpoint_point`

### 8. 把两动点路径转化为单动点路径

- 目标：将 EG+FG 转化为 DG+FG
- 理由：利用两个动点的线段绑定关系，把原路径中的两动点线段替换成等长的固定点到动点线段。
- 计算：DE=√2·NG，可得 EG=DG
- 结论：EG+FG=DG+FG
- Method：`two_moving_points_path_reduction`

### 9. 列出折线拉直候选

- 目标：为 DG+FG 生成可选的将军饮马转化
- 理由：动点在同一直线上时，可以把折线一端关于动点所在直线作对称，把折线最短问题转成两定点距离问题。
- 计算：反射 D 得 D_prime(m + 1, 2 - m)，候选最短线段 D_primeF；反射 F 得 F_prime(m/2 + 3/2, 3/2 - m)，候选最短线段 F_primeD
- 结论：得到 2 个拉直候选
- Method：`broken_path_straightening_candidates`

### 10. 选择折线拉直候选

- 目标：确定使用哪个对称点构造 D_prime
- 理由：比较候选反射点坐标复杂度，优先选择后续距离和交点计算更简单的候选。
- 计算：D_prime 坐标复杂度=210；F_prime 坐标复杂度=516
- 结论：选择 D_prime(m + 1, 2 - m)，最小路径转化为 D_primeF
- Method：`select_straightening_candidate`

### 11. 计算路径最小值表达式

- 目标：把折线路径转为最短线段距离
- 理由：路径转化后，折线最短值等于两个固定端点之间的距离。
- 计算：d=sqrt(5*m**2 - 10*m + 10)/2
- 结论：最小值表达式为 sqrt(5*m**2 - 10*m + 10)/2，代入后为 5/2
- Method：`distance_between_points`

### 12. 由最小值反求参数

- 目标：求 m 的值
- 理由：题目给出最小值，代入最小值表达式解方程。
- 计算：m=8
- 结论：m=8
- Method：`parameter_from_minimum_value`

### 13. 由点在抛物线上求抛物线

- 目标：确定当前小问的二次函数系数
- 理由：先代入 m=8，再把点坐标代入抛物线，并联立系数关系。
- 计算：a=1/6, b=-1/3, c=-7
- 结论：y=x**2/6 - x/3 - 7
- Method：`quadratic_coefficients_from_curve_points`

### 14. 求交点 G

- 目标：确定最短位置对应点
- 理由：最短时目标点同时位于两条约束直线上。
- 计算：G=(4, -13/3)
- 结论：G(4, -13/3)
- Method：`line_intersection_point`

## Checks

- `axis_point_on_x_axis`: passed，D 在 x 轴上
- `known_coefficients_match_relation`: passed，补齐后的系数满足题设关系
- `candidate_1_right_equal_length`: passed，N 候选 1 与已知直角边等长
- `candidate_1_right_angle`: passed，N 候选 1 与已知直角边垂直
- `candidate_2_right_equal_length`: passed，N 候选 2 与已知直角边等长
- `candidate_2_right_angle`: passed，N 候选 2 与已知直角边垂直
- `quadrant_filter_unique`: passed，象限与参数约束选出唯一候选点
- `parameter_constraint_used`: passed，N 在第四象限，且 m>2
- `parameter_domain`: passed，参数满足定义域
- `length_condition_matches`: passed，距离条件成立
- `coefficients_match_relation`: passed，通式系数满足题设关系
- `curve_point_0_on_parabola`: passed，代入点满足通式抛物线
- `curve_point_1_on_parabola`: passed，代入点满足通式抛物线
- `midpoint_average`: passed，F 的坐标为端点坐标平均值
- `moving_points_binding_relation`: passed，两个动点的绑定线段关系成立
- `moving_segment_equal_fixed_segment`: passed，EG 与 DG 等长
- `reflect_D_reflection_preserves_distance`: passed，D_prime 关于 MN 对称后保持到动点的距离
- `reflect_F_reflection_preserves_distance`: passed，F_prime 关于 MN 对称后保持到动点的距离
- `straightening_candidate_unique_minimum_score`: passed，存在唯一最低复杂度候选
- `selected_candidate_matches_target_name`: passed，选择结果对应目标辅助点 D_prime
- `distance_is_nonzero`: passed，距离表达式非零
- `evaluated_distance_positive`: passed，代入后的最小值为正
- `minimum_parameter_domain`: passed，参数满足定义域
- `minimum_value_matches`: passed，最小值匹配题设
- `coefficients_match_relation`: passed，通式系数满足题设关系
- `curve_point_0_on_parabola`: passed，代入点满足通式抛物线
- `curve_point_1_on_parabola`: passed，代入点满足通式抛物线
- `intersection_on_line1`: passed，G 在第一条直线上
- `intersection_on_line2`: passed，G 在第二条直线上
