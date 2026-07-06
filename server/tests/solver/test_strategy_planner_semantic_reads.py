from __future__ import annotations

from importlib import util
from pathlib import Path
from types import SimpleNamespace

from shuxueshuo_server.solver.runtime.handle_alias_index import HandleAliasIndex

# Transitional domain split: shared fixtures/helpers still live in
# test_strategy_planner_phase1.py until the support module is extracted.
_base_path = Path(__file__).with_name("test_strategy_planner_phase1.py")
_spec = util.spec_from_file_location("_strategy_planner_phase1_base", _base_path)
assert _spec is not None and _spec.loader is not None
_base = util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
for _name in dir(_base):
    if _name.startswith("__") or _name.startswith("test_"):
        continue
    globals()[_name] = getattr(_base, _name)
del _name, _base, _base_path, _spec, util


def test_strategy_payload_includes_semantic_read_catalog_without_handles() -> None:
    """semantic read catalog 给 LLM 语义引用，不暴露 canonical handle。"""
    payload = _nankai_payload()
    catalog = payload["semantic_read_catalog"]
    items = catalog["items"]

    assert catalog["item_count"] == len(items)
    assert {"ref": "D", "kind": "point", "scope": "problem"} in [
        {
            "ref": item["ref"],
            "kind": item["kind"],
            "scope": item["scope"],
        }
        for item in items
    ]
    assert any(
        item["kind"] == "fact"
        and item["ref"] == "coefficient_relation"
        and item.get("value_type") == "coefficient_relation"
        for item in items
    )
    assert any(
        item["kind"] == "answer"
        and item["ref"] == "i.parabola"
        and item.get("value_type") == "Parabola"
        for item in items
    )
    assert all("handle" not in item for item in items)


def test_semantic_read_catalog_uses_registry_answer_valid_scope() -> None:
    """answer catalog 的 scope 应来自 registry，而不是从 answer id 字符串猜测。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii", "ii_1")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(("answer:foo_bar",)),
        scope_parents={"problem": None, "ii": "problem", "ii_1": "ii"},
        answer_value_types={"answer:foo_bar": "Parabola"},
        handle_valid_scopes={"answer:foo_bar": "ii_1"},
    )

    catalog = SemanticReadResolver(registry).initial_catalog_payload()
    item = catalog["items"][0]

    assert item["kind"] == "answer"
    assert item["ref"] == "foo_bar"
    assert item["scope"] == "ii_1"
    assert item["valid_scope"] == "ii_1"


def test_handle_alias_index_matches_initial_point_coordinate_fact_without_from_step() -> None:
    """题面初始坐标 fact 没有 source_step_id，也应支持 object-facing point read。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i")),
        entity_handles=frozenset(("point:problem:A",)),
        fact_handles=frozenset(("fact:problem:A_coordinate",)),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "i": "problem"},
        fact_types={"fact:problem:A_coordinate": "point_coordinate"},
        handle_valid_scopes={
            "point:problem:A": "problem",
            "fact:problem:A_coordinate": "problem",
        },
    )
    item = SimpleNamespace(
        kind="fact",
        ref="A_coordinate",
        handle="fact:problem:A_coordinate",
        valid_scope="problem",
        source_step_id=None,
    )

    matches = HandleAliasIndex.point_coordinate_fact_items(
        kind="point",
        ref="A",
        from_step=None,
        scope_id="i",
        items=(item,),
        registry=registry,
        value_type_matches=lambda _item: True,
    )

    assert matches == [item]


def test_step_intent_schema_semantic_read_kinds_use_shared_constant() -> None:
    """Schema enum 应与 semantic/canonical handle kind 常量保持单源同步。"""
    kind_schema = (
        STEP_INTENT_JSON_SCHEMA["properties"]["scopes"]["items"]["properties"]
        ["steps"]["items"]["properties"]["semantic_reads"]["items"]["properties"]
        ["kind"]["enum"]
    )

    assert kind_schema == list(SEMANTIC_READ_KIND_ORDER)


