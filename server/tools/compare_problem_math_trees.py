"""Freeze and compare legacy/notation trees; never invokes an LLM or Solver plan.

Run from server: PYTHONPATH=. python tools/compare_problem_math_trees.py --output DIR
Exit 0 means the audit completed, not that the inputs are equivalent. Use
--require-equivalent for a migration gate (exit 1 for any unresolved difference).
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from hashlib import sha256
from pathlib import Path

import sympy as sp

from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.math_tree_audit import (
    build_math_tree,
    compare_math_trees,
    display_ast,
    scopes,
)
from shuxueshuo_server.problem_understanding.notation_contract import TEMPLATE_FILES
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def freeze_runtime(value):
    if isinstance(value, sp.Basic):
        return {"expression": sp.sstr(value), "structural_expression": sp.srepr(value)}
    if is_dataclass(value):
        return {
            "class": type(value).__name__,
            **{f.name: freeze_runtime(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, Mapping):
        return {str(k): freeze_runtime(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [freeze_runtime(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported runtime snapshot value: {type(value).__name__}")


def runtime_snapshot(problem):
    # This is the actual existing builder, not a reproduction of its objects.
    context = ContextBuilder().build(problem)
    payload = problem_to_llm_payload(problem)
    state = initial_planner_state_context(
        build_strategy_probe_inputs(problem),
        problem_payload=payload,
        handle_registry=CanonicalHandleRegistry.from_problem_payload(payload),
    ).state.to_payload()
    return {
        "scope_graph": state["scope_graph"],
        "math_objects": state["math_objects"],
        "conditions": state["conditions"],
        "state_slots": state["state_slots"],
        "runtime_scope_ids": list(context.scopes),
        "runtime_values": {
            name: freeze_runtime(scope) for name, scope in context.scopes.items()
        },
        "runtime_bound": True,
    }


def tree_text(snapshot):
    if not snapshot.get("raw_tree", {}).get("scope"):
        return (
            "INVALID INPUT\n"
            + json.dumps(snapshot.get("issues", []), ensure_ascii=False, indent=2)
            + "\n"
        )
    rows = []
    objects = snapshot.get("raw_objects", [])
    for scope in scopes(snapshot["raw_tree"]):
        rows.append(f"{scope['scope']}\n")
        for obj in objects:
            if obj["scope"] == scope["scope"]:
                rows.append(f"  object {obj['kind']} {obj['name']} [{obj['ref']}]\n")
        for fact in scope["facts"]:
            rows.append(f"  fact {display_ast(fact)}\n")
        for goal in scope["goals"]:
            rows.append(f"  goal {goal['kind']}: {display_ast(goal['target'])}\n")
            for field in ("variables", "in_terms_of"):
                if field in goal:
                    rows.append(
                        f"    {field}: {json.dumps(goal[field], ensure_ascii=False)}\n"
                    )
    return "".join(rows)


def readable_difference(difference, snapshots):
    text = json.dumps(difference, ensure_ascii=False, indent=2)
    atoms = {k: v for s in snapshots for k, v in s.get("atoms", {}).items()}
    for code, value in atoms.items():
        text = text.replace("n_" + code, display_ast(value))
    return text


def run(output, *, cases=CASES, notation_dir=None, workflow_batch=None):
    if notation_dir is not None and workflow_batch is not None:
        raise ValueError("choose notation_dir or workflow_batch, not both")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    workflow_batch = Path(workflow_batch) if workflow_batch is not None else None
    notation_dir = (
        Path(notation_dir)
        if notation_dir
        else ROOT / "server/tests/solver/fixtures/math-notation-v1"
    )
    # The other task may edit the parser. Hash before and after; don't silently
    # present a report built while its implementation changed.
    package = ROOT / "server/shuxueshuo_server/problem_understanding"
    source_files = sorted(package.glob("*.py")) + [Path(__file__), *TEMPLATE_FILES]
    source_before = {str(p.relative_to(ROOT)): digest(p) for p in source_files}
    manifest = {
        "schema_version": "math-tree-audit-run/v1",
        "input_class": (
            "recorded_workflow_candidate"
            if workflow_batch is not None
            else "authored_fixture"
            if notation_dir == ROOT / "server/tests/solver/fixtures/math-notation-v1"
            else "external_candidate"
        ),
        "source_hashes": source_before,
        "cases": [],
        "llm_calls": 0,
        "new_runtime_bound": False,
        "source_correctness": "not_established",
    }
    summary = [
        "# 新旧数学对象树对照\n",
        "本报告是离线语义审计。对象或表达式一致不能代替原图正确性验证，也不表示新输入已经接通 Solver 运行时。\n",
        "|题目|旧/新命名对象|规范化对象与作用域|有界条件/目标等价|限定项差异|状态条件差异|结论|",
        "|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        directory = output / case
        directory.mkdir()
        paths = {
            "legacy": ROOT / "internal/problem-domain-fixtures" / f"{case}.json",
            "notation": (
                workflow_batch / case / "workflow/candidate.json"
                if workflow_batch is not None
                else notation_dir / f"{case}.json"
            ),
            "solver": ROOT / "internal/solver-fixtures" / f"{case}.json",
        }
        values = {}
        bindings = {}
        for kind, path in paths.items():
            raw = path.read_bytes()
            values[kind] = strict_json(raw.decode())
            bindings[kind] = {
                "path": str(path.relative_to(ROOT))
                if path.is_relative_to(ROOT)
                else str(path),
                "sha256": sha256(raw).hexdigest(),
            }
            (directory / f"input-{kind}.json").write_bytes(raw)
        old = build_math_tree(values["legacy"], format="legacy")
        new = build_math_tree(values["notation"], format="notation")
        comparison = compare_math_trees(old, new)
        validation = ProblemDomainValidator().validate(
            ProblemDraft.create(values["legacy"])
        )
        save(
            directory / "legacy-domain-validation.json", validation.report.to_payload()
        )
        if not validation.ok:
            raise ValueError(f"old domain cannot build production runtime: {case}")
        domain_runtime = runtime_snapshot(validation.projection.problem)
        fixture_runtime = runtime_snapshot(
            load_problem_ir(directory / "input-solver.json")
        )
        save(directory / "legacy-domain-runtime.json", domain_runtime)
        save(directory / "legacy-fixture-runtime.json", fixture_runtime)
        save(directory / "legacy-math-tree.json", old)
        save(directory / "notation-math-tree.json", new)
        save(directory / "comparison.json", comparison)
        (directory / "legacy-tree.txt").write_text(tree_text(old))
        (directory / "notation-tree.txt").write_text(tree_text(new))
        differences = comparison.get("differences", [])
        counts = Counter(d["category"] for d in differences)
        identity_equal = not any(
            counts[k] for k in ("scopes", "objects", "scope_count")
        )
        record = {
            "case": case,
            "inputs": bindings,
            "status": comparison["status"],
            "parse_valid": old["parse_valid"] and new["parse_valid"],
            "object_scope_equal": identity_equal
            and old["parse_valid"]
            and new["parse_valid"],
            "bounded_semantic_equivalence": comparison.get(
                "bounded_semantic_equivalence", False
            ),
            "difference_categories": dict(counts),
            "legacy_runtime_comparison": {
                "domain_objects": len(domain_runtime["math_objects"]),
                "fixture_objects": len(fixture_runtime["math_objects"]),
                "exact_snapshot_equal": domain_runtime == fixture_runtime,
            },
        }
        manifest["cases"].append(record)
        summary.append(
            f"|[{case}]({case}/README.md)|{old.get('counts', {}).get('named_objects', '?')}/{new.get('counts', {}).get('named_objects', '?')}|{'一致' if record['object_scope_equal'] else '待核对'}|{'已证明' if record['bounded_semantic_equivalence'] else '未证明'}|{counts['qualifiers']} 组|{counts['state_conditions']} 组|{comparison['status']}|"
        )
        report = [
            f"# {case}\n",
            f"结论：`{comparison['status']}`。新输入种类：`{manifest['input_class']}`。\n",
            "[旧数学树](legacy-tree.txt) · [新数学树](notation-tree.txt) · [机器差异](comparison.json) · [旧领域输入运行时树](legacy-domain-runtime.json) · [原 Solver fixture 运行时树](legacy-fixture-runtime.json)\n",
            "## 差异\n",
        ]
        for d in differences:
            report.extend(
                [
                    f"### {d['category']} {d.get('scope', '')}\n",
                    "```text",
                    readable_difference(d, (old, new)),
                    "```\n",
                ]
            )
        report.extend(
            [
                "## 边界\n",
                "所有原始输入已冻结。旧结构通过生产领域校验并构建实际初始运行时树；新结构当前建立的是数学语义审计树，尚未绑定生产 StateSlot/StateVersion。此报告不裁决哪一侧符合原图。\n",
                "曲线名称只在同一作用域恰有一个曲线时统一；原始名称与映射均保留。内部 function_variable、复合对象及 minimum_target 的表达差异保存在旧树 annotations 中。旧 Solver 目标描述不会伪装为额外数学题设。\n",
            ]
        )
        (directory / "README.md").write_text("\n".join(report))
    after = {str(p.relative_to(ROOT)): digest(p) for p in source_files}
    manifest["source_stable"] = after == source_before
    manifest["complete"] = manifest["source_stable"]
    save(output / "manifest.json", manifest)
    summary.extend(
        [
            "\n## 如何阅读\n",
            "先检查对象和作用域，再检查条件/目标及限定项。状态条件作为facts逐问比较，并在答案投影前单独保留；参数答案等价不代表原始条件树一致。最值变量和答案参数也单独保留。`needs_review` 不等于数学错误，也不允许视作迁移通过。\n",
            "现有运行时对象包含匿名几何对象、表达式、答案对象和状态槽，数量不能直接与新 JSON 的命名对象数量比较。两份旧运行时快照保留为后续生产绑定验收的基线。\n",
            f"源码稳定：`{manifest['source_stable']}`；真实 LLM 调用：0；新输入运行时绑定：未实现。\n",
        ]
    )
    (output / "README.md").write_text("\n".join(summary))
    if not manifest["source_stable"]:
        raise RuntimeError(
            "audit source changed during run; retain evidence and use a fresh output directory"
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--notation-dir", type=Path)
    inputs.add_argument(
        "--workflow-batch",
        type=Path,
        help="read CASE/workflow/candidate.json from an existing batch; no LLM calls",
    )
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--require-equivalent", action="store_true")
    args = parser.parse_args()
    result = run(
        args.output,
        cases=args.case or CASES,
        notation_dir=args.notation_dir,
        workflow_batch=args.workflow_batch,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "statuses": {x["case"]: x["status"] for x in result["cases"]},
            },
            ensure_ascii=False,
        )
    )
    return int(
        args.require_equivalent
        and any(x["status"] != "equivalent" for x in result["cases"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
