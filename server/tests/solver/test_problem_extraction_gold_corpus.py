from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from PIL import Image
import pytest

from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpus,
    GoldCorpusError,
    audit_gold_corpus,
    load_gold_corpus,
    main,
    render_gold_overlays,
)
from shuxueshuo_server.solver.extraction import gold_corpus as gold_corpus_module
from shuxueshuo_server.solver.extraction.semantic_diff import (
    compare_problem_semantics,
)


EXPECTED_PROBLEM_IDS = {
    "tj-2026-heping-ermo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-nankai-yimo-25",
    "tj-2026-xiqing-yimo-25",
}
EXPECTED_COVERAGE_GAPS = {
    "cross_page_target",
    "deterministic_complete_anchor",
    "printed_figure_in_target",
    "unrecoverable_occlusion",
}


@pytest.fixture(scope="module")
def gold_corpus() -> GoldCorpus:
    return load_gold_corpus()


def test_gold_corpus_has_five_immutable_source_cases(gold_corpus: GoldCorpus) -> None:
    report = audit_gold_corpus(gold_corpus)

    assert report.ok, report.to_text()
    assert report.case_count == 5
    assert {case.problem_id for case in gold_corpus.cases} == EXPECTED_PROBLEM_IDS
    assert len({case.manifest.problem_fixture for case in gold_corpus.cases}) == 5
    assert all(len(case.manifest.pages) == 1 for case in gold_corpus.cases)


def test_auditor_rejects_empty_corpus_and_missing_f0_anchors(
    tmp_path: Path,
) -> None:
    report = audit_gold_corpus(GoldCorpus(root=tmp_path, cases=()))

    assert not report.ok
    assert report.case_count == 0
    assert "gold.corpus_empty" in {issue.code for issue in report.issues}
    assert {
        issue.problem_id
        for issue in report.issues
        if issue.code == "gold.anchor_case_missing"
    } == EXPECTED_PROBLEM_IDS


def test_gold_corpus_cli_rejects_empty_root(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path)]) == 1
    assert "gold.corpus_empty" in capsys.readouterr().out


def test_gold_annotations_cover_every_authored_semantic_identity(
    gold_corpus: GoldCorpus,
) -> None:
    for case in gold_corpus.cases:
        fixture = _fixture_payload(case.manifest.problem_fixture)
        expected = fixture["input"]
        report = compare_problem_semantics(
            expected,
            expected,
            actual_evidence=case.annotation.semantic_evidence,
        )

        assert report.ok, report.to_payload()
        evidence_by_id = {
            item.evidence_id: item for item in case.annotation.evidence
        }
        referenced = {
            ref
            for category in case.annotation.semantic_evidence.values()
            for refs in category.values()
            for ref in refs
        }
        assert referenced
        assert all(evidence_by_id[ref].purpose == "problem_source" for ref in referenced)
        assert all(evidence_by_id[ref].origin != "handwritten" for ref in referenced)


def test_gold_coverage_report_is_stable_and_keeps_real_gaps(
    gold_corpus: GoldCorpus,
) -> None:
    first = audit_gold_corpus(gold_corpus)
    second = audit_gold_corpus(gold_corpus)

    assert first.to_payload() == second.to_payload()
    assert {gap.code for gap in first.coverage_gaps} == EXPECTED_COVERAGE_GAPS
    assert first.coverage["declared.expected_route=multimodal_required"] == (
        "tj-2026-xiqing-yimo-25",
    )
    assert first.coverage["declared.handwriting=non_overlapping"] == (
        "tj-2026-heping-yimo-25",
    )
    assert first.coverage["grounded.printed_figure_in_target=false"] == tuple(
        sorted(EXPECTED_PROBLEM_IDS)
    )


def test_neighbor_coverage_counts_unique_subjects_not_polygons(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-nankai-yimo-25")
    original = case.annotation.excluded_regions[0]
    second_polygon = replace(
        original,
        region_id="neighbor_question_24_part_2",
        polygon=((0.025, 0.175), (0.1, 0.175), (0.1, 0.63), (0.025, 0.63)),
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                excluded_regions=(original, second_polygon),
            ),
        ),
    )

    report = audit_gold_corpus(mutated)

    assert report.ok, report.to_text()
    assert "gold.coverage_neighbor_count_mismatch" not in {
        issue.code for issue in report.issues
    }
    assert set(report.coverage["grounded.neighbor_question_count=1"]) == {
        case.problem_id,
        "tj-2026-heping-ermo-25",
        "tj-2026-hexi-yimo-25",
        "tj-2026-xiqing-yimo-25",
    }