def test_step_intent_validator_resolves_semantic_reads_before_handle_validation() -> None:
    """semantic_reads 应覆盖 legacy reads，并解析成 canonical StepIntent.reads。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    first_step = payload["scopes"][0]["steps"][0]
    first_step["reads"] = ["fact:problem:not_a_real_handle"]
    first_step["semantic_reads"] = [
        {"kind": "function", "ref": "parabola"},
        {"kind": "point", "ref": "D"},
        {
            "kind": "fact",
            "ref": "coefficient_relation",
            "value_type": "coefficient_relation",
        },
    ]

    validator = StepIntentValidator()
    draft = validator.validate_json(
        json.dumps(payload, ensure_ascii=False),
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
    )

    assert draft.steps[0].reads == (
        "function:problem:parabola",
        "point:problem:D",
        "fact:problem:coefficient_relation",
    )
    assert validator.last_semantic_read_resolution_report is not None
    assert validator.last_semantic_read_resolution_report.changed
    assert all(
        item.overrode_legacy_reads
        for item in validator.last_semantic_read_resolution_report.resolutions
    )


def test_semantic_reads_can_reference_initial_answer_handle() -> None:
    """初始 answer catalog item 也可通过 semantic_reads 解析。"""
    payload = _valid_step_intent_payload()
    step = payload["scopes"][0]["steps"][0]
    step["reads"] = []
    step["semantic_reads"] = [
        {
            "kind": "answer",
            "ref": "i.parabola",
            "value_type": "Parabola",
        },
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.steps[0].reads == ("answer:i.parabola",)


def test_semantic_reads_accepts_initial_canonical_answer_handle() -> None:
    """answer canonical handle 也可直接作为 semantic_reads.ref。"""
    payload = _valid_step_intent_payload()
    step = payload["scopes"][0]["steps"][0]
    step["reads"] = []
    step["semantic_reads"] = [
        {
            "kind": "answer",
            "ref": "answer:i.parabola",
            "value_type": "Parabola",
        },
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.steps[0].reads == ("answer:i.parabola",)


def test_semantic_reads_accepts_initial_canonical_handles() -> None:
    """semantic_reads.ref 也兼容直接复制 ProblemIR 的 canonical handle。"""
    payload = _valid_step_intent_payload()
    step = payload["scopes"][0]["steps"][0]
    step["reads"] = ["fact:problem:not_a_real_handle"]
    step["semantic_reads"] = [
        {"kind": "function", "ref": "function:problem:parabola"},
        {"kind": "point", "ref": "point:problem:D"},
        {
            "kind": "fact",
            "ref": "fact:problem:coefficient_relation",
            "value_type": "coefficient_relation",
        },
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.steps[0].reads == (
        "function:problem:parabola",
        "point:problem:D",
        "fact:problem:coefficient_relation",
    )


def test_semantic_and_legacy_scope_name_alias_share_resolution() -> None:
    """semantic_reads 与 legacy reads 的 ``scope:name`` alias 应同源解析。"""
    semantic_payload = _valid_step_intent_payload()
    semantic_step = semantic_payload["scopes"][0]["steps"][0]
    semantic_step["reads"] = []
    semantic_step["semantic_reads"] = [
        {
            "kind": "fact",
            "ref": "problem:coefficient_relation",
            "value_type": "coefficient_relation",
        },
    ]

    legacy_payload = _valid_step_intent_payload()
    legacy_step = legacy_payload["scopes"][0]["steps"][0]
    legacy_step["reads"] = ["problem:coefficient_relation"]

    semantic_draft = StepIntentValidator().validate_json(
        json.dumps(semantic_payload, ensure_ascii=False),
        handle_registry=_registry(),
    )
    legacy_draft = StepIntentValidator().validate_json(
        json.dumps(legacy_payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert semantic_draft.steps[0].reads == ("fact:problem:coefficient_relation",)
    assert legacy_draft.steps[0].reads == semantic_draft.steps[0].reads


def test_semantic_reads_accepts_quadratic_value_type_for_function_entity() -> None:
    """DeepSeek 可把 untyped function entity 标成 value_type=quadratic。"""
    payload = _valid_step_intent_payload()
    step = payload["scopes"][0]["steps"][0]
    step["reads"] = ["fact:problem:not_a_real_handle"]
    step["semantic_reads"] = [
        {"kind": "function", "ref": "parabola", "value_type": "quadratic"},
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.steps[0].reads == ("function:problem:parabola",)


def _dynamic_parent_coordinate_payload() -> dict[str, object]:
    return {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_axis_point",
                        "recipe_hint": "quadratic_axis_from_relation",
                        "goal_type": "derive_point",
                        "target": "answer:i.axis_point",
                        "strategy": "求公共锚点坐标。",
                        "reads": ["function:problem:parabola"],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:problem:anchor_coordinate_value",
                                "valid_scope": "problem",
                                "description": "公共锚点坐标，全题有效。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "后续步骤需要读取公共坐标。",
                    }
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_constructed_point",
                        "recipe_hint": None,
                        "goal_type": "derive_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "读取公共锚点并构造后续点。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:moving_point_coordinate_expr",
                                "valid_scope": "ii",
                                "description": "动点坐标表达式。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试 semantic 前序产物读取。",
                    }
                ],
            },
        ]
    }


def test_semantic_reads_can_reference_previous_produced_fact_by_from_step() -> None:
    """前序 produces 需要通过 from_step 精确引用。"""
    payload = _dynamic_parent_coordinate_payload()
    second_step = payload["scopes"][1]["steps"][0]
    second_step["reads"] = [
        "function:problem:parabola",
        "fact:problem:anchor_coordinate_value",
    ]
    second_step["semantic_reads"] = [
        {"kind": "function", "ref": "parabola"},
        {
            "kind": "fact",
            "ref": "anchor_coordinate_value",
            "from_step": "derive_axis_point",
        },
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.scopes[1].steps[0].reads == (
        "function:problem:parabola",
        "fact:problem:anchor_coordinate_value",
    )


def test_semantic_reads_accepts_previous_canonical_produced_fact_by_from_step() -> None:
    """前序 produces 可用 canonical handle 作为 semantic_reads.ref。"""
    payload = _dynamic_parent_coordinate_payload()
    second_step = payload["scopes"][1]["steps"][0]
    second_step["reads"] = ["fact:problem:not_a_real_handle"]
    second_step["semantic_reads"] = [
        {
            "kind": "fact",
            "ref": "fact:problem:anchor_coordinate_value",
            "from_step": "derive_axis_point",
        },
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.scopes[1].steps[0].reads == ("fact:problem:anchor_coordinate_value",)


def test_semantic_reads_infers_missing_from_step_for_previous_produced_fact() -> None:
    """漏写 from_step 时，唯一可见前序 produces 应由代码确定性补齐。"""
    payload = _dynamic_parent_coordinate_payload()
    second_step = payload["scopes"][1]["steps"][0]
    second_step["reads"] = ["fact:problem:not_a_real_handle"]
    second_step["semantic_reads"] = [
        {
            "kind": "fact",
            "ref": "anchor_coordinate_value",
        },
    ]

    validator = StepIntentValidator()
    draft = validator.validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.scopes[1].steps[0].reads == ("fact:problem:anchor_coordinate_value",)
    assert validator.last_semantic_read_resolution_report is not None
    resolution = validator.last_semantic_read_resolution_report.resolutions[0]
    assert resolution.inferred_from_step == "derive_axis_point"


def test_semantic_reads_infers_missing_from_step_for_canonical_parent_scope_fact() -> None:
    """覆盖真实 DeepSeek：canonical dynamic fact 漏 from_step 但唯一可见时可解析。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i", "ii", "ii_1")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={
            "problem": None,
            "i": "problem",
            "ii": "problem",
            "ii_1": "ii",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_anchor_coordinate_i",
                        "recipe_hint": "quadratic_axis_from_relation",
                        "goal_type": "derive_axis_point",
                        "target": "answer:i.axis_point",
                        "strategy": "求 锚点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:problem:anchor_coordinate",
                                "valid_scope": "problem",
                                "description": "锚点坐标，全题有效。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试父级动态 fact。",
                    }
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "construct_N_from_right_angle",
                        "recipe_hint": "right_angle_equal_length_construct_and_select",
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "读取 锚点坐标构造 N。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "fact:problem:anchor_coordinate",
                                "value_type": "Point",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试漏写 from_step 自动推断。",
                    }
                ],
            },
        ]
    }

    validator = StepIntentValidator()
    draft = validator.validate(payload, handle_registry=registry)

    assert draft.scopes[1].steps[0].reads == ("fact:problem:anchor_coordinate",)
    assert validator.last_semantic_read_resolution_report is not None
    resolution = validator.last_semantic_read_resolution_report.resolutions[0]
    assert resolution.inferred_from_step == "derive_anchor_coordinate_i"


