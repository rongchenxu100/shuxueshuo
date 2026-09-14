"""Isolated rational-rewrite experiment; never marks the extremum goal solved.

This prefix harness uses the registered executor and state allocator. It is not
a new Family or a replacement for the full Functional transactional interpreter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from copy import deepcopy
from dataclasses import asdict, is_dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .explanation.expression_rewrite import build_rewrite_lesson
from .explanation.models import ExplanationSnapshot, TeachingTraceEntry
from .family.expression_rewrite import ORGANIZE_EXPRESSIONS_CONTRACT
from .math_kernel import SympyKernel
from .math_kernel.expression_rewrite import parse_expression, parse_relation
from .problem_models import ProblemIR
from .runtime.context import RuntimeContext
from .runtime.executor import InvocationExecutor
from .runtime.function_specs import function_spec_from_method
from .runtime.method_specs import MethodSpecRegistry
from .runtime.methods.organize_expressions import PARAMETERS_SCHEMA, PROMPT
from .runtime.models import MethodInvocation, TypedValue
from .runtime.state_identity import (
    ArgVersionBinding,
    ComputationKey,
    IndexedStateVersion,
    LogicalReturnEffect,
    LogicalStateKey,
    MathObjectId,
    ScopeVisibilityResolver,
    StateAllocationRequest,
    StateAllocationService,
    StateEffectKey,
    StateIdentityIndex,
    StateSlotId,
    StateVersionId,
)
from .visual.text_builder import build_text_method_visual

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
FIXTURE = ROOT / "tests/solver/fixtures/expression_rewrite/q08.json"


class _RootScope:
    def ancestor_scopes(self, scope):
        return (scope,) if scope == "problem" else (scope, "problem")


class RewriteExperiment:
    """Small prefix test host for existing runtime primitives, with staged writes."""

    def __init__(self, fixture):
        self.fixture = deepcopy(fixture)
        kernel = SympyKernel()
        symbols = kernel.symbols(fixture["symbols"])
        problem = ProblemIR(
            fixture["problem_id"], "rational_rewrite", "text", fixture["symbols"]
        )
        self.context = RuntimeContext(problem, kernel, symbols)
        self.context.write_path(
            "$problem.outputs.target_expression",
            TypedValue(
                "Expression", parse_expression(fixture["expression"], symbols).value
            ),
            from_scope_id="problem",
        )
        for name, value in fixture["conditions"].items():
            self.context.write_path(
                f"$problem.constraints.{name}",
                TypedValue("Condition", parse_relation(value, symbols)),
                from_scope_id="problem",
            )
        self.specs = MethodSpecRegistry.load_from_code()
        self.function = function_spec_from_method(
            self.specs.require("organize_expressions"),
            contract=ORGANIZE_EXPRESSIONS_CONTRACT,
            adapter=None,
        )
        self.object_id = MathObjectId("target_expression", "expression", "problem")
        self.logical = LogicalStateKey(self.object_id, "expression", "Expression")
        self.index = StateIdentityIndex(ScopeVisibilityResolver(_RootScope()))
        initial = StateVersionId(StateSlotId(self.logical, "problem"), 0)
        self.index.register(
            IndexedStateVersion(initial, "problem", None, "target_expression")
        )
        self.goal_solved = False

    def execute(self, call):
        if (
            set(call) != {"step_id", "capability_id", "args", "parameters"}
            or call["capability_id"] != "organize_expressions"
        ):
            raise ValueError("调用协议不匹配")
        if call["args"].get("expression") != "target_expression" or set(
            call["args"]
        ) != {"expression", "conditions"}:
            raise ValueError("表达式必须绑定 target_expression")
        names = call["args"]["conditions"]
        if (
            not isinstance(names, list)
            or len(set(names)) != len(names)
            or any(n not in self.fixture["conditions"] for n in names)
        ):
            raise ValueError("条件绑定不存在或重复")
        current = self.index.latest_visible(self.logical, consumer_scope_id="problem")
        digest = hashlib.sha256(
            json.dumps(call["parameters"], sort_keys=True).encode()
        ).hexdigest()
        key = ComputationKey(
            "organize_expressions",
            (
                ArgVersionBinding("expression", 0, current.version_id),
                *(
                    ArgVersionBinding("conditions", i, condition_id=name)
                    for i, name in enumerate(names)
                ),
            ),
            digest,
        )
        effect = StateEffectKey(
            (
                LogicalReturnEffect(
                    "organized_expression",
                    self.logical,
                    "preserve_input_object",
                    "transition",
                ),
            )
        )
        decision = StateAllocationService().allocate(
            StateAllocationRequest(
                call_id=call["step_id"],
                capability_id=call["capability_id"],
                return_name="organized_expression",
                object_id=self.object_id,
                state_kind="expression",
                runtime_type="Expression",
                storage_scope_id="problem",
                valid_scope_id="problem",
                requested_write_mode="transition",
                identity_policy="preserve_input_object",
                is_shareable=False,
                computation_key=key,
                state_effect_key=effect,
                source_version_ids=(current.version_id,),
            ),
            self.index,
        )
        if decision.selected_version_id is None or decision.conflict_code:
            raise ValueError(f"状态分配失败: {decision.to_payload()}")
        branch = self.context.fork()
        scope = call["step_id"]
        branch.ensure_step_scope(scope, "problem")
        destination = f"$step.{scope}.outputs.organized_expression"
        invocation = MethodInvocation(
            invocation_id=scope,
            method_id="organize_expressions",
            scope=scope,
            inputs={
                "expression": "$problem.outputs.target_expression",
                "conditions": tuple(f"$problem.constraints.{n}" for n in names),
            },
            outputs={"organized_expression": destination},
            parameters=deepcopy(call["parameters"]),
        )
        executor = InvocationExecutor(self.specs, kernel=branch.kernel)
        executor.validator.validate_invocation(branch, invocation)
        result = executor.execute_invocation(branch, invocation)
        branch.write_path(
            "$problem.outputs.target_expression",
            result.outputs["organized_expression"],
            from_scope_id="problem",
            allow_overwrite=True,
        )
        staged_index = self.index.clone()
        version = IndexedStateVersion(
            decision.selected_version_id,
            "problem",
            scope,
            "target_expression",
            computation_key=key,
            state_effect_key=effect,
            previous_version_id=current.version_id,
            source_version_ids=(current.version_id,),
        )
        staged_index.register(version)
        # Publish only after the whole Method and final-state allocation succeed.
        self.context, self.index = branch, staged_index
        return {
            "call": deepcopy(call),
            "output": str(result.outputs["organized_expression"].value),
            "checks": [{"name": c.name, "ok": c.ok} for c in result.checks],
            "trace": result.trace_fragments[0],
            "committedVersion": version.to_payload(),
            "allocation": decision.to_payload(),
            "goalSolved": self.goal_solved,
            "executionMode": "isolated_prefix_executor_and_state_allocator",
        }


def save_json(path, value):
    def encode(item):
        import sympy as sp

        if hasattr(item, "to_payload"):
            return item.to_payload()
        if is_dataclass(item):
            return asdict(item)
        if isinstance(item, sp.Basic):
            return str(item)
        raise TypeError(f"Cannot serialize {type(item).__name__}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n",
        encoding="utf-8",
    )


def execute_record(fixture, call):
    from .expression_rewrite_transaction import execute_rewrite_transaction

    report = execute_rewrite_transaction(fixture, call)
    if len(report.call_results) != 1 or report.call_results[0].status != "verified":
        raise ValueError(
            [
                i.to_payload()
                for result in report.call_results
                for i in result.root_issues
            ]
        )
    result = report.call_results[0]
    return {
        "call": deepcopy(call),
        "output": str(result.runtime_results[0].value),
        "checks": [{"name": c.name, "ok": c.ok} for c in result.step_results[0].checks],
        "trace": result.step_results[0].trace_fragments[0],
        "committedVersion": report.committed_versions[0].to_payload(),
        "allocation": result.state_writes[0].to_payload(),
        "goalSolved": False,
        "executionMode": "functional_transactional_interpreter",
        "transaction": report.to_payload(),
    }


def generate_preview(record, fixture, directory, output_path):
    trace = deepcopy(record["trace"])
    for card in trace["conditionCards"]:
        card.pop("source", None)
    call_id = record["call"]["step_id"]
    snapshot = ExplanationSnapshot(
        problem_id=fixture["problem_id"],
        family_id="rewrite_prefix_experiment",
        problem={
            "conditions": fixture["conditions"],
            "expression": fixture["expression"],
        },
        effective_steps=(
            {
                "step_id": call_id,
                "scope_id": "problem",
                "goal_type": "organize_expressions",
            },
        ),
        teaching_trace=(
            TeachingTraceEntry(
                trace_id=call_id + ":trace",
                source_step_id=call_id,
                scope_id="problem",
                capability_id="organize_expressions",
                method_id="organize_expressions",
                trace_fragments=(trace,),
            ),
        ),
        fact_index={},
        checks=tuple(record["checks"]),
    )
    method_spec = MethodSpecRegistry.load_from_code().require("organize_expressions")
    ir = build_rewrite_lesson(snapshot, method_spec)
    step = ir.steps[0]
    visual = build_text_method_visual(
        snapshot=snapshot, lesson_step=step, method_spec=method_spec
    )
    student = {
        "id": step.id,
        "section": "整理式子",
        "title": visual["title"],
        "t": 0,
        "showDiagram": False,
        "derive": [list(line) for line in step.derive],
        "box": list(step.box),
        "visual": visual,
    }
    lesson = {
        "meta": {
            "id": fixture["problem_id"],
            "pageTitle": "q08 · 整理式子实验（仅演示整理步骤）",
            "outputPath": output_path,
        },
        "problem": {
            "lines": [
                "仅演示整理步骤，不是完整求最小值的解答。",
                "条件："
                + "，".join(
                    "\\(" + record["trace"]["conditionCards"][i]["latex"] + "\\)"
                    for i in range(len(record["trace"]["conditionCards"]))
                ),
                "原目标：\\(" + record["trace"]["source"]["latex"] + "\\)",
            ]
        },
        "steps": [student],
    }
    save_json(directory / "execution.json", record)
    save_json(directory / "explanation-snapshot.json", snapshot.to_payload())
    save_json(directory / "lesson-ir.json", ir.to_payload())
    save_json(directory / "student-steps.json", [student])
    save_json(directory / "visual-spec.json", student["visual"])
    save_json(directory / "lesson-data.json", lesson)
    subprocess.run(
        ["node", str(REPO / "tools/build-text-page.mjs"), str(directory)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )


def live_batch(fixture, directory):
    from .runtime.config import SolverRuntimeConfig

    config = SolverRuntimeConfig.from_sources()
    if config.llm_provider == "recorded":
        config = replace(config, llm_provider="deepseek")
    batch = directory / datetime.now(UTC).strftime("batch-%Y%m%dT%H%M%S%fZ")
    batch.mkdir(parents=True, exist_ok=False)
    prompt = {
        "instruction": PROMPT,
        "problem": {
            "conditions": fixture["conditions"],
            "expression": fixture["expression"],
            "objective": "求最小值；本次仅整理，不应用不等式",
        },
        "bindingCatalog": {
            "target_expression": {"type": "Expression", "math": fixture["expression"]},
            **{
                k: {"type": "Condition", "math": v}
                for k, v in fixture["conditions"].items()
            },
        },
        "responseShape": {
            "step_id": "rewrite_1",
            "capability_id": "organize_expressions",
            "args": {
                "expression": "target_expression",
                "conditions": list(fixture["conditions"]),
            },
            "parameters": "必须满足 parametersSchema 的对象",
        },
        "parametersSchema": PARAMETERS_SCHEMA,
    }
    save_json(batch / "prompt.json", prompt)
    samples = []
    try:
        config.build_llm_client()
    except Exception as exc:  # noqa: BLE001 -- persist experiment configuration failures
        save_json(
            batch / "report.json",
            {
                "status": "blocked_configuration",
                "requestedSamples": 5,
                "executedRequests": 0,
                "samples": [],
                "error": str(exc),
            },
        )
        print(f"真实测试未执行：{exc}；报告：{batch}", flush=True)
        return
    for i in range(5):
        client = config.build_llm_client()
        started = time.monotonic()
        item = {
            "sample": i + 1,
            "provider": config.llm_provider,
            "configuredModel": client.model,
            "protocolParsed": False,
            "mathVerified": False,
            "specializedClassification": False,
            "frontendGenerated": False,
        }
        try:
            raw = client.complete(
                {
                    "messages": [
                        {"role": "system", "content": "只输出一个严格 JSON 调用对象。"},
                        {
                            "role": "user",
                            "content": json.dumps(prompt, ensure_ascii=False),
                        },
                    ]
                }
            )
            item["rawResponse"] = raw
            call = json.loads(raw)
            item["protocolParsed"] = True
            record = execute_record(fixture, call)
            item["mathVerified"] = True
            item["operations"] = [
                t["operation"] for t in record["trace"]["transitions"]
            ]
            item["specializedClassification"] = (
                record["trace"]["teachingEffect"]
                == "combine_fractions_revealing_condition"
            )
            generate_preview(
                record,
                fixture,
                batch / f"sample-{i + 1}",
                f"site/previews/q08-rewrite/{batch.name}/sample-{i + 1}.html",
            )
            item["frontendGenerated"] = True
        except Exception as exc:  # noqa: BLE001 -- retain every failed independent sample
            item["error"] = str(exc)
        item.update(
            {
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "actualModel": client.last_response_model,
                "usage": client.last_usage,
                "providerAttempts": list(client.last_provider_attempts),
            }
        )
        samples.append(item)
        save_json(batch / f"sample-{i + 1}.json", item)
        save_json(
            batch / "report.json",
            {"samples": samples, "sampleCount": 5, "noRepairRetries": True},
        )
        print(
            json.dumps(
                {
                    k: v
                    for k, v in item.items()
                    if k not in {"rawResponse", "providerAttempts"}
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    print(str(batch), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    fixture = json.loads(FIXTURE.read_text())
    directory = REPO / "internal/experiments/organize-expressions-q08"
    if args.live:
        live_batch(fixture, directory / "live")
    else:
        record = execute_record(fixture, fixture["call"])
        generate_preview(
            record,
            fixture,
            directory / "deterministic",
            "site/previews/inequality-basic-q08-organize.html",
        )
        print(directory / "deterministic")


if __name__ == "__main__":
    main()
