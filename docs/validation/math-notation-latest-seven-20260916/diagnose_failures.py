"""Offline difference isolation, not acceptance or a repair to model responses.

Run from server: uv run python ../docs/validation/math-notation-latest-seven-20260916/diagnose_failures.py
Only diagnostic copies in memory are changed. Frozen inputs, gold, live outputs,
parser and acceptance policies are never written by this script.
"""

import json
from copy import deepcopy
from pathlib import Path

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_semantics import compare

ROOT = Path(__file__).resolve().parents[3]
BATCH = ROOT / "internal/solver-runs/math-notation-remaining-six-20260916-120805"
results = {}


def start(case):
    directory = BATCH / case
    expected = json.loads((directory / "input-fixture/gold.json").read_text())
    actual = json.loads((directory / "raw-response.txt").read_text())
    return expected, actual


def check(case, stage, expected, actual):
    report = NotationValidator().validate(actual)
    difference = compare(expected, actual)
    results.setdefault(case, []).append({
        "stage": stage,
        "diagnostic_only": True,
        "valid": report.ok,
        "parse_issue_count": len(report.issues),
        "parse_issues": report.issues,
        "comparison_ok": difference["ok"],
        "classification": difference["classification"],
        "remaining_paths": [x["path"] for x in difference.get("differences", [])],
    })


def replace(scope, old, new):
    index = scope["facts"].index(old)
    scope["facts"][index] = new


case = "tj-2026-heping-ermo-25"
gold, raw = start(case)
check(case, "original", gold, raw)
copy = deepcopy(raw)
replace(copy["root"], "axis(Γ) ∩ x_axis = {M}", "M ∈ axis(Γ) ∩ x_axis")
check(case, "M intersection notation aligned in diagnostic copy", gold, copy)
replace(copy["root"]["children"][1], "line(A,K) ∩ line(E,G) = {H}", "H ∈ segment(A,K) ∩ segment(E,G)")
check(case, "H intersection notation also aligned in diagnostic copy", gold, copy)

case = "tj-2026-hexi-yimo-25"
gold, raw = start(case)
check(case, "original", gold, raw)
copy = deepcopy(raw)
replace(copy["root"]["children"][2], "M = (b+1/2, y_M)", "x(M) = b+1/2")
check(case, "M coordinate notation aligned in diagnostic copy", gold, copy)

case = "tj-2026-nankai-yimo-25"
gold, raw = start(case)
check(case, "original", gold, raw)
copy = deepcopy(raw)
replace(copy["root"], "axis(Γ) ∩ x_axis = {D}", "D ∈ axis(Γ) ∩ x_axis")
check(case, "D intersection notation aligned in diagnostic copy", gold, copy)
copy["root"]["children"][1]["children"][1]["goals"][0].pop("at")
check(case, "equation-goal at removed in diagnostic copy, not a correctness ruling", gold, copy)

case = "tj-2026-xiqing-yimo-25"
gold, raw = start(case)
check(case, "original", gold, raw)
copy = deepcopy(raw)
replace(copy["root"]["children"][1], "D = (b+2, y_D)", "x(D) = b+2")
check(case, "D coordinate notation aligned in diagnostic copy", gold, copy)
copy["root"]["facts"].remove("A ∈ Γ")
check(case, "redundant membership also removed in diagnostic copy", gold, copy)

case = "k-quad"
gold, raw = start(case)
check(case, "original", gold, raw)
copy = deepcopy(raw)
replace(copy["root"]["children"][0]["children"][0], "AC ∩ BD = {O}", "segment(A,C) ∩ segment(B,D) = {O}")
check(case, "explicit segment operands substituted in diagnostic copy", gold, copy)
copy["root"]["children"][0]["children"][1]["facts"].insert(0, "quadrilateral(A,B,C,D)")
copy["root"]["children"][1]["facts"].insert(0, "quadrilateral(A,B,C,D)")
check(case, "two explicit quadrilateral relations restored in diagnostic copy", gold, copy)

payload = {"offline_only": True, "model_calls": 0, "live_results_unchanged": True, "cases": results}
Path(__file__).with_name("failure-diagnostics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
for case, stages in results.items():
    for stage in stages:
        print(case, stage["stage"], stage["parse_issue_count"], stage["comparison_ok"], stage["remaining_paths"])