def test_semantic_reads_accepts_previous_canonical_created_entity_by_from_step() -> None:
    """前序 creates 也可用 canonical handle 作为 semantic_reads.ref。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "make_aux",
                        "recipe_hint": None,
                        "goal_type": "construct_auxiliary_point",
                        "target": "point:ii:Aux",
                        "strategy": "构造辅助点。",
                        "reads": [],
                        "creates": [_create("point:ii:Aux", "point", "ii")],
                        "produces": [],
                        "reason": "测试 creates。",
                    },
                    {
                        "step_id": "read_aux",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "读取辅助点。",
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "point:ii:Aux",
                                "from_step": "make_aux",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 canonical created entity ref。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("point:ii:Aux",)


def test_semantic_reads_infers_missing_from_step_for_previous_created_entity() -> None:
    """漏写 from_step 时，唯一可见前序 creates 也可自动补齐。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "make_aux",
                        "recipe_hint": None,
                        "goal_type": "construct_auxiliary_point",
                        "target": "point:ii:Aux",
                        "strategy": "构造辅助点。",
                        "reads": [],
                        "creates": [_create("point:ii:Aux", "point", "ii")],
                        "produces": [],
                        "reason": "测试 creates。",
                    },
                    {
                        "step_id": "read_aux",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "读取辅助点。",
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "Aux",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 inferred from_step。",
                    },
                ],
            }
        ]
    }

    validator = StepIntentValidator()
    draft = validator.validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("point:ii:Aux",)
    assert validator.last_semantic_read_resolution_report is not None
    resolution = validator.last_semantic_read_resolution_report.resolutions[0]
    assert resolution.inferred_from_step == "make_aux"


def test_semantic_reads_accepts_dynamic_point_coordinate_alias() -> None:
    """动态坐标类 fact 的 Point output 可被 point_coordinate 语义读取。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_moving_point_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "构造 动点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:moving_point_coordinate_expr",
                                "valid_scope": "ii",
                                "description": "动点坐标表达式。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试动态坐标产物。",
                    },
                    {
                        "step_id": "read_moving_point_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "读取 动点坐标。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "moving_point_coordinate_expr",
                                "value_type": "point_coordinate",
                                "from_step": "construct_moving_point_coordinate",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 point_coordinate alias。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("fact:ii:moving_point_coordinate_expr",)


def test_semantic_reads_accepts_initial_point_coordinate_state_from_point_ref() -> None:
    """LLM 可用 point + point_coordinate 读取题面点坐标状态。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:problem:A",)),
        fact_handles=frozenset(("fact:problem:A_coordinate_value",)),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        fact_types={"fact:problem:A_coordinate_value": "point_coordinate"},
        handle_valid_scopes={
            "point:problem:A": "problem",
            "fact:problem:A_coordinate_value": "problem",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "read_A_coordinate_state",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "读取 A 点及其坐标状态。",
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "A",
                                "value_type": "point_coordinate",
                            },
                            {
                                "kind": "point",
                                "ref": "A",
                            },
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试对象状态读取。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[0].reads == (
        "fact:problem:A_coordinate_value",
        "point:problem:A",
    )


