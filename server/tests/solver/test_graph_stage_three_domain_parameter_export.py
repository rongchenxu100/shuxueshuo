"""Exercise M6 course export without replacing the frozen public course."""

import json
from pathlib import Path

import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.search.lesson import run_stage_two
from shuxueshuo_server.search.stage_three import run_stage_three
from tools.export_graph_walk_course import export_course

REPO = Path(__file__).resolve().parents[3]
Q22 = sp.Interval(1, sp.oo)


def test_export_q22_match_domain_course_evidence(tmp_path):
    frozen = {
        path: path.read_bytes()
        for path in (REPO / "site/data/graph-walk").glob("function-concepts-q22*.json")
    }
    candidate = {
        "original_text": r"函数 $f(x)=\sqrt{kx^{2}+2x+1}$ 的定义域为 $\mathbb R$，求实数 $k$ 的取值范围。",
        "root": {
            "definitions": ["f(x)=sqrt(k*x^2+2*x+1)"],
            "facts": [],
            "goals": [{"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "k"}],
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
    assert decode_value(route["feasible_set_exact"]) == Q22
    snapshot = open_store(tmp_path / "stage-two-1" / "stage-three").snapshot()
    pending = [row for row in snapshot.get("interaction_states", []) if row.get("status") != "interactive"]
    assert not pending, pending
    evidence = export_course(tmp_path / "stage-two-1" / "stage-three", "function-concepts-q22")
    goal = evidence["lesson"]["goals"][0]
    assert goal["primary"] == "type-function-domain"
    assert not goal["d1"].get("diagnostics"), goal["d1"].get("diagnostics")
    assert goal["walk"]["bundle"]["intro"], "D1/D2 walk required for topic course build"
    assert evidence["stream"]["contract"] == "graph-stage-three-snapshot/v2"
    output = tmp_path / "function-concepts-q22.evidence.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    assert json.loads(output.read_text()) == evidence
    assert {path: path.read_bytes() for path in frozen} == frozen
