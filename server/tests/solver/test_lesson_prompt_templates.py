"""Family context is optional, source-bound and separate from execution authority."""

# Imported pytest fixtures are injected as test parameters.
# ruff: noqa: F811
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from jinja2 import TemplateNotFound, UndefinedError
from test_basic_inequality_lesson import snapshot  # noqa: F401
from test_basic_inequality_lesson_expansion import snapshots  # noqa: F401

from shuxueshuo_server.solver.explanation import lesson_prompt
from shuxueshuo_server.solver.explanation.amgm_sequence_rule import (
    sequence_rule_registry,
)
from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.family import (
    BASIC_INEQUALITY_FAMILY,
    DEFAULT_FAMILY_REGISTRY,
)


def prompt_for(snapshot):
    projection = AnnotatedTeachingPlanProjector(rule_registry=sequence_rule_registry()).project(snapshot)
    return projection, render_annotated_teaching_prompt(projection.plan, authority=projection.authority)


def context_section(prompt, heading):
    return json.loads(prompt.user.split(heading + "\n\n", 1)[1].split("\n\n## ", 1)[0])


@pytest.mark.parametrize("case", ["q03", "q07", "q08"])
def test_minimum_context_has_catalog_and_verified_route(case, snapshots):
    projection, prompt = prompt_for(snapshots[case])
    catalog = context_section(prompt, "## Family 解题思路目录（理解背景，不代表本题已执行）")
    assert len(catalog["methods"]) == 6
    assert {m["name"] for m in catalog["methods"]} >= {"换元法", "配齐次式", "直接应用基本不等式"}
    routes = context_section(prompt, "## 本题已验证路线（只解释对应容器的材料，不新增数学事实）")
    assert len(routes) == 1
    route = routes[0]
    assert route["scope_ref"] == "problem" and route["goal_ref"] == "problem.minimum"
    assert [s["source_steps"][0] for s in route["steps"]] == [
        r["teaching_step_ref"] for r in projection.authority["containers"]["goal:problem.minimum"]
    ]
    assert "求最大值" not in prompt.user and "upper_bound" not in prompt.user
    assert "求最小值" in prompt.user
    assert '"direction":"≥"' in prompt.user
    if case == "q07":
        assert "消去 a" in route["steps"][1]["purpose"]
        assert route["steps"][2]["title"] == "再次应用基本不等式取极值"
    if case == "q03":
        assert any(s.get("approach") == "配齐次式" for s in route["steps"])
    assert "不得改为“设取”" in prompt.system


def test_maximum_also_receives_family_template_and_ignores_problem_number(snapshot):
    _, prompt = prompt_for(snapshot)
    _, renamed = prompt_for(replace(snapshot, problem_id="unrelated-problem-id"))
    assert prompt.messages == renamed.messages
    assert "求上界" in prompt.system and "求最大值" in prompt.user
    assert r"数学表达式使用 \( ... \)" in prompt.system
    assert r"根式使用 LaTeX \sqrt{...}" in prompt.system
    assert "JSON 字符串转义示例" in prompt.system
    assert "共享示例仅示范字段与步骤合并" in prompt.system
    assert '"direction":"≤"' in prompt.user
    assert {asset["id"] for asset in prompt.assets} == {
        "system-v1.jinja", "shared-v1.jinja", "user-v1.jinja",
        "shared-example-v1.jinja", "boundaries-v1.jinja",
        "basic-inequality-v1.jinja", BASIC_INEQUALITY_FAMILY.strategy_reference,
    }
    assert BASIC_INEQUALITY_FAMILY not in DEFAULT_FAMILY_REGISTRY.families


def test_quadratic_uses_shared_template_even_with_bound_direction():
    path = Path(__file__).parent / "fixtures/lesson_scope_authoring_vnext/heping_ermo_b1/snapshot.json"
    value = explanation_snapshot_from_payload(json.loads(path.read_text()))
    projection, prompt = prompt_for(value)
    authority = deepcopy(projection.authority)
    for rows in authority["containers"].values():
        for row in rows:
            row["bound_direction"] = ">="
    same = render_annotated_teaching_prompt(projection.plan, authority=authority)
    assert same.messages == prompt.messages
    assert {asset["id"] for asset in prompt.assets} == {
        "system-v1.jinja", "shared-v1.jinja", "user-v1.jinja",
        "shared-example-v1.jinja", "boundaries-v1.jinja",
    }
    assert "Family 解题思路目录" not in prompt.user
    assert "联立求解推导" not in prompt.system
    assert "JSON 字符串转义示例" not in prompt.system
    assert "数学表达式使用" not in prompt.system
    assert r"\frac" not in prompt.system
    assert "根式写“√”" in prompt.system
    assert '"derive":["∴ m＝4"]' in prompt.system