def test_semantic_reads_accepts_dynamic_coordinate_suffix_point_ref() -> None:
    """kind=point/ref=B_coordinate 应归一到 B 的坐标状态。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_B_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_axis_intercept_point",
                        "target": "fact:ii:B_coordinate",
                        "strategy": "求 B 坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:B_coordinate",
                                "valid_scope": "ii",
                                "description": "B 点坐标。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试动态坐标产物。",
                    },
                    {
                        "step_id": "read_B_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "读取 B 坐标。",
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "B_coordinate",
                                "value_type": "point_coordinate",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试坐标后缀 alias。",
                    },
                ],
            }
        ]
    }

    validator = StepIntentValidator()
    draft = validator.validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("fact:ii:B_coordinate",)
    assert validator.last_semantic_read_resolution_report is not None
    resolution = validator.last_semantic_read_resolution_report.resolutions[-1]
    assert resolution.inferred_from_step == "derive_B_coordinate"


def test_semantic_reads_rejects_ambiguous_point_coordinate_state_alias() -> None:
    """多个可见同名坐标状态时，point ref 不能静默挑一个。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:problem:A",)),
        fact_handles=frozenset((
            "fact:problem:A_coordinate",
            "fact:ii:A_coordinate",
        )),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        fact_types={
            "fact:problem:A_coordinate": "point_coordinate",
            "fact:ii:A_coordinate": "point_coordinate",
        },
        handle_valid_scopes={
            "point:problem:A": "problem",
            "fact:problem:A_coordinate": "problem",
            "fact:ii:A_coordinate": "ii",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "read_ambiguous_A_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "读取 A 坐标。",
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "A",
                                "value_type": "point_coordinate",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试歧义。",
                    },
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_ambiguous"):
        StepIntentValidator().validate(payload, handle_registry=registry)


def test_semantic_reads_accepts_dynamic_coordinate_point_alias() -> None:
    """动态坐标类 fact 的 Point output 也可被 point 语义读取。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_anchor_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_axis_point",
                        "target": "fact:problem:anchor_coordinate",
                        "strategy": "求 锚点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:problem:anchor_coordinate",
                                "valid_scope": "problem",
                                "description": "锚点坐标。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试动态坐标产物。",
                    },
                    {
                        "step_id": "read_anchor_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "读取 锚点坐标。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "anchor_coordinate",
                                "value_type": "point",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 point alias。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("fact:problem:anchor_coordinate",)


def test_semantic_reads_accepts_point_ref_for_dynamic_coordinate_fact() -> None:
    """DeepSeek 写 kind=point/from_step=N 时可读回唯一 动点坐标 fact。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_moving_point_coordinate_ii",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "求 动点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:moving_point_coordinate_expr",
                                "valid_scope": "ii",
                                "description": "动点坐标表达式。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试动态坐标产物。",
                    },
                    {
                        "step_id": "use_moving_point_coordinate_ii",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "读取 动点坐标。",
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "moving_point",
                                "from_step": "derive_moving_point_coordinate_ii",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 point ref alias。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("fact:ii:moving_point_coordinate_expr",)


def test_semantic_reads_do_not_fallback_to_valid_legacy_reads() -> None:
    """semantic_reads 失败时，即使 legacy reads 可见也必须阻断。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:ii:N",)),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_moving_point_coordinate_ii",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "求 动点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:moving_point_coordinate_expr",
                                "valid_scope": "ii",
                                "description": "动点坐标表达式。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试前序产物。",
                    },
                    {
                        "step_id": "use_legacy_reads",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "semantic 误写时不应读取 canonical reads。",
                        "reads": ["point:ii:N"],
                        "semantic_reads": [
                            {
                                "kind": "point",
                                "ref": "missing_N",
                                "from_step": "derive_moving_point_coordinate_ii",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 semantic 优先。",
                    },
                ],
            }
        ]
    }

    validator = StepIntentValidator()
    with pytest.raises(StrategyDraftValidationError, match="semantic_read_unknown"):
        validator.validate(payload, handle_registry=registry)

    report = validator.last_semantic_read_resolution_report
    assert report is not None
    assert report.ok is False
    assert report.fallbacks == ()
    assert [item.code for item in report.errors] == ["semantic_read_unknown"]


def test_semantic_reads_partial_success_does_not_fallback_to_legacy_reads() -> None:
    """semantic_reads 部分成功时不能整步 fallback 到 legacy reads。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:ii:N", "point:ii:Old")),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "partial_semantic_reads",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "semantic 部分写对时不能退回旧 reads。",
                        "reads": ["point:ii:Old"],
                        "semantic_reads": [
                            {"kind": "point", "ref": "N"},
                            {"kind": "point", "ref": "missing_N"},
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 partial semantic 优先。",
                    },
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    assert draft is None
    assert report.ok is False
    assert report.semantic_read_resolution is not None
    semantic_report = report.semantic_read_resolution
    assert [item.handle for item in semantic_report.resolutions] == ["point:ii:N"]
    assert [item.code for item in semantic_report.errors] == ["semantic_read_unknown"]
    assert semantic_report.fallbacks == ()
    assert semantic_report.partially_resolved_payload is not None
    partial_step = semantic_report.partially_resolved_payload["scopes"][0]["steps"][0]
    assert partial_step["reads"] == ["point:ii:N"]
    assert "semantic_reads" not in partial_step


def test_semantic_reads_do_not_index_malformed_dynamic_produces() -> None:
    """动态 catalog 不应从未通过结构校验的 produces 中建立 phantom item。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_moving_point_coordinate_ii",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "求 动点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:moving_point_coordinate_expr",
                                "valid_scope": "ii",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "produces 缺 description，不应进入 semantic catalog。",
                    },
                    {
                        "step_id": "use_moving_point_coordinate_ii",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "尝试读取 malformed 前序产物。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "moving_point_coordinate_expr",
                                "value_type": "Point",
                                "from_step": "derive_moving_point_coordinate_ii",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 phantom dynamic catalog 防护。",
                    },
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    assert draft is None
    assert report.ok is False
    assert report.semantic_read_resolution is not None
    semantic_report = report.semantic_read_resolution
    assert semantic_report.resolutions == ()
    assert [item.code for item in semantic_report.errors] == [
        "semantic_read_dynamic_catalog_malformed",
        "semantic_read_unknown",
    ]
    assert "produces[0] missing required fields: description" in (
        semantic_report.errors[0].message
    )


def test_semantic_reads_ignores_extra_fields_and_records_warning() -> None:
    """catalog 展示字段误带入 semantic_reads 时应删除并继续 exact match。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(("fact:ii:a_value",)),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        fact_types={"fact:ii:a_value": "symbol_value"},
        handle_valid_scopes={"fact:ii:a_value": "ii"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_ii_parabola",
                        "recipe_hint": "quadratic_from_constraints",
                        "goal_type": "derive_parabola",
                        "target": "fact:ii:parabola_expr",
                        "strategy": "读取含 scope 的 semantic read。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "a_value",
                                "scope": "ii",
                                "handle": "fact:ii:a_value",
                                "description": "catalog 展示字段",
                                "value_type": "symbol_value",
                            }
                        ],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:parabola_expr",
                                "valid_scope": "ii",
                                "description": "第（Ⅱ）问抛物线。",
                            }
                        ],
                        "reason": "extra fields 不应阻断 semantic read。",
                    }
                ],
            }
        ]
    }

    validator = StepIntentValidator()
    draft = validator.validate(payload, handle_registry=registry)

    assert draft.steps[0].reads == ("fact:ii:a_value",)
    report = validator.last_semantic_read_resolution_report
    assert report is not None
    assert report.ok is True
    assert report.warnings == (
        "semantic_read_extra_fields_ignored: "
        "scopes[0].steps[0].semantic_reads[0] ignored fields: description, handle, scope",
    )
    assert report.to_payload()["warnings"] == list(report.warnings)


