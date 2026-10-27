"""Exercise M6 course export without replacing the frozen public course."""

import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.search.lesson import run_stage_two
from shuxueshuo_server.search.stage_three import run_stage_three
from tools.export_graph_walk_course import export_course

REPO = Path(__file__).resolve().parents[3]
@pytest.mark.parametrize("problem_id,expression,parameter,prescribed,original_text,expected", [
    ("function-concepts-q22-v2", "sqrt(k*x^2+2*x+1)", "k", "ℝ",
     r"函数 $f(x)=\sqrt{kx^{2}+2x+1}$ 的定义域为 $\mathbb R$，求实数 $k$ 的取值范围。",
     sp.Interval(1, sp.oo)),
    ("function-concepts-q04", "sqrt(m*x^2+4*m*x+3)", "m", "ℝ",
     r"函数 $y=\sqrt{mx^{2}+4mx+3}$ 的定义域为 $\mathbb R$，求实数 $m$ 的取值范围。",
     sp.Interval(0, sp.Rational(3, 4))),
    ("function-concepts-q12", "1/sqrt(m*x^2-6*m*x+m+8)", "m", "ℝ",
     r"函数 $f(x)=\dfrac{1}{\sqrt{mx^{2}-6mx+m+8}}$ 的定义域为 $\mathbb R$，求实数 $m$ 的取值范围。",
     sp.Interval.Ropen(0, 1)),
    ("function-concepts-q23b", "sqrt(x^2-3*x-m)/sqrt(x-1)", "m", "(1,∞)",
     r"已知函数 $f(x)=\dfrac{\sqrt{x^2-3x-m}}{\sqrt{x-1}}$ 的定义域为 $(1,+\infty)$，求实数 $m$ 的取值范围。",
     sp.Interval(-sp.oo, -sp.Rational(9, 4))),
], ids=["q22", "q04", "q12", "q23b"])
def test_export_match_domain_course_evidence(tmp_path, problem_id, expression, parameter, prescribed, original_text, expected):
    frozen = {
        path: path.read_bytes()
        for path in (REPO / "site/data/graph-walk").glob("function-concepts-*.json")
    }
    candidate = {
        "original_text": original_text,
        "root": {
            "definitions": [f"f(x)={expression}"],
            "facts": [],
            "goals": [{"kind": "match_domain", "object": "f", "domain": prescribed, "symbol": parameter}],
        },
    }
    extracted = candidate_features(candidate)
    assert extracted["ok"], extracted
    reviewed = {
        "status": "reviewed_candidate",
        "source_reviewed": True,
        "candidate": candidate,
        "features": extracted["features"],
        "features_ok": True,
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("recognition and exact execution must not call a model")

    stage_two = run_stage_two(
        tmp_path, reviewed, provider=forbidden, unsupported_root=tmp_path / "unsupported"
    )
    assert stage_two["status"] == "completed", stage_two
    assert stage_two["goals"][0]["primary"] == "type-function-domain"
    result = run_stage_three(tmp_path / "stage-two-1")
    assert result["status"] == "completed", result
    (goal,) = result["goals"]
    assert goal["status"] == "solved", goal
    (route,) = goal["routes"]
    assert route["status"] == "verified", route
    assert route["method"] == "method-domain-parameter"
    assert decode_value(route["feasible_set_exact"]) == expected
    snapshot = open_store(tmp_path / "stage-two-1" / "stage-three").snapshot()
    pending = [row for row in snapshot.get("interaction_states", []) if row.get("status") != "interactive"]
    assert not pending, pending
    evidence = export_course(tmp_path / "stage-two-1" / "stage-three", problem_id)
    goal = evidence["lesson"]["goals"][0]
    assert goal["primary"] == "type-function-domain"
    assert not goal["d1"].get("diagnostics"), goal["d1"].get("diagnostics")
    assert goal["walk"]["bundle"]["intro"], "D1/D2 walk required for topic course build"
    assert evidence["stream"]["contract"] == "graph-stage-three-snapshot/v2"
    titles = [part["title"] for row in evidence["stream"]["interactions"] for part in row["parts"]]
    assert "转化为恒成立问题" in titles
    assert "选择已学方法" in titles
    assert "回到定义域求参" in titles
    output = tmp_path / f"{problem_id}.evidence.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    assert json.loads(output.read_text()) == evidence
    assert {path: path.read_bytes() for path in frozen} == frozen