def test_one_excluded_polygon_may_reference_multiple_neighbor_questions(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-nankai-yimo-25")
    existing_subject = case.annotation.excluded_subjects[0]
    second_subject = replace(
        existing_subject,
        subject_id="neighbor_question_23",
        label="第23题",
    )
    region = replace(
        case.annotation.excluded_regions[0],
        subject_ids=(existing_subject.subject_id, second_subject.subject_id),
    )
    coverage = dict(case.annotation.coverage)
    coverage["neighbor_question_count"] = 2
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                excluded_subjects=(existing_subject, second_subject),
                excluded_regions=(region,),
                coverage=coverage,
            ),
        ),
    )

    report = audit_gold_corpus(mutated)

    assert report.ok, report.to_text()


def test_non_neighbor_exclusion_does_not_change_neighbor_count(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-nankai-yimo-25")
    existing_subject = case.annotation.excluded_subjects[0]
    header_subject = replace(
        existing_subject,
        subject_id="page_header",
        kind="header",
        label="页眉",
    )
    header_region = replace(
        case.annotation.excluded_regions[0],
        region_id="page_header_region",
        subject_ids=(header_subject.subject_id,),
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                excluded_subjects=(existing_subject, header_subject),
                excluded_regions=(
                    case.annotation.excluded_regions[0],
                    header_region,
                ),
            ),
        ),
    )

    report = audit_gold_corpus(mutated)

    assert report.ok, report.to_text()


def test_coverage_cannot_claim_a_printed_figure_without_evidence(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    coverage = dict(case.annotation.coverage)
    coverage["printed_figure_in_target"] = True
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(case.annotation, coverage=coverage),
        ),
    )

    report = audit_gold_corpus(mutated)

    assert "gold.coverage_printed_figure_mismatch" in {
        issue.code for issue in report.issues
    }
    assert "printed_figure_in_target" in {
        gap.code for gap in report.coverage_gaps
    }


def test_coverage_cannot_self_certify_deterministic_complete(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    coverage = dict(case.annotation.coverage)
    coverage.update(
        expected_route="deterministic_complete",
        zero_llm_expected=True,
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(case.annotation, coverage=coverage),
        ),
    )

    report = audit_gold_corpus(mutated)

    assert "gold.deterministic_route_unverified" in {
        issue.code for issue in report.issues
    }
    assert "deterministic_complete_anchor" in {
        gap.code for gap in report.coverage_gaps
    }


def test_coverage_rejects_ungrounded_multimodal_route(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    coverage = dict(case.annotation.coverage)
    coverage["expected_route"] = "multimodal_required"
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(case.annotation, coverage=coverage),
        ),
    )

    assert "gold.coverage_multimodal_ungrounded" in _issue_codes(mutated)


def test_gold_overlays_render_for_manual_review(
    gold_corpus: GoldCorpus,
    tmp_path: Path,
) -> None:
    rendered = render_gold_overlays(gold_corpus, tmp_path)

    assert len(rendered) == 5
    assert {path.stem.rsplit("-page_1", 1)[0] for path in rendered} == EXPECTED_PROBLEM_IDS
    for path in rendered:
        with Image.open(path) as image:
            assert image.width > 1000
            assert image.height > 1500


def test_semantic_diff_ignores_outer_table_order_and_display_text() -> None:
    expected = _fixture_payload(
        "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
    )
    actual = deepcopy(expected)
    payload = actual["input"]
    for category in ("scopes", "entities", "facts", "question_goals"):
        payload[category] = list(reversed(payload[category]))
    payload["original_text"]["lines"] = [
        "  " + line.replace("，", "，  ").replace("（", "(").replace("）", ")")
        for line in payload["original_text"]["lines"]
    ]
    for item in payload["entities"] + payload["facts"]:
        item["description"] = "仅用于展示的改写"
        item["display"] = "仅用于展示"
        item["source"] = "compatibility text"

    report = compare_problem_semantics(expected, actual)

    assert report.ok, report.to_payload()


