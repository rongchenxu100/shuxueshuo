"""Authoring-only recorded solve -> student lesson -> declarative diagrams -> HTML."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

SERVER = Path(__file__).resolve().parents[1]
ROOT = SERVER.parent
sys.path.insert(0, str(SERVER))
from run_basic_inequality_stage4a import RecordedClient
from run_basic_inequality_stage4a import run as solve
from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.basic_inequality_teaching import (
    lesson_key_point,
)
from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.lesson_ir import LessonAuthoringPipeline
from shuxueshuo_server.solver.explanation.scope_lesson import (
    ScopeLessonAuthoringService,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.student_display import student_math_display
from shuxueshuo_server.solver.visual import (
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def build(
    *, output, mode="deterministic", content=None, rule_registry=None, case="q01"
):
    if case not in {"q01", "q03", "q07", "q08"}:
        raise ValueError("page case outside admitted representative fixtures")
    if rule_registry is None:
        from shuxueshuo_server.solver.explanation.amgm_sequence_rule import (
            sequence_rule_registry,
        )

        rule_registry = sequence_rule_registry()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    result, runtime = solve(
        gold=SERVER
        / f"tests/solver/fixtures/math-notation-v1/basic-inequality/{case}.json",
        problem_ir=SERVER
        / f"tests/solver/fixtures/basic-inequality-problem-ir/v1/{case}/problem-ir.json",
        output=output / "solver",
        mode="recorded",
        plan=(
            ROOT
            / "internal/functional-plan-fixtures/basic-inequality-q01-stage4b.functional-plan.json"
            if case == "q01"
            else SERVER / f"tests/solver/fixtures/basic-inequality-stage4/{case}.json"
        ),
    )
    if result.status != "ok":
        raise ValueError("recorded solve failed; see solver/result.json")
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    write(output / "snapshot.json", snapshot.to_payload())
    original = AnnotatedTeachingPlanProjector().project(snapshot)
    write(output / "method-draft.json", original.plan.to_payload())
    projection = AnnotatedTeachingPlanProjector(rule_registry=rule_registry).project(
        snapshot
    )
    write(output / "rule-draft.json", projection.plan.to_payload())
    write(output / "teaching-authority.json", projection.authority)
    service = None
    if mode != "deterministic":
        if mode == "recorded":
            if content is None:
                raise ValueError("recorded mode requires --content")
            client = RecordedClient(Path(content).read_text())
        elif mode == "deepseek":
            config = SolverRuntimeConfig.from_sources(
                planner_mode="strategy", llm_provider="deepseek"
            )
            client = config.build_llm_client(thinking_effort="disabled")
        else:
            raise ValueError("unknown lesson mode")
        service = ScopeLessonAuthoringService(
            client=client, rule_registry=rule_registry
        )
    built = LessonAuthoringPipeline(
        authoring_service=service, rule_registry=rule_registry
    ).build(snapshot)
    write(output / "lesson-ir.json", built.lesson.to_payload())
    write(output / "lesson-validation.json", built.validation.to_payload())
    write(output / "scope-content.json", built.validation.accepted_content)
    if built.generation:
        g = built.generation
        write(output / "lesson-projection-audit.json", g.projection_audit)
        write(
            output / "lesson-request.json",
            {"messages": g.prompt.messages, "output_schema": g.output_schema},
        )
        (output / "lesson-response.txt").write_text(g.raw_response)
        write(output / "lesson-call-metadata.json", g.metadata_payload())
        for attempt in g.transport_attempts:
            write(
                output / attempt.reasoning_debug_filename,
                attempt.reasoning_debug_payload(),
            )
            (
                output
                / f"transport-attempt-{attempt.transport_attempt:02d}.response.txt"
            ).write_text(attempt.raw_response)
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=built.lesson)
    write(output / "visual-step-ir.json", visual.to_payload())
    VisualStepIRValidator().validate(visual, lesson=built.lesson)
    write(
        output / "visual-binding-audit.json",
        {
            "steps": [
                {"lesson_step_id": s.lesson_step_id, "diagrams": list(s.diagram_blocks)}
                for s in visual.steps
            ],
            "gaps": visual.metadata.get("visual_gaps", []),
        },
    )
    if visual.metadata.get("visual_gaps"):
        raise ValueError(
            "required teaching visual missing; see visual-binding-audit.json"
        )
    compiled = forward_compile(visual)
    data = compiled.lesson_data
    data["meta"].update(
        id=snapshot.problem_id,
        pageTitle="基本不等式 · "
        + (
            "求最大值"
            if "maximum" in next(iter(snapshot.answers.values()))
            else "求最小值"
        ),
        generatedFromSolver=True,
        outputPath="site/generated/inequality.html",
    )
    data["problem"]["answerText"] = "；".join(
        student_math_display(v)
        for values in snapshot.answers.values()
        for v in values.values()
    )
    data["problem"]["source"] = ""
    data["problem"]["lines"] = [
        {"text": line} for line in snapshot.problem["original_text"]
    ]
    data["meta"]["breadcrumbTitle"] = "基本不等式"
    data["problem"]["keyPoints"] = {
        "items": [lesson_key_point(step, snapshot) for step in built.lesson.steps]
    }
    write(
        output / "visual-version-manifest.json",
        {
            "specs": sorted(
                {
                    (block["spec_id"], block["spec_version"])
                    for step in visual.steps
                    for block in step.diagram_blocks
                }
            ),
            "components": sorted(
                {
                    (block["component_id"], block["component_version"])
                    for step in visual.steps
                    for block in step.diagram_blocks
                }
            ),
            "snapshot_schema": snapshot.to_payload().get("schema_version"),
            "visual_schema": visual.schema_version,
        },
    )
    from shuxueshuo_server.solver.explanation.math_typography import typeset_lesson_data
    data = typeset_lesson_data(data)
    write(output / "lesson-data.json", data)
    write(output / "geometry-spec.json", compiled.geometry_spec)
    write(output / "step-decorations.json", compiled.step_decorations)
    completed = subprocess.run(
        [
            "node",
            str(ROOT / "tools/build-text-page.mjs"),
            str(output),
            "--output",
            str(output / "lesson.html"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    (output / "compile.log").write_text(completed.stdout + completed.stderr)
    completed.check_returncode()
    summary = {
        "mode": mode,
        "steps": len(built.lesson.steps),
        "page": str(output / "lesson.html"),
        "elapsed_seconds": round(perf_counter() - started, 3),
        "lesson": built.generation.metadata_payload()
        if built.generation
        else {"provider_calls": 0, "fallback_used": False},
    }
    write(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=["deterministic", "recorded", "deepseek"],
        default="deterministic",
    )
    parser.add_argument("--content", type=Path)
    parser.add_argument("--case", choices=["q01", "q03", "q07", "q08"], default="q01")
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                output=args.output, mode=args.mode, content=args.content, case=args.case
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
