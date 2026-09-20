# 操作目录（由契约生成）

可选字段标记为 `?`；操作类型和字段均来自 `contracts.py`。

|类型|字段|
|---|---|
|`quantified_relation`|`quantifier variable domain expression operator value`|
|`any_of`|`branches`|
|`polygon`|`vertices`|
|`angle_equal`|`angles`|
|`angle_ratio`|`angles ratio`|
|`angle_value`|`angle degrees`|
|`right_angle`|`angle`|
|`angle_sum`|`angles degrees`|
|`equal_length`|`segments`|
|`length_ratio`|`segments ratio`|
|`cut_ratio`|`segment by ratio`|
|`length_value`|`segment value`|
|`squared_length_value`|`segment value`|
|`area_equal`|`triangles`|
|`area_ratio`|`triangles ratio`|
|`area_value`|`triangle value`|
|`midpoint`|`point segment`|
|`intersection`|`point segments interior?`|
|`diagonal`|`polygon segment`|
|`diagonal_bisects`|`polygon bisector bisected`|
|`parallel`|`segments`|
|`perpendicular`|`segments`|
|`point_on_ray`|`point ray`|
|`point_on_segment`|`point segment interior?`|
|`square`|`polygon`|
|`parallelogram`|`polygon`|
|`coordinates`|`point coordinates`|
|`origin`|`point`|
|`translation`|`point original vector`|
|`curve_equation`|`curve expression independent dependent`|
|`curve_at_x`|`point curve x`|
|`curve_landmark`|`point curve landmark side? exclude_point?`|
|`point_on_curve`|`point curve`|
|`point_on_axis`|`point axis curve?`|
|`scalar_constraint`|`symbol operator value`|
|`quantity_relation`|`expression operator value`|
|`extremum_constraint`|`expression direction variables value?`|
|`find_range`|`symbol in_terms_of?`|
|`find_value`|`target in_terms_of?`|
|`find_length`|`segment in_terms_of?`|
|`find_angle`|`angle in_terms_of?`|
|`find_area`|`triangle in_terms_of?`|
|`find_area_ratio`|`triangles in_terms_of?`|
|`find_length_ratio`|`segments in_terms_of?`|
|`find_tan`|`angle in_terms_of?`|
|`find_coordinates`|`point`|
|`find_equation`|`curve`|
|`find_minimum`|`expression variables in_terms_of?`|
|`find_maximum`|`expression variables in_terms_of?`|