@pytest.mark.parametrize(
    ("mutation", "expected_category", "expected_kind"),
    (
        ("delete_entity", "entities", "missing"),
        ("add_entity", "entities", "unexpected"),
        ("change_fact_subject", "facts", "value_mismatch"),
        ("change_scope_parent", "scopes", "value_mismatch"),
        ("delete_goal", "question_goals", "missing"),
    ),
)
def test_semantic_diff_reports_structural_mutations(
    mutation: str,
    expected_category: str,
    expected_kind: str,
) -> None:
    expected = _fixture_payload(
        "internal/solver-fixtures/tj-2026-heping-yimo-25.json"
    )
    actual = deepcopy(expected)
    payload = actual["input"]
    if mutation == "delete_entity":
        payload["entities"].pop()
    elif mutation == "add_entity":
        extra = deepcopy(payload["entities"][-1])
        extra["handle"] = "segment:ii:unexpected"
        extra["name"] = "unexpected"
        payload["entities"].append(extra)
    elif mutation == "change_fact_subject":
        fact = payload["facts"][0]
        fact["subject"] = "symbol:problem:b"
    elif mutation == "change_scope_parent":
        scope = next(item for item in payload["scopes"] if item["scope_id"] == "i_2")
        scope["parent"] = "ii"
    elif mutation == "delete_goal":
        payload["question_goals"].pop()

    report = compare_problem_semantics(expected, actual)

    assert not report.ok
    assert any(
        item.category == expected_category and item.kind == expected_kind
        for item in report.differences
    )
    assert report.to_payload() == compare_problem_semantics(expected, actual).to_payload()


def test_semantic_diff_reports_missing_evidence_by_identity(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    fixture = _fixture_payload(case.manifest.problem_fixture)
    evidence = {
        category: dict(entries)
        for category, entries in case.annotation.semantic_evidence.items()
    }
    evidence["question_goals"].pop("answer:iii_b")

    report = compare_problem_semantics(
        fixture,
        fixture,
        actual_evidence=evidence,
    )

    assert not report.ok
    assert report.first_mismatch is not None
    assert report.first_mismatch.kind == "evidence_missing"
    assert report.first_mismatch.identity == "answer:iii_b"


def test_semantic_diff_reports_missing_original_text_line_evidence(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    fixture = _fixture_payload(case.manifest.problem_fixture)
    evidence = {
        category: dict(entries)
        for category, entries in case.annotation.semantic_evidence.items()
    }
    evidence["original_text_lines"] = {}

    report = compare_problem_semantics(
        fixture,
        fixture,
        actual_evidence=evidence,
    )

    assert not report.ok
    assert {
        (item.category, item.identity, item.kind)
        for item in report.differences
    } == {
        ("original_text_lines", str(index), "evidence_missing")
        for index in range(4)
    }


def test_semantic_diff_preserves_order_inside_semantic_records() -> None:
    expected = _fixture_payload(
        "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
    )
    actual = deepcopy(expected)
    fact = next(
        item
        for item in actual["input"]["facts"]
        if item["handle"] == "fact:problem:coefficient_relation"
    )
    fact["subjects"] = list(reversed(fact["subjects"]))

    report = compare_problem_semantics(expected, actual)

    assert not report.ok
    assert any(
        item.identity == "fact:problem:coefficient_relation"
        and item.path.endswith(".subjects")
        and item.kind == "value_mismatch"
        for item in report.differences
    )


def test_auditor_rejects_changed_source_sha(gold_corpus: GoldCorpus) -> None:
    case = gold_corpus.cases[0]
    page = replace(case.manifest.pages[0], sha256="0" * 64)
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, manifest=replace(case.manifest, pages=(page,))),
    )

    assert "gold.source_sha_mismatch" in _issue_codes(mutated)


def test_auditor_rejects_changed_source_orientation(
    gold_corpus: GoldCorpus,
) -> None:
    case = gold_corpus.cases[0]
    page = replace(case.manifest.pages[0], orientation_degrees=90)
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, manifest=replace(case.manifest, pages=(page,))),
    )

    assert "gold.source_orientation_mismatch" in _issue_codes(mutated)


def test_auditor_reports_mirrored_exif_without_false_rotation_mismatch(
) -> None:
    image = Image.new("RGB", (20, 10), "white")
    image.getexif()[274] = 2

    assert gold_corpus_module._image_orientation(image) == (0, True)


def test_auditor_rejects_fixture_path_outside_repository(
    gold_corpus: GoldCorpus,
    tmp_path: Path,
) -> None:
    case = gold_corpus.cases[0]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text("{}", encoding="utf-8")
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            manifest=replace(
                case.manifest,
                problem_fixture=str(fixture_path),
            ),
        ),
    )

    assert "gold.problem_fixture_path_outside_repo" in _issue_codes(mutated)