def test_semantic_reads_extra_scope_does_not_disambiguate() -> None:
    """忽略 scope 后仍按原 exact match 规则处理歧义。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(("fact:problem:a_value", "fact:ii:a_value")),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        fact_types={
            "fact:problem:a_value": "symbol_value",
            "fact:ii:a_value": "symbol_value",
        },
        handle_valid_scopes={
            "fact:problem:a_value": "problem",
            "fact:ii:a_value": "ii",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "read_ambiguous_a_value",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:param",
                        "strategy": "scope extra field 不能参与消歧。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "a_value",
                                "scope": "ii",
                                "value_type": "symbol_value",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "仍应提示 ambiguous。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_ambiguous"):
        StepIntentValidator().validate(payload, handle_registry=registry)


def test_semantic_reads_does_not_fallback_to_invalid_legacy_reads() -> None:
    """legacy reads 不可见时，semantic_reads 错误仍应阻断。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:ii:N",)),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "use_invalid_legacy_reads",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "semantic 与 canonical 都错误。",
                        "reads": ["point:ii:Missing"],
                        "semantic_reads": [{"kind": "point", "ref": "missing_N"}],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 invalid fallback 不生效。",
                    },
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_unknown"):
        StepIntentValidator().validate(payload, handle_registry=registry)


