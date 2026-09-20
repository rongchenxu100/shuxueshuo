"""Offline diagnostics; modified copies never replace the saved model response.

From server: uv run python ../docs/validation/math-notation-geometry-proofs-20260916/diagnose_k.py
"""

import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_semantics import compare

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "internal/solver-runs/math-notation-seven-20260916-135634/k-quad"
raw = (SOURCE / "raw-response.txt").read_bytes()
actual = json.loads(raw)
gold = json.loads((SOURCE / "input-fixture/gold.json").read_text())
aligned = deepcopy(actual)
children = aligned["root"]["children"]
aligned["root"]["children"] = [{"label": "(1)", "children": children[:2]}, *children[2:]]
marked = deepcopy(aligned)


def leaves(payload):
    nodes = payload["root"]["children"]
    return [*nodes[0]["children"], *nodes[1:]]


for target, expected in zip(leaves(marked), leaves(gold)):
    target["uncertainties"] = deepcopy(expected["uncertainties"])

comparisons = {
    "original_response": compare(gold, actual),
    "diagnostic_hierarchy_aligned_only": compare(gold, aligned),
    "diagnostic_hierarchy_and_missing_flags_restored": compare(gold, marked),
}
assert not comparisons["original_response"]["ok"]
remaining = comparisons["diagnostic_hierarchy_aligned_only"]
assert len(remaining["differences"]) == 4
assert all(d["path"].endswith("/uncertainties") for d in remaining["differences"])
assert comparisons["diagnostic_hierarchy_and_missing_flags_restored"]["ok"]
normalization = {}
for name, payload in (("gold", gold), ("diagnostic_hierarchy_aligned", aligned)):
    report = NotationValidator().validate(payload)
    assert report.ok
    normalization[name] = report.semantic_normalization["proofs"]

result = {
    "offline_only": True,
    "network_calls": 0,
    "source_response": str(SOURCE / "raw-response.txt"),
    "source_sha256": sha256(raw).hexdigest(),
    "diagnostic_changes_are_not_model_outputs": True,
    "diagnostic_edits": ["restore the empty (1) parent", "restore four missing_figure flags from frozen gold"],
    "comparisons": comparisons,
    "normalization_proofs": normalization,
}
(HERE / "k-diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({
    "original_passed": comparisons["original_response"]["ok"],
    "after_hierarchy_alignment_remaining_paths": [d["path"] for d in remaining["differences"]],
    "diagnostic_math_equivalent": comparisons["diagnostic_hierarchy_and_missing_flags_restored"]["ok"],
    "proof_counts": {name: dict(Counter(p["rule"] for p in proofs)) for name, proofs in normalization.items()},
}, ensure_ascii=False, indent=2))