def test_auditor_rejects_asset_path_outside_repository(
    gold_corpus: GoldCorpus,
    tmp_path: Path,
) -> None:
    case = gold_corpus.cases[0]
    asset_path = tmp_path / "source.jpg"
    Image.new("RGB", (20, 10), "white").save(asset_path)
    page = replace(case.manifest.pages[0], asset_path=str(asset_path))
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, manifest=replace(case.manifest, pages=(page,))),
    )

    assert "gold.source_asset_path_outside_repo" in _issue_codes(mutated)


def test_auditor_reports_malformed_canonical_fixture_as_typed_issue(
    gold_corpus: GoldCorpus,
) -> None:
    case = gold_corpus.cases[0]
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            manifest=replace(
                case.manifest,
                problem_fixture=(
                    "internal/schemas/"
                    "problem-extraction-source-manifest.schema.json"
                ),
            ),
        ),
    )

    report = audit_gold_corpus(mutated)

    assert not report.ok
    assert "gold.problem_fixture_semantics_invalid" in {
        issue.code for issue in report.issues
    }


def test_auditor_rejects_missing_source_asset(gold_corpus: GoldCorpus) -> None:
    case = gold_corpus.cases[0]
    page = replace(case.manifest.pages[0], asset_path="missing/source-page.png")
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, manifest=replace(case.manifest, pages=(page,))),
    )

    assert "gold.source_asset_missing" in _issue_codes(mutated)


def test_auditor_rejects_duplicate_evidence_id(gold_corpus: GoldCorpus) -> None:
    case = gold_corpus.cases[0]
    annotation = replace(
        case.annotation,
        evidence=case.annotation.evidence + (case.annotation.evidence[0],),
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, annotation=annotation),
    )

    assert "gold.duplicate_evidence_id" in _issue_codes(mutated)


def test_auditor_rejects_unreferenced_problem_source_evidence(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    orphan = replace(case.annotation.evidence[0], evidence_id="orphan_printed")
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                evidence=case.annotation.evidence + (orphan,),
            ),
        ),
    )

    assert "gold.problem_source_evidence_orphan" in _issue_codes(mutated)


def test_auditor_rejects_handwriting_relabelled_as_printed(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-xiqing-yimo-25")
    evidence = tuple(
        replace(item, origin="printed")
        if item.evidence_id == "student_work_overlay"
        else item
        for item in case.annotation.evidence
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, annotation=replace(case.annotation, evidence=evidence)),
    )

    assert "gold.student_work_marked_printed" in _issue_codes(mutated)


def test_auditor_rejects_unknown_evidence_as_semantic_source(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    evidence = tuple(
        replace(item, origin="unknown")
        if item.evidence_id == "printed_line_3"
        else item
        for item in case.annotation.evidence
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(case, annotation=replace(case.annotation, evidence=evidence)),
    )

    assert "gold.semantic_evidence_origin_invalid" in _issue_codes(mutated)


def test_auditor_rejects_selection_that_includes_neighbor_question(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-nankai-yimo-25")
    selection = replace(
        case.annotation.selection_regions[0],
        polygon=case.annotation.excluded_regions[0].polygon,
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(case.annotation, selection_regions=(selection,)),
        ),
    )

    assert "gold.selection_overlaps_excluded_region" in _issue_codes(mutated)


def test_auditor_uses_real_polygon_containment(gold_corpus: GoldCorpus) -> None:
    case = _case(gold_corpus, "tj-2026-heping-yimo-25")
    diamond = replace(
        case.annotation.selection_regions[0],
        polygon=((0.5, 0.005), (0.985, 0.5), (0.5, 0.995), (0.015, 0.5)),
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(case.annotation, selection_regions=(diamond,)),
        ),
    )

    assert "gold.semantic_evidence_outside_selection" in _issue_codes(mutated)


def test_selection_and_excluded_regions_may_share_only_a_boundary(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-nankai-yimo-25")
    selection = replace(
        case.annotation.selection_regions[0],
        polygon=((0.1, 0.1), (0.9, 0.1), (0.1, 0.9)),
    )
    excluded = replace(
        case.annotation.excluded_regions[0],
        polygon=((0.9, 0.9), (0.1, 0.9), (0.9, 0.1)),
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                selection_regions=(selection,),
                excluded_regions=(excluded,),
            ),
        ),
    )

    assert "gold.selection_overlaps_excluded_region" not in _issue_codes(mutated)