def test_template_content_changes_are_audited_not_blocked(tmp_path, monkeypatch, snapshot):
    for template in lesson_prompt.TEMPLATE_ROOT.glob("*.jinja"):
        (tmp_path / template.name).write_bytes(template.read_bytes())
    monkeypatch.setattr(lesson_prompt, "TEMPLATE_ROOT", tmp_path)
    _, before = prompt_for(snapshot)
    shared = tmp_path / "shared-v1.jinja"
    shared.write_text(shared.read_text() + "\n请保持讲解简洁。\n")
    _, after = prompt_for(snapshot)
    assert after.system != before.system
    assets_before = {asset["id"]: asset["sha256"] for asset in before.assets}
    assets_after = {asset["id"]: asset["sha256"] for asset in after.assets}
    assert assets_after[shared.name] == sha256(shared.read_bytes()).hexdigest()
    assert assets_before[shared.name] != assets_after[shared.name]


def test_declared_missing_template_is_configuration_error(snapshot):
    projection, _ = prompt_for(snapshot)
    family = replace(BASIC_INEQUALITY_FAMILY, teaching_template="missing-template.jinja")
    with pytest.raises(TemplateNotFound):
        lesson_prompt.render_lesson_prompt(
            projection.plan.to_payload(), projection.authority,
            output_schema={}, boundaries={"independent": [], "mergeable": []},
            families={family.family_id: family},
        )


def test_template_variables_fail_closed(tmp_path, monkeypatch, snapshot):
    for template in lesson_prompt.TEMPLATE_ROOT.glob("*.jinja"):
        (tmp_path / template.name).write_bytes(template.read_bytes())
    (tmp_path / "basic-inequality-v1.jinja").write_text("{{ missing_teaching_variable }}")
    monkeypatch.setattr(lesson_prompt, "TEMPLATE_ROOT", tmp_path)
    with pytest.raises(UndefinedError, match="missing_teaching_variable"):
        prompt_for(snapshot)


def test_jinja_data_is_json_serialized_without_html_escape_or_template_execution():
    text = '{{ 7 * 7 }} {% include "missing.jinja" %} x<y \\(\\frac{x}{y}\\) "值"'
    payload = {"root_scope": {"scope_ref": "problem"}, "text": text}
    _, user, assets = lesson_prompt.render_lesson_prompt(
        payload, {}, output_schema={"const": text},
        boundaries={"independent": [], "mergeable": []},
    )
    assert json.loads(user.split("## Annotated Teaching Plan\n\n")[1]) == payload
    schema = json.loads(user.split("## 输出 JSON Schema\n\n")[1].split("\n\n## ")[0])
    assert schema == {"const": text}
    assert "&lt;" not in user and "&quot;" not in user
    assert "## 必须独立" not in user and "## 可考虑合并" not in user
    assert {a["id"] for a in assets} == {
        "system-v1.jinja", "shared-v1.jinja", "user-v1.jinja", "shared-example-v1.jinja",
    }


@pytest.mark.parametrize("independent,mergeable", [(True, False), (False, True), (True, True)])
def test_jinja_boundary_sections_are_conditional(independent, mergeable):
    boundaries = {
        "independent": [{"owner_kind": "Goal", "owner_ref": "i.value", "refs": ["s1", "s2"]}]
        if independent else [],
        "mergeable": [{"owner_kind": "Scope", "owner_ref": "ii", "runs": [["s3", "s4"], ["s6", "s7"]]}]
        if mergeable else [],
    }
    _, user, _ = lesson_prompt.render_lesson_prompt(
        {"root_scope": {}}, {}, output_schema={}, boundaries=boundaries,
    )
    assert ("## 必须独立的教学材料" in user) == independent
    assert ("## 可考虑合并的连续材料" in user) == mergeable
    if independent:
        assert '- Goal i.value：必须分别输出 ["s1"]、["s2"]' in user
    if mergeable:
        assert '- Scope ii：["s3","s4"]、["s6","s7"]' in user


def test_route_references_stay_in_owner_container():
    material = {"step_ref": "s1", "title": "计算", "goal": "完成当前计算"}
    payload = {"root_scope": {"scope_ref": "problem", "children": [
        {"scope_ref": owner, "goals": {f"{owner}.value": [{"materials": [material]}]}}
        for owner in ("i", "ii")
    ]}}
    authority = {"containers": {f"goal:{owner}.value": [{"teaching_step_ref": "s1"}]
                                 for owner in ("i", "ii")}}
    routes = lesson_prompt._routes(payload, authority)
    assert [(r["scope_ref"], r["goal_ref"]) for r in routes] == [("i", "i.value"), ("ii", "ii.value")]
    authority["containers"]["goal:i.value"][0]["teaching_step_ref"] = "s2"
    with pytest.raises(ValueError, match="reference_mismatch"):
        lesson_prompt._routes(payload, authority)
