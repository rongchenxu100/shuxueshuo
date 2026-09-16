"""Offline audit of saved responses. No provider creation or network calls."""

import argparse
import json
from hashlib import sha256
from html import escape
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

from .candidate_common import strict_json
from .notation_contract import schema
from .notation_semantics import evaluate
from .notation_service import parse_candidate


def replay(batch, output):
    batch, output = Path(batch).resolve(), Path(output).resolve()
    summary = json.loads((batch / "batch-summary.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    results, sections = {}, []
    for case in summary["cases"]:
        source = batch / case
        raw = (source / "raw-response.txt").read_text()
        actual = strict_json(raw)
        fixture = source / "input-fixture"
        expected = json.loads((fixture / "gold.json").read_text())
        policy_file = fixture / "acceptance-policy.json"
        policy = json.loads(policy_file.read_text()) if policy_file.exists() else None
        frozen = json.loads((source / "frozen.json").read_text())
        assert (
            sha256((fixture / "gold.json").read_bytes()).hexdigest()
            == frozen["gold_sha256"]
        )
        case_dir = output / case
        case_dir.mkdir()
        # Match correctness is checked against the frozen gold below; use its
        # family here only for the generic match declaration validator.
        parsed = parse_candidate(
            raw,
            problem_id=case,
            source_sha256=frozen["image_sha256"],
            registry_snapshot=frozen["registry_snapshot"],
            registered_families=[expected["family_id"]]
            if expected["family_id"]
            else [],
            store=ExtractionArtifactStore(case_dir / "artifacts"),
        )
        comparison = evaluate(expected, actual, policy)
        match_correct = all(
            actual[k] == expected[k] for k in ("match_status", "family_id")
        )
        call = json.loads((source / "call.json").read_text())
        row = {
            "offline_replay_only": True,
            "live_passed": summary["results"][case]["passed"],
            "replay_passed": parsed["contract_valid"]
            and comparison["ok"]
            and match_correct,
            "json_schema_valid": Draft202012Validator(schema()).is_valid(actual),
            "match_correct": match_correct,
            "original_parse_issues": len(
                json.loads((source / "parsed.json").read_text())["reports"]["ir"][
                    "issues"
                ]
            ),
            "replay_parse_issues": len(parsed["reports"]["ir"]["issues"]),
            "continuation": parsed["continuation"],
            "elapsed_seconds": summary["results"][case]["elapsed_seconds"],
            "usage": call["usage"],
            "finish_reason": call["finish_reason"],
            "raw_response_sha256": sha256(raw.encode()).hexdigest(),
            "frozen_request_sha256": frozen["request_hash"],
            "request_contract": frozen["output_contract"],
        }
        results[case] = row
        for name, value in (
            ("parsed", parsed),
            ("comparison", comparison),
            ("summary", row),
        ):
            (case_dir / (name + ".json")).write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            )
        sections.append(
            "<section><h2>"
            + escape(case)
            + "</h2><p>真实批次："
            + ("通过" if row["live_passed"] else "失败")
            + "；离线回放："
            + ("通过" if row["replay_passed"] else "失败")
            + "；耗时："
            + str(row["elapsed_seconds"])
            + " 秒</p>"
            + "<h3>模型实际输出</h3><pre>"
            + escape(json.dumps(actual, ensure_ascii=False, indent=2))
            + "</pre>"
            + "<details><summary>当前解析问题</summary><pre>"
            + escape(
                json.dumps(
                    parsed["reports"]["ir"]["issues"], ensure_ascii=False, indent=2
                )
            )
            + "</pre></details><details><summary>阻断状态</summary><pre>"
            + escape(json.dumps(parsed["continuation"], ensure_ascii=False, indent=2))
            + "</pre></details></section>"
        )
    result = {
        "offline_replay_only": True,
        "network_calls": 0,
        "source_batch": str(batch),
        "live_passed": summary["passed"],
        "replay_passed": sum(r["replay_passed"] for r in results.values()),
        "implementation_files": {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        "results": results,
    }
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "outputs.html").write_text(
        '<!doctype html><html lang="zh"><meta charset="utf-8"><title>七题数学字符串抽取：实际输出</title>'
        "<style>body{font:16px/1.65 system-ui;max-width:980px;margin:40px auto;padding:0 24px;color:#17243a}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:18px;border-radius:8px}section{border-top:2px solid #ddd;margin:32px 0}summary{cursor:pointer}</style>"
        f"<h1>模型实际输出与离线回放</h1><p>真实批次 {result['live_passed']}/{len(results)} 通过；当前离线回放 {result['replay_passed']}/{len(results)} 通过。以下展示保存的完整返回及后续离线校验，不含新的模型调用。候选尚未接入 Solver。</p>"
        + "".join(sections)
        + "</html>"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.batch, args.output)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("results", "implementation_files")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
