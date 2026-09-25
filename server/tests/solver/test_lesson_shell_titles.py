"""Extracted question markers must become descriptive, scope-aware titles."""
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.visual.lesson_shell import (
    _question_target_for_section,
    _section_marker_from_title,
    _section_titles_for_lesson,
    lesson_data_from_lesson_ir,
)


@pytest.mark.parametrize("label", ["(I)", "（Ⅰ）", "(i)", "第（Ⅰ）问"])
def test_parent_marker_spellings(label):
    assert _section_marker_from_title(label) == ("Ⅰ", "")
    assert _question_target_for_section(
        title=label, scope_id="unrelated_id", problem_lines=[
            "(I) 当 a=2 时，直接写出点 D 的坐标和函数解析式；",
            "(II) 求另一结果。",
        ],
    ) == "写出点 D 的坐标和函数解析式"


@pytest.mark.parametrize("parent_label", ["(II)", "（Ⅱ）", "第（Ⅱ）问"])
def test_extracted_titles_reach_both_cards_and_navigation(parent_label):
    scopes = [
        {"scope_id": "first", "label": "(I)", "parent": "problem"},
        {"scope_id": "second", "label": parent_label, "parent": "problem"},
        {"scope_id": "child_a", "label": "①", "parent": "second"},
        {"scope_id": "child_b", "label": "②", "parent": "second"},
    ]
    steps = [SimpleNamespace(
        id=f"teach:{s['scope_id']}", scope_id=s["scope_id"], title="计算",
        nav_title="求值", derive=[], box=[],
    ) for s in scopes]
    lesson = SimpleNamespace(
        problem_id="uploaded", steps=steps,
        sections=[SimpleNamespace(scope_id=s["scope_id"], title=s["label"], steps=[step.id])
                  for s, step in zip(scopes, steps)],
    )
    snapshot = SimpleNamespace(problem={"scopes": scopes})
    base = {"problem": {"lines": [
        "(I) 当 a=2 时，直接写出点 D 的坐标和函数解析式；",
        "(II) 若 M、N 在函数图像上，且 MN=DM。",
        "① 当 MN=√10 时，求函数解析式，并直接写出路径最小值；",
        "② 当路径最小值为 5 时，写出函数解析式和点 G 的坐标。",
    ]}}
    result = lesson_data_from_lesson_ir(lesson, base, snapshot=snapshot)
    expected = {
        "first": "第（Ⅰ）问：写出点 D 的坐标和函数解析式",
        "second": "第（Ⅱ）问：公共推导",
        "child_a": "第（Ⅱ）①问：求函数解析式，并直接写出路径最小值",
        "child_b": "第（Ⅱ）②问：写出函数解析式和点 G 的坐标",
    }
    for step, scope in zip(result["steps"], scopes):
        title = expected[scope["scope_id"]]
        assert step["section"] == title
        assert result["ui"]["groupTitles"][scope["scope_id"]] == title
        assert result["ui"]["groupTitles"][title] == title
    assert "ui" not in base


def test_descriptive_title_is_not_rewritten():
    title = "第（Ⅱ）问：已有完整的教学目标"
    lesson = SimpleNamespace(sections=[SimpleNamespace(
        scope_id="ii", title=title, steps=[],
    )], steps=[])
    assert _section_titles_for_lesson(lesson, {}) == {"ii": title}


def test_teaching_section_label_preserves_subquestion_identity():
    step = SimpleNamespace(id="step", scope_id="ii", title="计算", nav_title="计算",
                           derive=[], box=[], section_label="多次应用基本不等式")
    lesson = SimpleNamespace(problem_id="p", steps=[step], sections=[SimpleNamespace(
        scope_id="ii", title="第（Ⅱ）问：求最小值", steps=[step.id])])
    snapshot = SimpleNamespace(problem={"scopes": [
        {"scope_id": "ii", "parent": "problem", "label": "第（Ⅱ）问：求最小值"},
    ], "original_text": ["（Ⅱ）求最小值。"]})
    result = lesson_data_from_lesson_ir(lesson, {}, snapshot=snapshot)
    assert result["steps"][0]["section"] == "第（Ⅱ）问：求最小值"
    assert step.section_label == "多次应用基本不等式"


