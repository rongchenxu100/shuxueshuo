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