def test_semantic_reads_accepts_canonical_dynamic_point_coordinate_alias() -> None:
    """DeepSeek 可在 semantic_reads.ref 中直接写动态坐标 fact handle。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_moving_point_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:moving_point_coordinate_expr",
                        "strategy": "构造 动点坐标。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:moving_point_coordinate_expr",
                                "valid_scope": "ii",
                                "description": "动点坐标表达式。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试动态坐标产物。",
                    },
                    {
                        "step_id": "read_moving_point_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "读取 动点坐标。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "fact:ii:moving_point_coordinate_expr",
                                "value_type": "point_coordinate",
                                "from_step": "construct_moving_point_coordinate",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 canonical ref + point_coordinate alias。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("fact:ii:moving_point_coordinate_expr",)


def test_semantic_reads_accepts_scoped_handle_shorthand_for_dynamic_fact() -> None:
    """DeepSeek 可用 kind + scope:name 读取前序动态 fact。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii", "ii_1")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem", "ii_1": "ii"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_parabola_relation_ii",
                        "recipe_hint": None,
                        "goal_type": "derive_parabola",
                        "target": "fact:ii:parabola_expression",
                        "strategy": "求含参抛物线。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:parabola_expression",
                                "valid_scope": "ii",
                                "description": "含参抛物线。",
                                "output_type": "Parabola",
                            }
                        ],
                        "reason": "测试动态 fact 产物。",
                    },
                    {
                        "step_id": "evaluate_parabola_ii1",
                        "recipe_hint": None,
                        "goal_type": "derive_parabola",
                        "target": "answer:ii_1.parabola",
                        "strategy": "代入参数求解析式。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "ii:parabola_expression",
                                "from_step": "derive_parabola_relation_ii",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 scope:name shorthand。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("fact:ii:parabola_expression",)


def test_semantic_reads_merges_same_handle_answer_goal_and_dynamic_output() -> None:
    """answer goal 与前序 produced answer 同 handle 时可读，但不推断来源。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(("answer:i.parabola",)),
        scope_parents={"problem": None, "i": "problem"},
        answer_value_types={"answer:i.parabola": "Parabola"},
        handle_valid_scopes={"answer:i.parabola": "i"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_parabola_i",
                        "recipe_hint": None,
                        "goal_type": "derive_parabola",
                        "target": "answer:i.parabola",
                        "strategy": "求抛物线。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "answer:i.parabola",
                                "valid_scope": "i",
                                "description": "第（Ⅰ）问抛物线。",
                                "output_type": "Parabola",
                            }
                        ],
                        "reason": "测试 answer 产物。",
                    },
                    {
                        "step_id": "read_parabola_i",
                        "recipe_hint": None,
                        "goal_type": "derive_axis_point",
                        "target": "answer:i.axis_point",
                        "strategy": "读取刚求出的抛物线。",
                        "semantic_reads": [
                            {
                                "kind": "answer",
                                "ref": "i.parabola",
                                "value_type": "Parabola",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "不需要 from_step。",
                    },
                ],
            }
        ]
    }

    validator = StepIntentValidator()
    draft = validator.validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == ("answer:i.parabola",)
    assert validator.last_semantic_read_resolution_report is not None
    resolution = validator.last_semantic_read_resolution_report.resolutions[-1]
    assert resolution.candidate_count == 2
    assert resolution.inferred_from_step is None


def test_semantic_reads_rejects_non_coordinate_dynamic_point_alias() -> None:
    """非坐标类动态 Point fact 不能冒充 point_coordinate。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_candidate",
                        "recipe_hint": None,
                        "goal_type": "derive_constructed_point",
                        "target": "fact:ii:selected_N",
                        "strategy": "构造候选点。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:selected_N",
                                "valid_scope": "ii",
                                "description": "选中的候选点。",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试非坐标产物。",
                    },
                    {
                        "step_id": "read_candidate_as_coordinate",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "错误读取候选点为坐标 fact。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "selected_N",
                                "value_type": "point_coordinate",
                                "from_step": "construct_candidate",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试 alias 不应过宽。",
                    },
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError) as exc_info:
        StepIntentValidator().validate(payload, handle_registry=registry)

    message = str(exc_info.value)
    assert "semantic_read_unknown" in message
    assert "available_value_types=['Point']" in message


def test_semantic_reads_collects_all_resolution_errors() -> None:
    """semantic read 解析应聚合同轮错误，并保留已成功解析项。"""
    payload = _valid_step_intent_payload()
    step = payload["scopes"][0]["steps"][0]
    step.pop("reads", None)
    step["semantic_reads"] = [
        {"kind": "function", "ref": "parabola"},
        {"kind": "fact", "ref": "missing_relation"},
        {
            "kind": "fact",
            "ref": "coefficient_relation",
            "value_type": "symbol_value",
        },
    ]

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft is None
    assert report.ok is False
    assert report.errors
    assert "semantic_read_errors: count=1" in report.errors[0]
    assert report.semantic_read_resolution is not None
    semantic_report = report.semantic_read_resolution
    assert semantic_report.ok is False
    assert [item.handle for item in semantic_report.resolutions] == [
        "function:problem:parabola",
        "fact:problem:coefficient_relation",
    ]
    assert [item.code for item in semantic_report.errors] == ["semantic_read_unknown"]
    assert [
        item.semantic_ref.to_payload() if item.semantic_ref else None
        for item in semantic_report.errors
    ] == [{"kind": "fact", "ref": "missing_relation"}]
    partial = semantic_report.partially_resolved_payload
    assert partial is not None
    partial_step = partial["scopes"][0]["steps"][0]
    assert partial_step["reads"] == [
        "function:problem:parabola",
        "fact:problem:coefficient_relation",
    ]
    assert "semantic_reads" not in partial_step
    serialized_report = report.to_payload()
    assert (
        serialized_report["semantic_read_resolution"]["partially_resolved_payload"]
        ["scopes"][0]["steps"][0]["reads"]
        == ["function:problem:parabola", "fact:problem:coefficient_relation"]
    )


def test_semantic_reads_rejects_canonical_ref_kind_mismatch() -> None:
    """canonical handle 的 namespace 必须与 semantic kind 一致。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0].pop("reads", None)
    payload["scopes"][0]["steps"][0]["semantic_reads"] = [
        {
            "kind": "point",
            "ref": "fact:problem:coefficient_relation",
            "value_type": "coefficient_relation",
        },
    ]

    with pytest.raises(
        StrategyDraftValidationError,
        match="semantic_read_kind_mismatch",
    ):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_semantic_reads_require_handle_registry() -> None:
    """非空 semantic_reads 没有 registry 时应 fail fast。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0].pop("reads")
    payload["scopes"][0]["steps"][0]["semantic_reads"] = [
        {"kind": "function", "ref": "parabola"},
    ]

    with pytest.raises(
        StrategyDraftValidationError,
        match="semantic_reads_require_handle_registry",
    ):
        StepIntentValidator().validate_json(json.dumps(payload, ensure_ascii=False))


