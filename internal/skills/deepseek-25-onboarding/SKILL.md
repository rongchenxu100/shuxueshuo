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

Prefer this order:

1. **ProblemIR gap**: missing entity, fact, scope, constraint, relation, or answer goal.
2. **FamilySpec gap**: wrong family, missing `strategy_principles`, missing `method_ids`, missing recipe, or missing binding rule.
3. **Method gap**: no reusable method can compute the needed fact/entity/answer.
4. **Recipe gap**: multiple methods form a standard reusable solving action.
5. **Binding gap**: method exists but semantic handles cannot bind to input slots.
6. **Normalizer gap**: LLM output has a structurally safe, deterministic rewrite.
7. **Prompt/few-shot gap**: LLM repeatedly chooses an invalid strategy or non-executable step granularity.

Do not patch runtime logic by matching a specific `problem_id`, exam title, fixed point name, or subquestion id.

### 4. Add Reusable Capability

When adding or extending a method:

- Put implementation and `SPEC` in the method Python file.
- Treat Python `SPEC` as the source of truth; generated `internal/method-specs/*.json` is derived.
- Run the method spec generator:

```bash
cd server && uv run python -m shuxueshuo_server.solver.runtime.methods.generate_specs
```

- Add method unit tests, including old-case regression if extending an existing method.

When adding recipe or binding capability:

- Add recipe and method binding rules to the relevant `SolverFamilySpec`.
- Keep recipe generic: no problem id, no fixed point names, no answer values.
- Add unit tests for recipe selection, selector existence, binding behavior, and any normalizer rewrite.

When changing prompt/few-shot:

- Keep StepIntent at method/recipe executable granularity, not student-facing explanation granularity.
- Do not put expected answers into prompt or payload.
- Prefer family strategy principles and verified few-shot examples over single-case prompt hacks.

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