@pytest.mark.parametrize("route, expected", [
    ("直接应用基本不等式", "直接应用基本不等式"), ("", "解题过程"),
])
def test_internal_branch_title_cannot_create_a_question(route, expected):
    step = SimpleNamespace(id="s", scope_id="branch", title="计算", nav_title="计算",
                           derive=[], box=[], section_label=route)
    lesson = SimpleNamespace(problem_id="p", steps=[step], sections=[SimpleNamespace(
        scope_id="branch", title="第（Ⅰ）问", steps=[step.id])])
    snapshot = SimpleNamespace(problem={"original_text": ["求原式最小值。"], "scopes": [
        {"scope_id": "problem", "parent": None, "label": "题目"},
        {"scope_id": "branch", "parent": "problem", "label": "第（Ⅰ）问"},
    ]})
    result = lesson_data_from_lesson_ir(lesson, {}, snapshot=snapshot)
    assert result["steps"][0]["section"] == expected
    assert result["ui"]["groupTitles"][expected] == expected


def test_shared_prelude_and_nested_runtime_branch_use_source_question_ownership():
    scopes = [
        {"scope_id": "problem", "parent": None, "label": "题目"},
        {"scope_id": "first", "parent": "problem", "label": "（Ⅰ）"},
        {"scope_id": "second", "parent": "problem", "label": "（Ⅱ）"},
        {"scope_id": "branch", "parent": "second", "label": "正根分支"},
    ]
    steps = [SimpleNamespace(id=s, scope_id=s, title="计算", nav_title="计算",
                             derive=[], box=[], section_label="直接应用基本不等式")
             for s in ("problem", "branch")]
    lesson = SimpleNamespace(problem_id="p", steps=steps, sections=[SimpleNamespace(
        scope_id=s.scope_id, title=s.scope_id, steps=[s.id]) for s in steps])
    snapshot = SimpleNamespace(problem={"scopes": scopes, "original_text": [
        "（Ⅰ）求最大值。", "（Ⅱ）求最小值。",
    ]})
    result = lesson_data_from_lesson_ir(lesson, {}, snapshot=snapshot)
    assert [s["section"] for s in result["steps"]] == ["公共推导", "第（Ⅱ）问：求最小值"]


def test_missing_child_text_does_not_steal_parent_goal():
    assert _question_target_for_section(
        title="第（Ⅱ）①问", scope_id="ii_1",
        problem_lines=["(II) 求公共函数解析式。"],
    ) == ""


def test_compound_goal_is_not_truncated_at_last_request():
    assert _question_target_for_section(
        title="(III)", scope_id="third", problem_lines=[
            "（Ⅲ）求点 P，再求函数解析式。",
        ],
    ) == "求点 P，再求函数解析式"


@pytest.mark.parametrize("text", [
    "1. 求b的值；2. 求c的值",
    "1、求b的值；2、求c的值",
    "⑴求b的值；⑵求c的值",
    "（1）求b的值；2. 求c的值",
    "求b和c的值。",
    "",
])
def test_numbered_scope_labels_preserve_questions_without_source_marker_match(text):
    scopes = [
        {"scope_id": "problem", "parent": None, "label": "题目"},
        {"scope_id": "one", "parent": "problem", "label": "第（1）问"},
        {"scope_id": "two", "parent": "problem", "label": "第（2）问"},
        {"scope_id": "positive", "parent": "two", "label": "正根分支"},
    ]
    steps = [SimpleNamespace(
        id=s, scope_id=s, title="计算", nav_title="求值", derive=[], box=[],
        section_label="直接应用基本不等式",
    ) for s in ("problem", "one", "two", "positive")]
    lesson = SimpleNamespace(problem_id="p", steps=steps, sections=[
        SimpleNamespace(scope_id=s.scope_id, title=s.scope_id, steps=[s.id])
        for s in steps
    ])
    snapshot = SimpleNamespace(problem={"scopes": scopes, "original_text": [text]})
    result = lesson_data_from_lesson_ir(lesson, {}, snapshot=snapshot)
    titles = [s["section"] for s in result["steps"]]
    assert titles[0] == "公共推导"
    assert titles[1].startswith("第（1）问：")
    assert titles[2].startswith("第（2）问：")
    assert titles[3] == titles[2]
    assert all(result["ui"]["groupTitles"][title] == title for title in titles)
