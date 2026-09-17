"""Deterministic stage-two acceptance and compact-input review artifacts.

Run from server: PYTHONPATH=. python tools/replay_math_runtime_binding.py --output DIR
Uses test-side trusted-plan rebinding and expected answers only for assertions.
No provider, source review, product admission, deployment or Planner call runs.
"""

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/tests/solver"))

from _math_runtime_binding_support import (
    CASES,
    assert_expected,
    candidate,
    execution_audit,
    replay,
    replay_errors,
    trusted_plan,
)
from _problem_planning_support import cached_planning_binding_fixture
from shuxueshuo_server.problem_understanding.compact_planner_input import (
    compact_methods,
    compact_problem,
    coverage,
)
from shuxueshuo_server.problem_understanding.runtime_binding import (
    bind_notation,
)
from shuxueshuo_server.product.runtime_binding import configuration
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
)


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def baseline(case):
    _, context, _, inputs, problem, _, state, catalog = cached_planning_binding_fixture(
        case
    )
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_scoped(
        inputs,
        problem_payload=problem,
        planner_state_context=state,
        problem_planning_context=context,
        problem_binding_catalog=catalog,
    )
    return payload["problem_planning_context"], payload["functional_capability_catalog"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    checks = []
    rows = []
    for case in CASES:
        old, old_methods = baseline(case)
        case_dir = output / case
        save(case_dir / "existing-problem.json", old)
        save(case_dir / "existing-methods.json", old_methods)
        for authored in (False, True):
            origin = "authored" if authored else "recorded"
            raw = candidate(case, authored)
            image = (
                ROOT
                / "server/tests/solver/fixtures/math-notation-v1/integration-images-20260916"
                / f"{case}.png"
            )
            bound = bind_notation(
                raw,
                problem_id=case,
                candidate_id="offline:" + sha256(wire(raw).encode()).hexdigest(),
                source_version_id="frozen:" + image.name,
                source_hash=sha256(image.read_bytes()).hexdigest(),
            )
            with TemporaryDirectory(prefix="notation-replay-") as tmp:
                result = replay(case, bound, Path(tmp))
            assert result.status == "accepted", replay_errors(result)
            assert_expected(case, bound, result)
            artifacts = bound.artifacts()
            compact = compact_problem(bound)
            methods = compact_methods(bound)
            artifacts.update(
                {
                    "source-notation.json": raw,
                    "compact-problem.json": compact,
                    "compact-methods.json": methods,
                    "coverage.json": coverage(bound),
                    "execution-audit.json": execution_audit(bound, result),
                    "rebound-plan.json": trusted_plan(case, bound),
                }
            )
            target = case_dir / origin
            for name, value in artifacts.items():
                save(target / name, value)
            (target / "compact-problem.compact.json").write_text(wire(compact) + "\n")
            # Save a local example with verified results and ancestor-only visibility.
            save(
                target / "local-input-after-replay.json",
                compact_problem(
                    bound,
                    scope_path=(len(raw["root"]["children"]) - 1,),
                    execution=result.verified_execution,
                ),
            )
            original_plan = (
                ROOT
                / "internal/functional-plan-v2-fixtures"
                / f"{case}.functional-plan.json"
            )
            check = {
                "case": case,
                "origin": origin,
                "status": "accepted",
                "answers_match": True,
                "goals": len(bound.planning_context.goal_views),
                "source_identity": dict(bound.source_identity),
                "trusted_plan_sha256": sha256(original_plan.read_bytes()).hexdigest(),
                "steps": len(artifacts["execution-audit.json"]["steps"]),
                "versions": len(
                    artifacts["execution-audit.json"]["committed_versions"]
                ),
                "evidence_kind": "frozen_input_replay_with_synthetic_test_authority",
                "current_product_admission": False,
            }
            checks.append(check)
            print(case, origin, "accepted", flush=True)
            if not authored:
                stats = {
                    "case": case,
                    "problem": {
                        "old_characters": len(wire(old)),
                        "new_characters": len(wire(compact)),
                    },
                    "methods": {
                        "old_characters": len(wire(old_methods)),
                        "new_characters": len(wire(methods)),
                    },
                    "token_count": None,
                    "token_reason": "No matching DeepSeek tokenizer; no model call.",
                    "scope": "JSON problem and method sections measured separately; not a full request ratio.",
                }
                save(case_dir / "size-statistics.json", stats)
                rows.append(stats)
    report = {
        "schema_version": "math-runtime-stage-two-report/v1",
        "binding_configuration": configuration(),
        "checks": checks,
        "statistics": rows,
        "model_calls": 0,
        "product_admissions": 0,
        "note": "Historical confirmed reviews remain historical. Runtime readiness in the product requires a current persisted review and admission run.",
    }
    save(output / "report.json", report)
    lines = [
        "# 阶段二冻结证据回放与简洁输入审阅",
        "",
        "十组回放全部通过：五题人工样例、五题冻结真实候选。逐目标核对答案和全部合法分支，并检查实际输入、提交状态版本与来源作用域。",
        "",
        "**本目录是离线回放证据，不是当前产品准入结果。** 回放使用测试侧的合成授权；历史 `confirmed` 没有被改写为当前复核。当前产品检查由页面按钮或 API 单独触发。无模型调用。",
        "",
        "旧输入由当前生产 `StrategyPayloadBuilder.build_scoped()` 生成；新输入由本次代码生成器生成。运行时适配只读取新候选，旧 fixture 只用于旧输入对照、计划选择与答案断言。",
        "",
        "| 题目 | 旧题目字符 | 新题目字符 | 题目段减少 | 审阅文件 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        p = row["problem"]
        case = row["case"]
        links = f"[旧输入]({case}/existing-problem.json) · [新输入]({case}/recorded/compact-problem.json) · [方法]({case}/recorded/compact-methods.json) · [覆盖]({case}/recorded/coverage.json) · [回放]({case}/recorded/execution-audit.json)"
        lines.append(
            f"| {case} | {p['old_characters']:,} | {p['new_characters']:,} | {1 - p['new_characters'] / p['old_characters']:.1%} | {links} |"
        )
    lines.extend(
        [
            "",
            '字符数统一使用 `json.dumps(ensure_ascii=False, separators=(",", ":"), sort_keys=True)` 的 Unicode 字符数。只比较题目段，不能据此声称整个请求的压缩比例。每题方法段体积另存 `size-statistics.json`。无匹配 tokenizer，token 保持 null。',
            "",
            "每题 `recorded/` 与 `authored/` 均包含原候选、编译对象/关系、canonical input、初始状态、来源映射、简洁输入、方法签名、覆盖清单和受信计划的执行审计。`local-input-after-replay.json` 展示当前问及祖先条件和已提交的可见结果。",
            "",
            "南开旧计划把最值步骤放在父问；新候选仅在两个子问声明最值。测试侧保留方法和数学选择，在两个子问分别绑定该步骤，未把子问条件提升到父问。",
            "",
            "方法签名的参数与返回值来自执行能力注册表；数学前提由同一能力 ID 的数学说明补充。它们是审阅文档，尚不是新的可执行步骤语言。",
            "",
            "复现：在 `server` 执行 `PYTHONPATH=. .venv/bin/python tools/replay_math_runtime_binding.py --output ../docs/validation/math-runtime-binding-stage-two-20260917`。",
        ]
    )
    (output / "README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
