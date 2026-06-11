---
name: deepseek-25-onboarding
description: Use this skill when adding a new middle-school problem, especially a question 25, to the Strategy Planner + DeepSeek solver pipeline from either a problem image or an existing lesson-spec problem. The agent creates canonical ProblemIR, expected answers, DeepSeek integration tests, recorded executable StepIntent fixtures, few-shot projection, and any reusable method/family/recipe/binding/normalizer code needed to make the tests pass.
---

# DeepSeek 25 Onboarding

Use this skill to onboard a new 第 25 题 into the Strategy Planner solver path:

```text
canonical ProblemIR
-> StrategyPlanner(deepseek or recorded)
-> StepIntent
-> RecipeTrialExecutor
-> RuntimeOrchestrator
-> ResultBuilder
```

The work is test-driven: create the DeepSeek integration test first, then add only reusable data/code needed to make the test pass.

## Input Modes

Exactly one input mode should be used.

### Mode A: Problem Image

Use when the user provides an image or screenshot of the problem.

1. Extract the full original text, source, question number, objects, conditions, scopes, subquestions, and visible answer information.
2. If the image does not include standard answers, solve the problem independently and create expected answers from the verified solution.
3. Build canonical solver artifacts from the extracted problem. Do not use image-derived text as runtime truth after canonical ProblemIR is created.

### Mode B: Existing Problem In The Repository

Use when the user refers to an existing题库 problem.

1. Search `internal/lesson-specs/*/01_problem.md` by problem id, source, district, exam name, or distinctive problem text.
2. Read the matching `01_problem.md`.
3. Read `02_solution.md` and `lesson-data.json` only to confirm answers, scopes, and likely student solution strategy.
4. The solver fact source is still canonical ProblemIR, not lesson markdown or page JSON.

## Required Artifacts

For `<problem_id>`, create or update:

- `internal/solver-fixtures/<problem_id>.json`
- `server/tests/solver/expected/<problem_id>.expected.json`
- `server/tests/solver/test_deepseek_strategy_planner_<case>.py`
- after DeepSeek succeeds: `internal/solver-fixtures/<problem_id>.executable-step-intents.json`
- after recorded succeeds: `internal/few-shots/<problem_id>.few-shot.json`

The canonical ProblemIR is the only authored problem fact source. Its `input` object must contain only `problem_id`, `pattern`, `problem_type`, `original_text`, `scopes`, `entities`, `facts`, and `question_goals`.

Do not hand-author runtime compatibility fields such as `symbols`, `symbol_roles`, `constraints`, `data.function`, `data.entities.points`, `data.entities.items`, `data.relations`, `data.path_problem`, `questions[].conditions`, or `questions[].goals.target_path`. `RuntimeProjection` derives those fields for `ContextBuilder` and `ResultBuilder`.

It must not include expected answers, raw DeepSeek output, method chains, runtime `ContextPath` values, derived solution facts, or auxiliary solution-only entities.

## Capability Abstraction Principles

The solver grows by adding reusable mathematical capabilities, not by patching one problem at a time.

### Method Level

A method describes **what mathematical problem it can solve**, not the procedural steps of one concrete solution. Write method summaries in this shape:

```text
Given <semantic inputs>, derive <semantic output> under <applicability/preconditions>.
```

Good method specs say:

- what class of conclusion the method derives;
- which semantic inputs are required;
- which output types it produces;
- which preconditions make the method applicable;
- whether symbolic or parameterized expressions are supported;
- what the method intentionally does not solve.

Avoid current-case wording such as fixed problem ids, district names, subquestion ids, answer values, or point names that are not abstract roles. Prefer role language such as `fixed point`, `moving point`, `reference angle`, `target point`, `known intercept`, `dynamic parameter`, and `path expression`.

The method Python `SPEC` is the source of truth. Generated `internal/method-specs/*.json` files must be synchronized from code, not edited by hand.

### Recipe Level

A recipe describes a standard executable solving action that may contain one or more methods. Use a recipe when the LLM needs a high-level menu item such as “turn an equal-length two-moving-point path into a single-moving-point distance”, while the code owns the internal method sequence and wiring.

Do not create recipes that merely restate one current problem’s helper point construction. If the recipe cannot be described without the current letters, it is not abstract enough.

### Family Level

`strategy_principles` should describe the student-friendly mathematical strategy for the family. `step_recipes` should describe standard executable actions in that strategy. The family name should reflect the core structure, such as weighted path transformation or equal-length ray path reduction, not a single exam problem.

The LLM should prefer `recipe_hint` from the recipe catalog first, then method ids from the method catalog. It may leave the hint empty only when no catalog entry fits; the code may still resolve such steps if the capability match is unique.

## Workflow

### 1. Establish The Problem Contract

