from __future__ import annotations

import json
from pathlib import Path
from copy import deepcopy

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.strategy_few_shots import (
    build_few_shot_entry,
    goal_types_from_scopes,
    load_few_shot_entries,
    query_goal_types_from_problem,
    select_few_shot_examples,
    validate_few_shot_entry,
    write_few_shot_entry,
)
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
)


def test_build_few_shot_entry_preserves_executable_scopes() -> None:
    """few-shot 应原样投射 executable StepIntent 的 scope 分组和 step 字段。"""
    problem_payload = _problem_payload("tj-2026-nankai-yimo-25")
    executable_payload = _json_fixture("tj-2026-nankai-yimo-25.executable-step-intents.json")

    entry = build_few_shot_entry(
        problem_payload=problem_payload,
        executable_step_intents=executable_payload,
        family_id="QuadraticPathMinimumSolver",
    )

    assert set(entry) == {
        "problem_id",
        "family_id",
        "title",
        "original_text",
        "retrieval",
        "example",
    }
    assert entry["problem_id"] == "tj-2026-nankai-yimo-25"
    assert entry["original_text"] == problem_payload["original_text"]
    assert entry["example"]["scopes"] == executable_payload["scopes"]
    assert entry["retrieval"]["goal_types"] == goal_types_from_scopes(
        executable_payload["scopes"]
    )

    serialized = json.dumps(entry, ensure_ascii=False)
    assert "schema_version" not in serialized
    assert "source" not in serialized
    assert "expected" not in serialized
    assert "$problem" not in serialized
    assert "$question" not in serialized


def test_few_shot_selector_uses_family_goal_overlap_and_top_one(tmp_path: Path) -> None:
    """selector 首版只返回同 family 中 goal_type 重叠最高的一个条目。"""
    nankai = build_few_shot_entry(
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
        executable_step_intents=_json_fixture("tj-2026-nankai-yimo-25.executable-step-intents.json"),
        family_id="QuadraticPathMinimumSolver",
    )
    weak = deepcopy(nankai)
    weak["problem_id"] = "weak-example"
    weak["example"]["scopes"] = [
        {
            **weak["example"]["scopes"][0],
            "steps": [weak["example"]["scopes"][0]["steps"][1]],
        }
    ]
    weak["retrieval"] = {"goal_types": goal_types_from_scopes(weak["example"]["scopes"])}
    other_family = {
        **nankai,
        "problem_id": "other-family",
        "family_id": "OtherFamily",
    }
    write_few_shot_entry(weak, tmp_path / "weak-example.few-shot.json")
    write_few_shot_entry(nankai, tmp_path / "tj-2026-nankai-yimo-25.few-shot.json")
    write_few_shot_entry(other_family, tmp_path / "other-family.few-shot.json")

    selected = select_few_shot_examples(
        family_id="QuadraticPathMinimumSolver",
        goal_types=("derive_parabola", "straighten_broken_path", "derive_parameter"),
        problem_id="new-problem",
        few_shot_dir=tmp_path,
    )

    assert [entry["problem_id"] for entry in selected] == ["tj-2026-nankai-yimo-25"]


def test_few_shot_selector_can_exclude_same_problem(tmp_path: Path) -> None:
    """测试链路可排除当前题，生产链路默认不排除。"""
    nankai = build_few_shot_entry(
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
        executable_step_intents=_json_fixture("tj-2026-nankai-yimo-25.executable-step-intents.json"),
        family_id="QuadraticPathMinimumSolver",
    )
    write_few_shot_entry(nankai, tmp_path / "tj-2026-nankai-yimo-25.few-shot.json")

    production = select_few_shot_examples(
        family_id="QuadraticPathMinimumSolver",
        goal_types=("derive_axis_point",),
        problem_id="tj-2026-nankai-yimo-25",
        allow_same_problem=True,
        few_shot_dir=tmp_path,
    )
    test_mode = select_few_shot_examples(
        family_id="QuadraticPathMinimumSolver",
        goal_types=("derive_axis_point",),
        problem_id="tj-2026-nankai-yimo-25",
        allow_same_problem=False,
        few_shot_dir=tmp_path,
    )

    assert [entry["problem_id"] for entry in production] == ["tj-2026-nankai-yimo-25"]
    assert test_mode == []


def test_strategy_payload_builder_uses_dynamic_few_shot_selector(tmp_path: Path) -> None:
    """未显式注入 few-shot 时，payload builder 应读取 selector 结果。"""
    entry = build_few_shot_entry(
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
        executable_step_intents=_json_fixture("tj-2026-nankai-yimo-25.executable-step-intents.json"),
        family_id="QuadraticPathMinimumSolver",
    )
    write_few_shot_entry(entry, tmp_path / "tj-2026-nankai-yimo-25.few-shot.json")

    payload = StrategyPayloadBuilder(few_shot_dir=tmp_path).build(
        _nankai_inputs(),
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
    )
    explicit = StrategyPayloadBuilder(
        few_shot_examples=[{"family_id": "fake", "scopes": []}],
        few_shot_dir=tmp_path,
    ).build(
        _nankai_inputs(),
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
    )

    assert payload["few_shot_examples"][0]["problem_id"] == "tj-2026-nankai-yimo-25"
    assert "example" in payload["few_shot_examples"][0]
    assert explicit["few_shot_examples"] == [{"family_id": "fake", "scopes": []}]


def test_runtime_config_passes_same_problem_few_shot_policy_to_strategy_provider() -> None:
    """真实集成测试可通过 runtime config 排除当前题 few-shot。"""
    problem = load_problem_ir("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json")
    context = ContextBuilder().build(problem)
    config = SolverRuntimeConfig(
        planner_mode="strategy",
        llm_provider="recorded",
        allow_same_problem_few_shot=False,
    )
    provider = config.build_default_planner_provider()

    assert provider is not None
    planner = provider(context)
    assert planner.payload_builder.allow_same_problem_few_shot is False


