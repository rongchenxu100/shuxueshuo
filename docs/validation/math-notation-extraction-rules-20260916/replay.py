"""Audit unchanged recorded responses against both gold revisions; no provider."""

import json
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.problem_understanding.notation_contract import TEMPLATE_FILES
from shuxueshuo_server.problem_understanding.notation_semantics import evaluate
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
FIXTURES = ROOT / "server/tests/solver/fixtures/math-notation-v1"
RECORDED = FIXTURES / "recorded-latest-20260916"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    output = BASE / "replay"
    output.mkdir(exist_ok=False)
    records = json.loads((RECORDED / "manifest.json").read_text())
    revision = json.loads((FIXTURES / "gold-revisions.json").read_text())
    results = {}
    for entry in records["cases"]:
        case = entry["case"]
        source = ROOT / entry["source"]
        frozen = json.loads((source / "frozen.json").read_text())
        raw = (RECORDED / (case + ".txt")).read_bytes()
        assert raw == (source / "raw-response.txt").read_bytes()
        assert sha256(raw).hexdigest() == entry["raw_sha256"]
        original_gold = (RECORDED / (case + ".gold.json")).read_bytes()
        assert sha256(original_gold).hexdigest() == frozen["gold_sha256"] == entry["gold_sha256"]
        current_gold = (FIXTURES / (case + ".json")).read_bytes()
        assert sha256(current_gold).hexdigest() == revision["cases"][case]["sha256"]
        policy_file = RECORDED / (case + ".policy.json")
        policy = json.loads(policy_file.read_text()) if policy_file.exists() else None
        if policy is not None:
            assert sha256(policy_file.read_bytes()).hexdigest() == entry["policy_sha256"]
        actual, expected = json.loads(raw), json.loads(current_gold)
        old_result = evaluate(json.loads(original_gold), actual, policy)
        new_result = evaluate(expected, actual, policy)
        destination = output / case
        destination.mkdir()
        parsed = parse_candidate(
            raw.decode(), problem_id=case, source_sha256=frozen["image_sha256"],
            registry_snapshot=frozen["registry_snapshot"],
            registered_families=[expected["family_id"]] if expected["family_id"] else [],
            store=ExtractionArtifactStore(destination / "artifacts"),
        )
        match_correct = all(actual[k] == expected[k] for k in ("match_status", "family_id"))
        row = {
            "original_live_passed": entry["live_passed"],
            "original_gold_offline_passed": old_result["ok"] and parsed["contract_valid"] and match_correct,
            "revised_gold_offline_passed": new_result["ok"] and parsed["contract_valid"] and match_correct,
            "original_parse_issues": len(json.loads((source / "parsed.json").read_text())["reports"]["ir"]["issues"]),
            "current_parse_issues": parsed["reports"]["ir"]["issues"],
            "continuation": parsed["continuation"],
            "raw_sha256": entry["raw_sha256"],
            "previous_gold_sha256": entry["gold_sha256"],
            "current_gold_sha256": revision["cases"][case]["sha256"],
        }
        results[case] = row
        for name, value in (("parsed", parsed), ("original-gold-comparison", old_result), ("revised-gold-comparison", new_result), ("summary", row)):
            dump(destination / (name + ".json"), value)
        (destination / "original-gold.json").write_bytes(original_gold)
        (destination / "revised-gold.json").write_bytes(current_gold)
    result = {
        "offline_replay_only": True, "network_calls": 0,
        "new_prompt_live_validated": False, "gold_revision": revision["revision"],
        "original_live_passed": sum(r["original_live_passed"] for r in results.values()),
        "original_gold_offline_passed": sum(r["original_gold_offline_passed"] for r in results.values()),
        "revised_gold_offline_passed": sum(r["revised_gold_offline_passed"] for r in results.values()),
        "total": len(results), "results": results,
        "template_files": {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in TEMPLATE_FILES},
        "implementation_files": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "server/shuxueshuo_server/problem_understanding").glob("*.py"))},
    }
    dump(output / "summary.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("results", "template_files", "implementation_files")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