def test_semantic_reads_rejects_malformed_array_even_without_reads() -> None:
    """semantic_reads 写错类型时不能被当成空 reads 接受。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0].pop("reads")
    payload["scopes"][0]["steps"][0]["semantic_reads"] = {"kind": "function"}

    with pytest.raises(
        StrategyDraftValidationError,
        match="semantic_reads must be an object array",
    ):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_semantic_reads_malformed_array_does_not_require_handle_registry_first() -> None:
    """错误类型的 semantic_reads 应由 validator 报结构错误，而不是误触发 resolver。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0].pop("reads")
    payload["scopes"][0]["steps"][0]["semantic_reads"] = {"kind": "function"}

    with pytest.raises(
        StrategyDraftValidationError,
        match="semantic_reads must be an object array",
    ):
        StepIntentValidator().validate_json(json.dumps(payload, ensure_ascii=False))


def test_semantic_read_resolver_rejects_unknown_ref() -> None:
    """semantic ref 必须 exact match catalog，不做猜测。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0].pop("reads", None)
    payload["scopes"][0]["steps"][0]["semantic_reads"] = [
        {"kind": "fact", "ref": "missing_relation"},
    ]

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_unknown"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_semantic_read_resolver_treats_value_type_as_hint_for_unique_ref() -> None:
    """ref/kind 已唯一时，value_type 口径差异不应阻断 semantic read。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0].pop("reads", None)
    payload["scopes"][0]["steps"][0]["semantic_reads"] = [
        {
            "kind": "fact",
            "ref": "coefficient_relation",
            "value_type": "symbol_value",
        },
    ]

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft.steps[0].reads == ("fact:problem:coefficient_relation",)


def test_semantic_reads_accept_runtime_value_type_aliases_for_dynamic_outputs() -> None:
    """LLM 语义类型应能匹配 runtime canonical output types。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "produce_runtime_values",
                        "recipe_hint": None,
                        "goal_type": "derive_runtime_values",
                        "target": "fact:ii:runtime_values",
                        "strategy": "产生多类 runtime outputs。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:m_value",
                                "valid_scope": "ii",
                                "description": "参数 m。",
                                "output_type": "ParameterValue",
                            },
                            {
                                "handle": "fact:ii:single_moving_path_equivalence",
                                "valid_scope": "ii",
                                "description": "路径降维结果。",
                                "output_type": "PathTransformation",
                            },
                            {
                                "handle": "fact:ii:straightened_path_choice",
                                "valid_scope": "ii",
                                "description": "折线拉直方案。",
                                "output_type": "StraighteningCandidate",
                            },
                            {
                                "handle": "fact:ii:path_minimum_expression",
                                "valid_scope": "ii",
                                "description": "路径最小值表达式。",
                                "output_type": "MinimumExpression",
                            },
                        ],
                        "reason": "测试。",
                    },
                    {
                        "step_id": "read_runtime_values",
                        "recipe_hint": None,
                        "goal_type": "derive_next",
                        "target": "fact:ii:next",
                        "strategy": "使用 LLM 语义类型读取 runtime outputs。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "m_value",
                                "value_type": "symbol_value",
                            },
                            {
                                "kind": "fact",
                                "ref": "single_moving_path_equivalence",
                                "value_type": "transformation",
                            },
                            {
                                "kind": "fact",
                                "ref": "straightened_path_choice",
                                "value_type": "straighteningCandidate",
                            },
                            {
                                "kind": "fact",
                                "ref": "path_minimum_expression",
                                "value_type": "minimum_expression",
                            },
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[1].reads == (
        "fact:ii:m_value",
        "fact:ii:single_moving_path_equivalence",
        "fact:ii:straightened_path_choice",
        "fact:ii:path_minimum_expression",
    )


def test_semantic_read_resolver_rejects_invisible_scope() -> None:
    """子问独有 fact 不能被 sibling scope 读取。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii", "ii_1", "ii_2")),
        entity_handles=frozenset(),
        fact_handles=frozenset(("fact:ii_1:child_only",)),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem", "ii_1": "ii", "ii_2": "ii"},
        fact_types={"fact:ii_1:child_only": "symbol_value"},
        handle_valid_scopes={"fact:ii_1:child_only": "ii_1"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "read_sibling_fact",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:value",
                        "strategy": "测试 sibling scope 不可见。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "child_only",
                                "value_type": "symbol_value",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_unknown"):
        StepIntentValidator().validate(payload, handle_registry=registry)


def test_semantic_read_resolver_rejects_invisible_canonical_scope() -> None:
    """写 canonical handle 也不能绕过 sibling scope 可见性。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii", "ii_1", "ii_2")),
        entity_handles=frozenset(),
        fact_handles=frozenset(("fact:ii_1:child_only",)),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem", "ii_1": "ii", "ii_2": "ii"},
        fact_types={"fact:ii_1:child_only": "symbol_value"},
        handle_valid_scopes={"fact:ii_1:child_only": "ii_1"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "read_sibling_fact",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:value",
                        "strategy": "测试 sibling scope 不可见。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "fact:ii_1:child_only",
                                "value_type": "symbol_value",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_unknown"):
        StepIntentValidator().validate(payload, handle_registry=registry)


def test_semantic_read_resolver_rejects_ambiguous_missing_from_step() -> None:
    """漏写 from_step 且命中多个前序产物时，应要求 LLM 消歧。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii", "ii_1")),
        entity_handles=frozenset(),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem", "ii_1": "ii"},
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_problem_shared",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:problem:shared_value",
                        "strategy": "产生全题 shared_value。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:problem:shared_value",
                                "valid_scope": "problem",
                                "description": "全题 shared_value。",
                                "output_type": "Equation",
                            }
                        ],
                        "reason": "测试。",
                    },
                    {
                        "step_id": "derive_ii_shared",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:shared_value",
                        "strategy": "产生第（Ⅱ）问 shared_value。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:shared_value",
                                "valid_scope": "ii",
                                "description": "第（Ⅱ）问 shared_value。",
                                "output_type": "Equation",
                            }
                        ],
                        "reason": "测试。",
                    },
                    {
                        "step_id": "read_shared",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii_1:result",
                        "strategy": "漏写 from_step 造成歧义。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "shared_value",
                                "value_type": "Equation",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    },
                ],
            }
        ]
    }

    with pytest.raises(
        StrategyDraftValidationError,
        match="semantic_read_ambiguous_missing_from_step",
    ) as exc_info:
        StepIntentValidator().validate(payload, handle_registry=registry)

    message = str(exc_info.value)
    assert "derive_problem_shared" in message
    assert "derive_ii_shared" in message