def test_query_goal_types_are_derived_from_current_problem_goals() -> None:
    """few-shot 检索应使用当前题目标，而不是 family common_goal_types。"""
    nankai_goals = query_goal_types_from_problem(
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25")
    )
    hexi_goals = query_goal_types_from_problem(
        problem_payload=_problem_payload("tj-2026-hexi-yimo-25")
    )

    assert nankai_goals == [
        "derive_axis_point",
        "derive_parabola",
        "derive_minimum_value",
        "derive_extremal_point",
    ]
    assert hexi_goals == [
        "derive_vertex_point",
        "derive_constructed_point",
        "derive_parameter",
    ]
    assert "reduce_path_expression" not in nankai_goals
    assert "derive_weighted_path_minimum" not in hexi_goals


def test_payload_selector_ranks_by_current_problem_goal_types(tmp_path: Path) -> None:
    """payload selector 不应退回 family common_goal_types 做检索。"""
    base = build_few_shot_entry(
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
        executable_step_intents=_json_fixture("tj-2026-nankai-yimo-25.executable-step-intents.json"),
        family_id="QuadraticPathMinimumSolver",
    )
    current_goal_match = deepcopy(base)
    current_goal_match["problem_id"] = "current-goal-match"
    current_goal_match["example"]["scopes"] = [
        {
            **base["example"]["scopes"][0],
            "steps": [base["example"]["scopes"][0]["steps"][1]],
        }
    ]
    current_goal_match["retrieval"] = {
        "goal_types": goal_types_from_scopes(current_goal_match["example"]["scopes"])
    }
    family_only_match = deepcopy(base)
    family_only_match["problem_id"] = "family-only-match"
    family_only_match["example"]["scopes"] = [
        {
            "scope_id": "fake",
            "steps": [
                {
                    "step_id": "reduce_path",
                    "recipe_hint": "two_moving_points_path_reduction",
                    "goal_type": "reduce_path_expression",
                    "target": "fact:fake:path",
                    "reads": [],
                    "creates": [],
                    "produces": [],
                    "strategy": "",
                    "reason": "",
                }
            ],
        }
    ]
    family_only_match["retrieval"] = {
        "goal_types": goal_types_from_scopes(family_only_match["example"]["scopes"])
    }
    write_few_shot_entry(family_only_match, tmp_path / "family-only-match.few-shot.json")
    write_few_shot_entry(current_goal_match, tmp_path / "current-goal-match.few-shot.json")

    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(
        _nankai_inputs(),
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
    )

    assert payload["few_shot_examples"][0]["problem_id"] == "current-goal-match"


def test_strategy_payload_builder_falls_back_to_virtual_few_shot(tmp_path: Path) -> None:
    """没有同 family 条目时，保留现有虚构 few-shot 兜底。"""
    payload = StrategyPayloadBuilder(few_shot_dir=tmp_path).build(
        _nankai_inputs(),
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
    )

    assert payload["few_shot_examples"][0]["problem_id"].startswith("fallback-")
    assert payload["few_shot_examples"][0]["note"].startswith("这是虚构简化场景")
    assert "example" in payload["few_shot_examples"][0]


def test_prompt_distinguishes_current_problem_and_few_shot_example(tmp_path: Path) -> None:
    """prompt 必须明确区分当前题和示例题，避免示例原文被当成当前条件。"""
    entry = build_few_shot_entry(
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
        executable_step_intents=_json_fixture("tj-2026-nankai-yimo-25.executable-step-intents.json"),
        family_id="QuadraticPathMinimumSolver",
    )
    write_few_shot_entry(entry, tmp_path / "tj-2026-nankai-yimo-25.few-shot.json")
    payload = StrategyPayloadBuilder(few_shot_dir=tmp_path).build(
        _nankai_inputs(),
        problem_payload=_problem_payload("tj-2026-nankai-yimo-25"),
    )

    prompt = StrategyPromptRenderer().render(payload)

    assert "## 当前题目 ProblemIR JSON" in prompt.user
    assert "## 示例题目 Few-shot" in prompt.user
    assert "不是当前题条件" in prompt.user
    assert "example.scopes[].steps[]" in prompt.user


def test_generated_few_shot_files_are_valid() -> None:
    """首批南开、河西 few-shot 文件应符合 V1 结构。"""
    entries = load_few_shot_entries(few_shot_dir=repo_root(Path(__file__)) / "internal" / "few-shots")
    by_id = {entry["problem_id"]: entry for entry in entries}

    assert set(by_id) >= {
        "tj-2026-nankai-yimo-25",
        "tj-2026-hexi-yimo-25",
    }
    for entry in by_id.values():
        validate_few_shot_entry(entry)
        assert entry["retrieval"]["goal_types"] == goal_types_from_scopes(
            entry["example"]["scopes"]
        )


def _nankai_inputs():
    """构建南开 Strategy probe 输入。"""
    return build_strategy_probe_inputs(
        load_problem_ir("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json")
    )


def _json_fixture(name: str) -> dict:
    """读取 solver fixture JSON object。"""
    return json.loads((repo_root(Path(__file__)) / "internal" / "solver-fixtures" / name).read_text(encoding="utf-8"))


def _problem_payload(problem_id: str) -> dict:
    """从 canonical ProblemIR 投影 few-shot 使用的 LLM payload。"""
    return problem_to_llm_payload(
        load_problem_ir(
            repo_root(Path(__file__))
            / "internal"
            / "solver-fixtures"
            / f"{problem_id}.json"
        )
    )