def test_auditor_rejects_missing_goal_evidence(gold_corpus: GoldCorpus) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    semantic_evidence = {
        category: dict(entries)
        for category, entries in case.annotation.semantic_evidence.items()
    }
    semantic_evidence["question_goals"].pop("answer:iii_b")
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                semantic_evidence=semantic_evidence,
            ),
        ),
    )

    assert "gold.semantic_evidence_missing" in _issue_codes(mutated)


def test_auditor_rejects_missing_fact_evidence(gold_corpus: GoldCorpus) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    semantic_evidence = {
        category: dict(entries)
        for category, entries in case.annotation.semantic_evidence.items()
    }
    semantic_evidence["facts"].pop("fact:iii:path_minimum_target")
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                semantic_evidence=semantic_evidence,
            ),
        ),
    )

    assert "gold.semantic_evidence_missing" in _issue_codes(mutated)


def test_auditor_reports_each_missing_semantic_identity_once(
    gold_corpus: GoldCorpus,
) -> None:
    case = _case(gold_corpus, "tj-2026-hexi-yimo-25")
    semantic_evidence = {
        category: dict(entries)
        for category, entries in case.annotation.semantic_evidence.items()
    }
    semantic_evidence["original_text_lines"] = {}
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            annotation=replace(
                case.annotation,
                semantic_evidence=semantic_evidence,
            ),
        ),
    )

    missing = [
        issue
        for issue in audit_gold_corpus(mutated).issues
        if issue.code == "gold.semantic_evidence_missing"
        and issue.path.startswith("$.semantic_evidence.original_text_lines.")
    ]

    assert len(missing) == 4
    assert {issue.path.rsplit(".", 1)[-1] for issue in missing} == {
        "0",
        "1",
        "2",
        "3",
    }


def test_auditor_rejects_problem_directory_name_mismatch(
    gold_corpus: GoldCorpus,
) -> None:
    case = gold_corpus.cases[0]
    wrong_path = (
        case.manifest.path.parent.parent
        / "wrong-dir-name"
        / case.manifest.path.name
    )
    mutated = _replace_case(
        gold_corpus,
        case.problem_id,
        replace(
            case,
            manifest=replace(case.manifest, path=wrong_path),
        ),
    )

    assert "gold.problem_directory_mismatch" in _issue_codes(mutated)


def test_loader_enforces_gold_annotation_json_schema(
    gold_corpus: GoldCorpus,
    tmp_path: Path,
) -> None:
    case = gold_corpus.cases[0]
    case_dir = tmp_path / case.problem_id
    case_dir.mkdir()
    manifest = json.loads(case.manifest.path.read_text(encoding="utf-8"))
    annotation = json.loads(case.annotation.path.read_text(encoding="utf-8"))
    annotation["coverage"].pop("expected_route")
    (case_dir / "source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    (case_dir / "gold-annotation.json").write_text(
        json.dumps(annotation, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(GoldCorpusError, match="expected_route"):
        load_gold_corpus(tmp_path)


def test_loader_enforces_source_manifest_json_schema(
    gold_corpus: GoldCorpus,
    tmp_path: Path,
) -> None:
    case = gold_corpus.cases[0]
    case_dir = tmp_path / case.problem_id
    case_dir.mkdir()
    manifest = json.loads(case.manifest.path.read_text(encoding="utf-8"))
    annotation = json.loads(case.annotation.path.read_text(encoding="utf-8"))
    manifest["pages"][0].pop("sha256")
    (case_dir / "source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    (case_dir / "gold-annotation.json").write_text(
        json.dumps(annotation, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(GoldCorpusError, match="sha256"):
        load_gold_corpus(tmp_path)


def _fixture_payload(path: str) -> dict[str, object]:
    return json.loads((Path(__file__).parents[3] / path).read_text(encoding="utf-8"))


def _case(gold_corpus: GoldCorpus, problem_id: str):
    return next(case for case in gold_corpus.cases if case.problem_id == problem_id)


def _replace_case(gold_corpus: GoldCorpus, problem_id: str, replacement) -> GoldCorpus:
    return replace(
        gold_corpus,
        cases=tuple(
            replacement if case.problem_id == problem_id else case
            for case in gold_corpus.cases
        ),
    )


def _issue_codes(gold_corpus: GoldCorpus) -> set[str]:
    return {item.code for item in audit_gold_corpus(gold_corpus).issues}
