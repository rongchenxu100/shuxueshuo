"""Generate the locked F5-C fixtures from the pre-F5-B authored plans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "internal" / "functional-plan-fixtures"
TARGET = ROOT / "internal" / "functional-plan-scope-native-fixtures"


COMMON_MAPPINGS: dict[str, dict[tuple[str | None, str, str], str]] = {
    "tj-2026-nankai-yimo-25": {
        (None, "a_value", "fact"): "symbol_value_a",
        (None, "c_value", "fact"): "symbol_value_c",
        (None, "coefficient_relation", "fact"): "coefficient_relation_a_b",
        (None, "F_midpoint_of_DN", "fact"): "midpoint_definition_d_n_f",
        (None, "MN_length_squared_eq_10", "fact"): "length_squared_mn",
        (None, "right_angle_equal_length_MDN", "fact"): (
            "right_angle_equal_length_m_d_n_dm_dn"
        ),
        (None, "path_minimum_target", "fact"): "path_minimum_target_e_g_f",
        (None, "path_minimum_value_given", "fact"): "minimum_value",
        (None, "i.axis_point", "answer"): "i.D",
        (None, "ii_1.minimum_value", "answer"): "ii_1.min_value",
        (None, "ii_2.intersection", "answer"): "ii_2.G",
    },
    "tj-2026-heping-ermo-25": {
        (None, "b_value", "fact"): "symbol_value_b",
        (None, "c_value", "fact"): "symbol_value_c",
        (None, "square_AEKG", "fact"): "square_ae_a_e_k_g",
        (None, "F_midpoint_of_AE", "fact"): "midpoint_definition_a_e_f",
        (None, "H_square_diagonal_intersection", "fact"): (
            "square_center_h_square_ae_a_e_k_g"
        ),
        (None, "path_minimum_target", "fact"): (
            "path_minimum_target_h_f_m_g"
        ),
        (None, "path_minimum_value_given", "fact"): "minimum_value",
        (None, "i_2.E", "point"): "E",
        (None, "i_2.G", "point"): "G",
        (None, "ii.A", "point"): "A",
        (None, "ii.E", "point"): "E",
        (None, "ii.G", "point"): "G",
    },
    "tj-2026-xiqing-yimo-25": {
        (None, "AD_eq_2BC", "fact"): "segment_length_relation_ad_bc",
        (None, "b_value", "fact"): "symbol_value_b",
        (None, "m_gt_0", "fact"): "symbol_constraint_m",
        (None, "path_minimum_value_given", "fact"): "minimum_value",
        (None, "i_P", "answer"): "i.vertex",
        (None, "ii_1_b", "answer"): "ii_1.b",
        (None, "ii_2_b", "answer"): "ii_2.b",
    },
    "tj-2026-hexi-yimo-25": {
        ("ii", "A", "point"): "ii.A",
        ("iii", "A", "point"): "iii.A",
        ("i", "a_value", "fact"): "i.symbol_value_a",
        ("ii", "a_value", "fact"): "ii.symbol_value_a",
        ("iii", "a_value", "fact"): "iii.symbol_value_a",
        (None, "D_on_parabola", "fact"): "point_on_curve_parabola_d",
        (None, "b_gt_0", "fact"): "symbol_constraint_b",
        (None, "b_value", "fact"): "symbol_value_b",
        (None, "c_value", "fact"): "symbol_value_c",
        (None, "n_gt_0", "fact"): "symbol_constraint_n",
        (None, "path_minimum_target", "fact"): "path_minimum_target",
        (None, "path_minimum_value_given", "fact"): "minimum_value",
        (None, "right_angle_equal_length_CAD", "fact"): (
            "right_angle_equal_length_c_a_d_ac_ad"
        ),
        (None, "i_P", "answer"): "i.P",
        (None, "ii_D", "answer"): "ii.D",
        (None, "iii_b", "answer"): "iii.b",
    },
    "tj-2026-heping-yimo-25": {
        (None, "CN_eq_CM", "fact"): "equal_length_condition",
        (None, "M_on_segment_BC", "fact"): "point_on_segment_m_bc",
        (None, "N_on_ray_CD", "fact"): "point_on_ray_n_cd",
        (None, "angle_sum_CBE_ACO_45", "fact"): "angle_sum",
        (None, "path_minimum_target", "fact"): (
            "path_minimum_target_o_m_b_n"
        ),
        (None, "path_minimum_value_given", "fact"): "minimum_value",
        (None, "i_1_parabola", "answer"): "i_1.parabola",
        (None, "i_2_E", "answer"): "i_2.E",
        (None, "ii_a", "answer"): "ii.a",
    },
}


CALL_RESULT_REWRITES: dict[
    str,
    dict[tuple[str, str, int | None], tuple[str, str]],
] = {
    "tj-2026-nankai-yimo-25": {
        ("ii_derive_parabola", "curve_points", 1): (
            "ii_construct_N",
            "selected_target_point",
        ),
        ("ii_1_solve_m", "p2", None): (
            "ii_construct_N",
            "selected_target_point",
        ),
        ("ii_2_derive_G", "line2_p2", None): (
            "ii_construct_N",
            "selected_target_point",
        ),
    },
    "tj-2026-hexi-yimo-25": {
        ("derive_weighted_minimum_iii", "curve_point", None): (
            "derive_curve_point_iii",
            "point",
        ),
    },
}


def _rewrite_ref(
    value: Any,
    *,
    scope_id: str,
    mappings: dict[tuple[str | None, str, str], str],
) -> None:
    if isinstance(value, list):
        for item in value:
            _rewrite_ref(item, scope_id=scope_id, mappings=mappings)
        return
    if not isinstance(value, dict) or "ref" not in value:
        return
    key = (scope_id, value["ref"], value["kind"])
    fallback = (None, value["ref"], value["kind"])
    value["ref"] = mappings.get(key, mappings.get(fallback, value["ref"]))


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for problem_id, mappings in COMMON_MAPPINGS.items():
        path = SOURCE / f"{problem_id}.functional-plan.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for scope in payload["scopes"]:
            for call in scope["calls"]:
                for value in call.get("args", {}).values():
                    _rewrite_ref(
                        value,
                        scope_id=scope["scope_id"],
                        mappings=mappings,
                    )
                for value in call.get("return_bindings", {}).values():
                    _rewrite_ref(
                        value,
                        scope_id=scope["scope_id"],
                        mappings=mappings,
                    )
                for (
                    rewrite_call_id,
                    arg_name,
                    item_index,
                ), (producer_id, return_name) in CALL_RESULT_REWRITES.get(
                    problem_id,
                    {},
                ).items():
                    if call["call_id"] != rewrite_call_id:
                        continue
                    replacement = {
                        "from_call": producer_id,
                        "return": return_name,
                    }
                    if item_index is None:
                        call["args"][arg_name] = replacement
                    else:
                        call["args"][arg_name][item_index] = replacement
        destination = TARGET / f"{problem_id}.functional-plan.json"
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
