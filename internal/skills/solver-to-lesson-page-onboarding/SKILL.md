---
name: solver-to-lesson-page-onboarding
description: Use this skill after a middle-school problem already has a passing solver/runtime path and Codex needs to generate, test, or repair the student-facing lesson page pipeline: ExplanationSnapshot, LessonIR, VisualStepIR, local/linked interactions, animation beats, generated JSON artifacts, and compiled HTML. Use when failures require adding method/recipe explanation specs, visual specs, animation specs, role binders, builders, compilers, validators, or frontend runtime support.
---

# Solver To Lesson Page Onboarding

Use this skill after a problem already passes the Strategy Planner + Runtime solver path.

The goal is to turn successful runtime artifacts into a student-facing interactive lesson page:

```text
successful runtime artifacts
-> ExplanationSnapshot
-> LessonIR
-> VisualStepIR
-> interactions / animations
-> generated geometry-spec.json + step-decorations.json + lesson-data.json
-> compiled HTML
```

This skill is not just a testing checklist. If the page pipeline fails because a reusable explanation, visual, interaction, animation, builder, compiler, validator, or frontend capability is missing, add the generic capability in the existing architecture and test it.

## Preconditions

- The solver path for the problem is already passing with recorded or real DeepSeek Strategy Planner.
- `RuntimeOrchestrator.last_success_artifacts` is available from a successful solve.
- The canonical ProblemIR is the only authored problem fact source.
- Recorded executable StepIntent fixtures may be used to avoid live solver LLM calls during page tests.

Do not start from handwritten `internal/lesson-specs/<problem-id>/geometry-spec.json`, `step-decorations.json`, or `lesson-data.json` as product inputs. Those authored specs may be used only for VS0 round-trip tests or golden comparison.

## Output Contract

For a problem page onboarding, create or update the relevant tests and generated/debug artifacts for:

- `ExplanationSnapshot` from successful runtime artifacts.
- `LessonIR`, either deterministic, LLM-generated, or recorded fixture-backed.
- `VisualStepIR` generated from `ExplanationSnapshot + LessonIR`.
- VS1 static scene generation.
- VS2 local / linked controls and `pointOverrides`.
- VS3 animation beats and modal playback.
- generated `geometry-spec.json`, `step-decorations.json`, `lesson-data.json`.
- compiled HTML via repository tools.

HTML is a compiled artifact. Do not hand-write or patch generated HTML.

## Workflow

### 1. Build From Runtime Success

Start from a passing solve:

```text
recorded or DeepSeek solve
-> RuntimeOrchestrator.last_success_artifacts
-> ExplanationSnapshotBuilder
```

The snapshot is the first fact source for lesson/page generation. It should contain effective StepIntent, teaching trace, fact index, verified values, answers, and planner insights. Do not use `SolverResult.to_dict()` as the primary lesson/page fact source.

### 2. Generate Or Validate LessonIR

LessonIR is the student-facing explanation plan. It owns:

- step grouping;
- `title` and `nav_title`;
- `goal`;
- `derive`;
- student-readable `box`;
- source ids, capability ids, and teaching substeps.

Use the Explanation LLM when enabled to improve grouping and wording, not to create mathematical facts. It may use previous attempts and repair feedback. If it fails after its repair budget, fall back to deterministic teaching drafts.

When LessonIR quality or validation fails:

- Add or improve `MethodExplanationSpec` or `RecipeExplanationSpec`.
- Add teaching substep specs when one executable recipe contains multiple cognitive actions.
- Add `title_required_terms` / `nav_title_required_terms` to teaching substep specs when LLM titles consistently drift from the intended teaching keywords.
- Add or improve method/recipe role binders.
- Add explanation few-shot or family mock few-shot when style and grouping are unstable.
- Improve normalizer / validator / repair feedback when LLM output is structurally repairable.

Do not write current problem point names, answer values, problem ids, or fixed paths into generic explanation builders or prompt rules.

### 3. Generate VisualStepIR

VisualStepIR is generated from `ExplanationSnapshot + LessonIR`, not authored page JSON.

Use method/recipe visual specs as the domain source for what should be drawn:

- `MethodVisualSpec` / `RecipeVisualSpec` declare semantic components and visual intent.
- Visual role binders bind roles to canonical handles and geometry ids.
- The builder creates scene diffs, focus, annotations, and VisualGap when a role cannot be resolved.
- The compiler maps semantic components to existing low-level step-decorations types.

When VisualStepIR fails or the graph is wrong:

- Add or improve `MethodVisualSpec` / `RecipeVisualSpec`.
- Add or improve `VisualRoleBinder`.
- Add a semantic component only when it represents a reusable visual idea.
- Compile new semantic components to existing low-level types when possible.
- Extend `GeometrySpecBuilder`, `BaseSceneBuilder`, or `SceneAccumulator` when the generated base or carry-forward model is insufficient.
- Extend `GeometryPointScopeNamer` when multi-scope point naming produces collisions, wrong suffixes, or inconsistent geometry ids.

Do not draw by problem id, exam name, or fixed point-letter special cases. Role language and canonical handles must drive visual generation.

### 4. Add Interactions

VS2 interactions are generated by code and runtime facts.

Use local / linked controls when they help students inspect moving-point relationships. Parameterized coordinates and domains must come from resolvers and verified facts.

When interactions fail:

- Add or improve `ParametricExpressionResolver`.
- Add or improve interaction spec, compiler, or validator.
- Ensure `lesson-data.steps[].localControls` and `step-decorations.steps[].pointOverrides` are generated together.
- Keep local interaction points out of global `geometry-spec.movingPoints` unless they truly belong to global state.

LLM must not create or modify `pointOverrides`, `parameterized_points`, `localControls`, interaction domains, or parameterized formulas.

### 5. Add Animations

VS3 animations are generated by method/recipe animation specs and deterministic builders.

Use animation for teaching transformations, constructions, linked motion, and shortest-path ideas when static images are too abrupt. Animation output should compile into `lesson-data.steps[].animation.beats`, not static `step-decorations`.

Animation beats may use `local_vars` with simple `from` / `to` tweens or multi-point `keyframes` for sweep motions. Both must validate against existing interaction parameter names.

When animation fails:

- Add or improve method/recipe timeline templates.
- Add reusable animation components.
- Add or improve `AnimationTimelineBuilder`.
- Extend validator or frontend runtime only for general animation behavior.
- Keep modal playback isolated from the main page state.

LLM must not modify timeline beats, scene patches, local var tweens, or animation structure unless a future validated review mode explicitly permits it.

### 6. Compile And Validate The Page

Generated artifacts should compile through the same public tools:

```bash
node tools/validate-geometry-spec.mjs <generated-output-dir>
node tools/build-lesson-page.mjs <generated-output-dir>
```

If compilation fails, fix generated artifacts, schema, compiler, or shared runtime. Do not patch the generated HTML page.

## LLM Boundaries

Use LLMs as teaching and visual arrangers, not as fact sources.

LLM may decide:

- wording;
- grouping;
- ordering;
- visual emphasis;
- label hiding;
- non-factual style choices;
- redundant derive compression.

LLM must not decide:

- point coordinates;
- curve expressions;
- final answers;
- real existence of mathematical objects;
- carry-forward / persistence lifecycle;
- interaction formulas or domains;
- animation beat structure;
- timeline scene patches.

For the full boundary policy, consult `docs/llm-role-boundaries-and-expansion-strategy.md`.

## Failure Classification

Classify failures before editing code.

LessonIR failures usually indicate:

- missing method/recipe explanation spec;
- missing teaching substep split;
- weak explanation role binder;
- insufficient few-shot or mock few-shot;
- invalid student-facing box or derive style;
- validator or repair feedback gap.

VisualStepIR failures usually indicate:

- missing visual spec;
- missing visual role binder;
- missing semantic component;
- geometry id / canonical handle mapping gap;
- base layer or carry-forward model gap;
- compiler / validator gap.

Interaction failures usually indicate:

- missing parameter resolver;
- missing role data for moving/linking points;
- domain/default derivation gap;
- compiler / frontend localControls mismatch.

Animation failures usually indicate:

- missing timeline template;
- missing reusable animation component;
- stale static-scene assumptions;
- modal runtime issue;
- derive accumulation or visual continuity gap.

If a failure exposes missing mathematical runtime facts, return to solver capability work and use `deepseek-25-onboarding`.

## Commands

Recorded solver smoke:

```bash
cd server && uv run python -m shuxueshuo_server.solver.solve_problem \
  --fixture ../internal/solver-fixtures/<problem_id>.json \
  --planner strategy --llm-provider recorded
```

Recorded explanation / LessonIR tests:

```bash
cd server && uv run pytest tests/solver/test_explanation_builder_text_<case>.py -q
```

DeepSeek explanation opt-in:

```bash
cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_EXPLANATION_BUILDER=1 \
  RUN_DEEPSEEK_<CASE>_EXPLANATION=1 \
  uv run pytest tests/solver/test_explanation_builder_text_<case>.py::<test_name> -q -s
```

Visual recorded-lesson fixture:

```bash
cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_VISUAL_BUILDER=1 \
  RUN_DEEPSEEK_<CASE>_VISUAL=1 \
  uv run pytest tests/solver/test_visual_step_ir_vs1.py::<recorded_lesson_visual_test> -q -s
```

Full DeepSeek explanation + visual:

```bash
cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_VISUAL_BUILDER=1 \
  RUN_DEEPSEEK_<CASE>_VISUAL=1 \
  uv run pytest tests/solver/test_visual_step_ir_vs1.py::<full_explanation_visual_test> -q -s
```

Generated page validation:

```bash
cd server && uv run pytest tests/solver/test_visual_step_ir_vs0.py -q
node tools/validate-geometry-spec.mjs <generated-output-dir>
node tools/build-lesson-page.mjs <generated-output-dir>
git diff --check
```

## Guardrails

- Do not use handwritten lesson-spec three JSON files as product inputs for this pipeline.
- Do not hand-edit generated HTML.
- Do not hard-code problem ids, exam names, answer values, or current-case point names in builders, compilers, validators, or prompts.
- Do not let LLM-generated text leak internal handles, runtime paths, Python/SymPy expression syntax, or expected answers.
- Do not let Visual LLM create carry-forward objects or mutate interactions / timeline.
- Prefer VisualGap or deterministic fallback over fake geometry.
- When a new visual or animation idea is reusable, model it as method/recipe spec + role binder + compiler support.
- Keep generated page tests opt-in when they call live DeepSeek; recorded tests must remain deterministic.
