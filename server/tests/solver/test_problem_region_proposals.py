from __future__ import annotations

from dataclasses import replace

from shuxueshuo_server.solver.extraction.observations import (
    ProblemRegionProposer,
    bbox_overlap_ratio,
    polygon_bbox,
)
from shuxueshuo_server.solver.extraction.source_identity import SourceSelection
from _problem_extraction_f2_support import assemble_fixture, make_fixture


def test_proposer_splits_neighboring_questions(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path)
    proposals = {item.question_label: item for item in result.observation.proposals}
    assert set(proposals) == {"24", "25"}
    assert proposals["24"].polygons[0] != proposals["25"].polygons[0]
    assert bbox_overlap_ratio(proposals["25"].polygons[0], proposals["24"].polygons[0]) == 0


def test_missing_question_labels_produces_typed_incomplete_issue() -> None:
    fixture = make_fixture()
    spans = tuple(replace(item, text="plain text") for item in __import__(
        "shuxueshuo_server.solver.extraction.observations",
        fromlist=["PaddleObservationAdapter"],
    ).PaddleObservationAdapter().text(fixture.text_record, source_artifact_id="artifact:page"))
    proposals, issues = ProblemRegionProposer().propose(
        pages=(),
        layout_blocks=(),
        text_spans=spans,
    )
    assert proposals == ()
    assert [item.code for item in issues] == ["extraction.problem_region_incomplete"]


def test_adjusted_selection_changes_selection_identity_without_source_drift() -> None:
    fixture = make_fixture()
    adjusted = SourceSelection.create(
        fixture.source,  # type: ignore[arg-type]
        mode="user_adjusted",
        revision=1,
        parent_selection_id=fixture.selection.selection_id,
        regions=(replace(fixture.selection.regions[0], polygon=((0.01, 0.48), (0.99, 0.48), (0.99, 0.99), (0.01, 0.99))),),
    )
    assert adjusted.source_id == fixture.selection.source_id
    assert adjusted.selection_id != fixture.selection.selection_id
    assert adjusted.parent_selection_id == fixture.selection.selection_id


def test_proposal_output_is_stable_under_input_order(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path)
    proposer = ProblemRegionProposer()
    expected, _ = proposer.propose(
        pages=result.observation.pages,
        layout_blocks=result.observation.layout_blocks,
        text_spans=result.observation.text_spans,
    )
    actual, _ = proposer.propose(
        pages=tuple(reversed(result.observation.pages)),
        layout_blocks=tuple(reversed(result.observation.layout_blocks)),
        text_spans=tuple(reversed(result.observation.text_spans)),
    )
    assert [item.to_payload() for item in actual] == [item.to_payload() for item in expected]


def test_double_column_questions_do_not_capture_the_other_column(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path)
    base = result.observation.text_spans[0]
    spans = (
        replace(
            base,
            observation_id="text:q24",
            text="24. left top",
            polygon=((0.05, 0.10), (0.42, 0.10), (0.42, 0.16), (0.05, 0.16)),
            reading_order=0,
        ),
        replace(
            base,
            observation_id="text:q25",
            text="25. left bottom",
            polygon=((0.05, 0.52), (0.42, 0.52), (0.42, 0.58), (0.05, 0.58)),
            reading_order=1,
        ),
        replace(
            base,
            observation_id="text:q26",
            text="26. right top",
            polygon=((0.56, 0.10), (0.94, 0.10), (0.94, 0.16), (0.56, 0.16)),
            reading_order=2,
        ),
        replace(
            base,
            observation_id="text:q27",
            text="27. right bottom",
            polygon=((0.56, 0.52), (0.94, 0.52), (0.94, 0.58), (0.56, 0.58)),
            reading_order=3,
        ),
    )

    proposals, issues = ProblemRegionProposer().propose(
        pages=result.observation.pages,
        layout_blocks=(),
        text_spans=spans,
    )

    assert issues == ()
    by_label = {item.question_label: item for item in proposals}
    assert set(by_label) == {"24", "25", "26", "27"}
    assert max(x for x, _ in by_label["24"].polygons[0]) < 0.5
    assert max(x for x, _ in by_label["25"].polygons[0]) < 0.5
    assert min(x for x, _ in by_label["26"].polygons[0]) > 0.5
    assert min(x for x, _ in by_label["27"].polygons[0]) > 0.5


def test_last_question_excludes_footer_bound_ocr(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path)
    base_block = result.observation.layout_blocks[0]
    footer = replace(
        base_block,
        observation_id="layout:footer",
        kind="footer",
        provider_label="footer",
        polygon=((0.05, 0.92), (0.95, 0.92), (0.95, 0.98), (0.05, 0.98)),
    )
    base_span = result.observation.text_spans[0]
    question = replace(
        base_span,
        observation_id="text:q25",
        text="25. target",
        polygon=((0.05, 0.50), (0.80, 0.50), (0.80, 0.56), (0.05, 0.56)),
        block_id=base_block.observation_id,
    )
    footer_text = replace(
        base_span,
        observation_id="text:footer",
        text="Page 1",
        polygon=((0.42, 0.93), (0.58, 0.93), (0.58, 0.97), (0.42, 0.97)),
        block_id=footer.observation_id,
    )

    proposals, issues = ProblemRegionProposer().propose(
        pages=result.observation.pages,
        layout_blocks=(base_block, footer),
        text_spans=(question, footer_text),
    )

    assert issues == ()
    assert len(proposals) == 1
    assert polygon_bbox(proposals[0].polygons[0])[3] < 0.9


def test_question_continuing_before_next_page_marker_gets_multi_page_proposal(
    tmp_path,
) -> None:
    _, result, _ = assemble_fixture(tmp_path)
    base_page = result.observation.pages[0]
    pages = (
        base_page,
        replace(
            base_page,
            page_id="page_2",
            source_artifact_id="artifact:page_2",
            layout_block_ids=(),
            reading_order=(),
        ),
    )
    base_span = result.observation.text_spans[0]
    spans = (
        replace(
            base_span,
            observation_id="text:q25",
            text="25. target starts",
            polygon=((0.05, 0.84), (0.92, 0.84), (0.92, 0.90), (0.05, 0.90)),
            reading_order=0,
        ),
        replace(
            base_span,
            observation_id="text:q25-tail",
            text="continued at the page bottom",
            polygon=((0.05, 0.92), (0.92, 0.92), (0.92, 0.98), (0.05, 0.98)),
            reading_order=1,
        ),
        replace(
            base_span,
            observation_id="text:q25-page2",
            page_id="page_2",
            text="continued on page two",
            polygon=((0.05, 0.08), (0.92, 0.08), (0.92, 0.16), (0.05, 0.16)),
            reading_order=0,
        ),
        replace(
            base_span,
            observation_id="text:q26",
            page_id="page_2",
            text="26. next question",
            polygon=((0.05, 0.40), (0.92, 0.40), (0.92, 0.46), (0.05, 0.46)),
            reading_order=1,
        ),
    )

    proposals, issues = ProblemRegionProposer().propose(
        pages=pages,
        layout_blocks=(),
        text_spans=spans,
    )

    assert issues == ()
    by_label = {item.question_label: item for item in proposals}
    assert by_label["25"].page_ids == ("page_1", "page_2")
    assert len(by_label["25"].polygons) == 2
    assert "cross_page_continuation" in by_label["25"].reason_codes
    assert by_label["25"].requires_confirmation is True
    assert by_label["26"].page_ids == ("page_2",)