def test_semantic_read_resolver_rejects_ambiguous_ref() -> None:
    """同一 scope 可见多个 exact match 时必须让 LLM 消歧。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i")),
        entity_handles=frozenset(),
        fact_handles=frozenset(("fact:problem:shared", "fact:i:shared")),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "i": "problem"},
        fact_types={
            "fact:problem:shared": "Equation",
            "fact:i:shared": "Equation",
        },
        handle_valid_scopes={
            "fact:problem:shared": "problem",
            "fact:i:shared": "i",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "read_shared",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:i:result",
                        "strategy": "测试歧义。",
                        "semantic_reads": [
                            {
                                "kind": "fact",
                                "ref": "shared",
                                "value_type": "Equation",
                            }
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="semantic_read_ambiguous"):
        StepIntentValidator().validate(payload, handle_registry=registry)


def test_semantic_read_resolver_reports_missing_scope_prefix_for_entities() -> None:
    """同名 entity 已被 scope 前缀消歧时，漏写前缀应报更具体错误。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:problem:A", "point:ii:A")),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        handle_valid_scopes={
            "point:problem:A": "problem",
            "point:ii:A": "ii",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "read_A_without_scope",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "测试 scope 前缀缺失。",
                        "semantic_reads": [{"kind": "point", "ref": "A"}],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(
        StrategyDraftValidationError,
        match="semantic_read_ambiguous_missing_scope_prefix",
    ) as exc_info:
        StepIntentValidator().validate(payload, handle_registry=registry)

    message = str(exc_info.value)
    assert "problem.A" in message
    assert "ii.A" in message


def test_semantic_read_resolver_accepts_scope_prefixed_entity_refs() -> None:
    """scope 前缀后的 entity ref 应能解析回对应 canonical handles。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset(("point:problem:A", "point:ii:A")),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        handle_valid_scopes={
            "point:problem:A": "problem",
            "point:ii:A": "ii",
        },
    )
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "read_scope_prefixed_A",
                        "recipe_hint": None,
                        "goal_type": "derive_relation",
                        "target": "fact:ii:result",
                        "strategy": "测试 scope 前缀。",
                        "semantic_reads": [
                            {"kind": "point", "ref": "problem.A"},
                            {"kind": "point", "ref": "ii.A"},
                        ],
                        "creates": [],
                        "produces": [],
                        "reason": "测试。",
                    }
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    assert draft.steps[0].reads == ("point:problem:A", "point:ii:A")


def test_recorded_step_intents_round_trip_through_semantic_reads() -> None:
    """真实 recorded StepIntent 的 reads 可机械转换为 semantic_reads 并还原。"""
    cases = (
        (NANKAI_FIXTURE, NANKAI_EXECUTABLE_STEP_INTENTS),
        (HEXI_FIXTURE, _repo_root() / "internal/solver-fixtures/tj-2026-hexi-yimo-25.executable-step-intents.json"),
        (XIQING_FIXTURE, _repo_root() / "internal/solver-fixtures/tj-2026-xiqing-yimo-25.executable-step-intents.json"),
        (HEPING_FIXTURE, _repo_root() / "internal/solver-fixtures/tj-2026-heping-yimo-25.executable-step-intents.json"),
        (HEPING_ERMO_FIXTURE, HEPING_ERMO_EXECUTABLE_STEP_INTENTS),
    )

    for problem_fixture, step_intent_path in cases:
        problem = load_problem_ir(problem_fixture)
        registry = CanonicalHandleRegistry.from_problem_payload(
            problem_to_llm_payload(problem)
        )
        raw = json.loads(Path(step_intent_path).read_text(encoding="utf-8"))
        legacy_draft = StepIntentValidator().validate(raw, handle_registry=registry)
        semantic_payload = _payload_with_semantic_reads(
            legacy_draft.to_payload(),
            registry,
        )
        semantic_draft = StepIntentValidator().validate(
            semantic_payload,
            handle_registry=registry,
        )

        assert [
            step.reads for step in semantic_draft.steps
        ] == [
            step.reads for step in legacy_draft.steps
        ]
