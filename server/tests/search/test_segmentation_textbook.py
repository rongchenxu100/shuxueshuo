"""Textbook questions end before their worked solutions; no model calls here."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.search.segmentation import (
    head_candidates,
    page_head_candidates,
    question_number,
    segment,
)
from shuxueshuo_server.search.segmentation_labels import (
    solution_heading,
    textbook_title,
)


def _line(y, head, *, left=.1, right=.9, height=.02):
    return {"box": [left, y, right, y + height], "head": head}


@pytest.mark.parametrize(("head", "number", "label"), [
    ("【例11】已知", 11, "例11"), ("例题 12. 求", 12, "例题12"),
    ("【变式1】", 1, "变式1"), ("变式训练2：", 2, "变式训练2"),
    ("练习1 已知", 1, "练习1"), ("（例十一）", 11, "例十一"),
])
def test_textbook_headings_keep_their_own_labels(head, number, label):
    title = textbook_title(head)
    assert (title["number"], title["label"]) == (number, label)


@pytest.mark.parametrize("head", ["例如1", "例1中的函数", "【变式1", "【例11", "练习", "1)2", "1/16"])
def test_prose_and_truncated_headings_are_not_question_starts(head):
    assert textbook_title(head) is None


def test_example_and_variants_restart_numbers_without_including_solutions_or_their_figures():
    lines = [
        _line(.05, "【例11】"), _line(.10, "A. B. C. D."), _line(.14, "解析："),
        _line(.20, "1. 先计算"), _line(.25, "答案：D"),
        _line(.35, "【变式1】"), _line(.40, "A. B. C. D."), _line(.44, "【解析】"),
        _line(.50, "1)2", left=.65, right=.68), _line(.55, "答案：C"),
        _line(.65, "【变式2】"), _line(.72, "解："),
        _line(.80, "【练习1】"), _line(.85, "求函数值。"),
        _line(.90, "8.", left=.70, right=.73),
    ]
    layout = [{"label": "figure", "box": [.6, .18, .9, .24]},
              {"label": "figure", "box": [.6, .67, .9, .70]}]
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": layout})
    assert [r["label"] for r in result.regions] == ["例11", "变式1", "变式2", "练习1"]
    for region, start, bottom, solution in zip(result.regions, [.05, .35, .65, .80],
                                               [.12, .42, .70, .87], [.14, .44, .72, 1]):
        assert region["crop"][1] <= start
        assert bottom <= region["crop"][3] <= solution


def test_book_titles_in_two_columns_keep_reading_order_and_local_solution_boundaries():
    lines = [_line(.1, "【例11】", right=.45), _line(.15, "答案：D", right=.45),
             _line(.2, "【变式1】", right=.45), _line(.25, "解析：", right=.45),
             _line(.1, "【例12】", left=.55), _line(.3, "解析：", left=.55)]
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": []})
    assert [r["label"] for r in result.regions] == ["例11", "变式1", "例12"]
    assert [r["column"] for r in result.regions] == [0, 0, 1]


def test_numbered_exercise_book_can_resume_after_a_solution():
    lines = [_line(.1, "1. 已知函数"), _line(.2, "解析："), _line(.25, "1. 先计算"),
             _line(.4, "2. 求函数值"), _line(.5, "解："), _line(.55, "1. 先计算")]
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": []})
    assert [r["number"] for r in result.regions] == [1, 2]
    assert result.regions[0]["crop"][3] <= .2
    assert result.regions[1]["crop"][3] <= .5
    lines[2]["head"] = "2. 先计算"
    lines[3]["head"] = "3. 求函数值"
    result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": []})
    assert [r["number"] for r in result.regions] == [1, 3], "solution steps must not re-enter through gap repair"


@pytest.mark.parametrize("head", ["1)2", "1）2", "1,2", "1，2"])
def test_formula_fragments_do_not_become_question_numbers(head):
    assert question_number(head, has_right_neighbour=True) is None


def test_isolated_digit_and_solution_only_page_fall_back_to_manual_selection():
    for lines in [
        [_line(.1, "已知函数"), _line(.4, "1.", left=.65, right=.68), _line(.5, "由此可得")],
        [_line(.1, "解析："), _line(.4, "1. 先计算"), _line(.5, "答案：C")],
    ]:
        result = segment({"width": 1000, "height": 1000, "lines": lines, "layout": []})
        assert result.mode == "uncertain"
        assert result.regions == []
    # A detached number followed by a real question body is still supported.
    lines = [_line(.1, "1.", right=.13), _line(.1, "", left=.15)]
    assert segment({"width": 1000, "height": 1000, "lines": lines, "layout": []}).regions[0]["number"] == 1


def test_short_title_can_use_several_paragraphs_to_ignore_a_facing_page_fragment():
    boxes = [(0, 60, 90, 110), (115, 60, 300, 90), (320, 60, 500, 90)]
    paragraphs = [(70, 200, 820, 240), (75, 300, 820, 340), (80, 500, 820, 540)]
    assert head_candidates(boxes, median_h=30, text_regions=paragraphs) == [0, 1]
    assert head_candidates(boxes, median_h=30, text_regions=paragraphs[:1]) == [0]


def test_recorded_textbook_page_keeps_questions_and_excludes_worked_answers():
    path = Path(__file__).parent / "fixtures/segment-textbook-solutions.ocr.json"
    ocr = json.loads(path.read_text())
    result = segment(ocr)
    assert [r["label"] for r in result.regions] == ["例11", "变式1", "变式2"]
    # Gold vertical bands include the piecewise formulas and all answer choices.
    for region, (top, bottom, solution_end) in zip(result.regions, [(.060, .140, .17), (.288, .380, .42), (.696, .741, .78)]):
        assert region["crop"][1] <= top
        assert bottom <= region["crop"][3] < solution_end
        assert region["crop"][0] > .04, "facing-page notes must stay outside the questions"
    wanted = page_head_candidates(ocr["lines"], ocr["layout"], ocr["width"], ocr["height"])
    example = next(i for i, line in enumerate(ocr["lines"]) if textbook_title(line["head"]) ==
                   {"kind": "example", "number": 11, "label": "例11"})
    assert example in wanted
    assert solution_heading("解析：") and not solution_heading("答案是什么")