- Choose a stable `problem_id` matching repository naming, such as `tj-2026-xiqing-yimo-25`.
- Choose `pattern` and `problem_type` from the structured problem, not from LLM guesswork during solving.
- Create expected answers separately under `server/tests/solver/expected/`.
- Make sure `QuestionGoal.handle` uses `answer:<goal_id>` and canonical entity/fact handles follow the repository naming scheme.
- For Point answers, set `question_goals[].target_handle` to the canonical point entity. For non-Point answers, the projection writes the result to the runtime `outputs` container.
- If an answer produced in a subquestion is intentionally reusable by sibling steps, set `question_goals[].valid_scope` to the broader proof scope. Do not expose a runtime `target_path`.
- Keep canonical ProblemIR text-faithful: every initial `Entity` and `Fact` must be directly stated by the original problem text. Do not pre-fill coordinates, expressions, equalities, helper points, helper lines, or transformed path facts that are obtained by solving.
- If the problem states a definitional object such as “C is the y-axis intercept” or “D is C translated right by 2”, encode that as an entity definition, not as a coordinate fact. The runtime/method layer must derive its value.
- If a solution introduces an auxiliary object such as an intersection/helper point, put it in StepIntent `creates[]` and produce its computed fact in `produces[]`; do not add it to the canonical ProblemIR.

### 2. Add The DeepSeek Test First

Create a test like the Xiqing pattern:

- Default tests must not call the network.
- The real DeepSeek test is opt-in with `RUN_LLM_INTEGRATION=1`, `RUN_DEEPSEEK_STRATEGY_PLANNER=1`, and a case-specific flag.
- At the start of the real test, clear `internal/solver-runs/strategy-planner-deepseek-<case>/`.
- The real test must call `solve_problem(problem, runtime_config=SolverRuntimeConfig.from_sources(planner_mode="strategy", llm_provider="deepseek", ...))`.
- Success means `result.status == "ok"` and `result.answers == expected`.

### 3. Run And Classify Failures

Use the debug artifacts to classify each failure before changing code.

Inspect the whole attempt, not only the first blocking exception. When available, read the raw draft, effective draft, normalization report, candidate report, execution diagnostic, accepted prefix, and previous-attempt payload.

Compare attempts when a later attempt succeeds. The most useful bugs often appear as a small shape difference between the failed and successful drafts. If the failed draft is mathematically correct but differs by naming, missing alias, multi-output shape, omitted state fact, or step ordering, prefer a code-side fix and add a fixed regression fixture.

Prefer this classification order:

1. **ProblemIR gap**: missing entity, fact, scope, constraint, relation, or answer goal.
2. **FamilySpec gap**: wrong family, missing `strategy_principles`, missing `method_ids`, missing recipe, or missing binding rule.
3. **Method gap**: no reusable method can compute the needed fact/entity/answer.
4. **Recipe gap**: multiple methods form a standard reusable solving action.
5. **Binding gap**: method exists but semantic handles cannot bind to input slots.
6. **Normalizer gap**: LLM output has a structurally safe, deterministic rewrite.
7. **Prompt/few-shot gap**: LLM repeatedly chooses an invalid strategy or non-executable step granularity.

Do not patch runtime logic by matching a specific `problem_id`, exam title, fixed point name, or subquestion id.

Use these decision rules:

- Add or extend a **method** when a reusable, checkable mathematical transformation/calculation is missing.
- Add or extend a **recipe** when several methods form a reusable solving action and the LLM needs a high-level hint.
- Add a **binding selector** when the method already exists but canonical handles cannot map reliably to method input slots.
- Add a **normalizer** only for deterministic structural drift, such as safe alias correction, scope widening to a visible parent, output-type alias, duplicate exact `creates`, or harmless utility fact rewrite.
- Tune **prompt/few-shot** when capabilities already exist but the LLM repeatedly chooses the wrong family strategy or wrong executable granularity.

Treat the first blocker as the execution boundary, not as the whole diagnosis. Use preflight warnings and skipped-step review to surface downstream issues of the same kind, but do not ask the LLM to rewrite accepted prefix steps unless the prefix itself is wrong.

The repair loop is stateless chat-wise. If a round fails, preserve rich repair context: previous raw/effective StepIntent draft, accepted prefix, applied fills, blockers, skipped steps, and repair instructions. A validation-only failure must not erase a previous rich execution diagnostic.

### Code-Side Absorption Rules

Absorb deterministic, structure-preserving deviations in code:

- If LLM reads an entity handle but omits the already-computed state fact, use entity-state resolution to bind the unique visible state. This applies to points, functions, symbols, segments, and other entity classes when the runtime type is known.
- If LLM uses an enumerated alias or parent-scope handle variant, canonicalize it through explicit alias rules only. Do not use fuzzy spelling correction.
- If a method returns multiple outputs, map produced handles to method output keys by structured signals first: `output_type`, answer value type, fact type, and handle semantic name. Never rely on output order or natural-language description as the primary mapping.
- If LLM emits a recipe’s internal method sequence, fold it back to the public recipe only when the recipe declares or clearly owns that sequence and the rewrite preserves all produced handles needed downstream.
- If a method has verified companion outputs, register them as readable runtime aliases even when the LLM does not explicitly produce every companion fact.
- If an existing method can safely prepare a missing prerequisite object, use declarative prep rules and expose only semantic StepIntent facts to the LLM, not runtime paths.

Do not absorb true mathematical gaps. Missing construction, missing relation, wrong family strategy, or an unsupported transformation should become repair feedback or a new reusable method/recipe.

### Planner Insight And Repair Feedback

Some methods reveal roles that the LLM should not guess before execution, such as the moving point after path reduction, selected candidates, or endpoints from a straightening recipe. Expose these as planner-visible insights in `previous_attempts`, not as expected answers.

Good planner insights:

- use canonical handles and output types only;
- say what was learned, such as `moving_point`, `fixed_points`, `transformed_path`, or recommended next capability;
- never include `ContextPath`, runtime invocation details, traceback, or expected answer values.

Repair guidance belongs near the capability that understands the failure:

- method-owned repair hints live in method Python `SPEC.repair_hints`;
- recipe-owned hints live with recipe execution metadata;
- binding-selector hints live with the selector or binding rule;
- `RepairFeedbackBuilder` only collects, ranks, merges, and filters hints for LLM consumption.

Do not hard-code a family-specific repair instruction in the generic builder or compiler. If a repair message names a method or recipe, it should be scoped by capability id, recipe id, or binding selector.

### 4. Add Reusable Capability

When adding or extending a method:

- Put implementation and `SPEC` in the method Python file.
- Treat Python `SPEC` as the source of truth; generated `internal/method-specs/*.json` is derived.
- Write the method summary as a capability statement, not an operation trace for one题.
- Include applicability, preconditions, input/output semantics, unsupported cases, and symbolic/parameterized support.
- If the method is useful for student explanation, describe the reusable mathematical idea, not a current-case derivation. Detailed derivation belongs to the explanation layer.
- If the method returns multiple useful values, declare all outputs in `SPEC.outputs`. Compiler alias registration must map those outputs structurally, especially for multi-output methods such as geometry transforms.
- If the method can repair a common misuse, add `repair_hints` to the method `SPEC` instead of putting the message in generic runtime code.
- Run the method spec generator:

```bash
cd server && uv run python -m shuxueshuo_server.solver.runtime.methods.generate_specs
```

- Add method unit tests, including old-case regression if extending an existing method.

When adding recipe or binding capability:

- Add recipe and method binding rules to the relevant `SolverFamilySpec`.
- Keep recipe generic: no problem id, no fixed point names, no answer values, and no hard-coded current-question path.
- Describe what the recipe solves at the executable step level, for example “reduce a two-moving-point path by an equal-length ray construction,” not “construct point F in 和平”.
- Let recipe execution own internal helper entities and method wiring when they are part of the standard action.
- Add unit tests for recipe selection, selector existence, binding behavior, and any normalizer rewrite.
- For recipe internals, keep a clear public contract. If the LLM should call the recipe, do not require it to know every internal method output; the compiler should wire and register companion outputs.
- If later planning depends on an internal result, expose a planner insight rather than expanding the recipe into a problem-specific mega method.

When changing prompt/few-shot:

- Keep StepIntent at method/recipe executable granularity, not student-facing explanation granularity.
- Do not put expected answers into prompt or payload.
- Prefer family strategy principles and verified few-shot examples over single-case prompt hacks.
- In tests, do not use the current problem as few-shot. Use a verified different example or a family mock fallback.
- A few-shot example teaches executable structure; webpage explanation steps may be coarser and are produced later by `ExplanationBuilder`.

### 5. Solidify The Passing Case

After the real DeepSeek test passes:

1. Convert the successful parsed StepIntent into `internal/solver-fixtures/<problem_id>.executable-step-intents.json`.
2. Ensure every executable step has a non-null `recipe_hint` that matches a recipe id or method id unless the code can uniquely resolve it by design.
3. Add recorded Strategy E2E and assert it does not call deterministic planner.
4. Generate the few-shot projection for the problem.
5. Run focused tests and full solver regression.

## Commands

Recorded CLI smoke:

```bash
cd server && uv run python -m shuxueshuo_server.solver.solve_problem \
  --fixture ../internal/solver-fixtures/<problem_id>.json \
  --planner strategy --llm-provider recorded
```

Real DeepSeek:

```bash
cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
  RUN_DEEPSEEK_<CASE>_STRATEGY_PLANNER=1 \
  uv run pytest tests/solver/test_deepseek_strategy_planner_<case>.py -q -s
```

Focused regression:

```bash
cd server && uv run pytest tests/solver/test_strategy_planner_phase1.py \
  tests/solver/test_strategy_planner_production.py \
  tests/solver/test_deepseek_strategy_planner_<case>.py -q
```

Full regression:

```bash
cd server && uv run pytest tests/solver -q
git diff --check
```

## Guardrails

- Do not keep both a solver fixture and a separate LLM ProblemIR as independent truth sources.
- Do not store expected answers inside canonical ProblemIR.
- Do not store derived conclusions in canonical ProblemIR, including computed coordinates for definitional points, simplified equations, final parameter values, or auxiliary construction points.
- Do not use raw DeepSeek responses as permanent golden fixtures.
- Do not add deterministic planners for new cases.
- Do not let Strategy Planner output runtime paths, method input bindings, or `ctx_N` ids.
- If a change helps only the current problem and cannot be described as reusable family/method/recipe behavior, stop and redesign the abstraction.
