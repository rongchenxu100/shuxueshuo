---
name: deepseek-25-onboarding
description: Use this skill when adding a new middle-school problem, especially a question 25, to the FunctionalPlan + DeepSeek solver pipeline from a problem image or an existing lesson-spec problem. The agent creates canonical ProblemIR, expected answers, authored FunctionalPlan fixtures, DeepSeek integration tests, mechanism few-shots, and reusable method, family, Function/Macro, binding, closure, and explanation support.
---

# DeepSeek 25 Onboarding

Onboard a new problem through the only planner protocol:

```text
canonical ProblemIR
-> FunctionalPlan provider (recorded or DeepSeek)
-> typed reconciliation and binding ledger
-> direct Function/Macro compiler
-> transactional execution
-> typed goal verification and retry
-> PlannerOutput
-> RuntimeOrchestrator
-> SolverResult
```

Work test-first. Add only reusable facts, contracts, and code needed by the
problem class; never encode one problem's answer or fixed method chain in generic
runtime code.

## Input Modes

### Problem Image

1. Extract the complete problem text, source, question number, objects,
   conditions, scope tree, subquestions, and any visible answer information.
2. If standard answers are absent, solve independently and verify them.
3. Create canonical ProblemIR. After that point, the image is not runtime truth.

### Existing Lesson-spec Problem

1. Find `internal/lesson-specs/*/01_problem.md` by id or distinctive text.
2. Read `01_problem.md` as the problem source.
3. Use `02_solution.md` and `lesson-data.json` only to verify answers, scopes,
   and likely strategy.
4. Keep canonical ProblemIR as the solver fact source.

## Required Artifacts

For `<problem_id>`, create or update:

- `internal/solver-fixtures/<problem_id>.json`
- `server/tests/solver/expected/<problem_id>.expected.json`
- `internal/functional-plan-fixtures/<problem_id>.functional-plan.json`
- the default recorded Functional regression for the case
- the opt-in DeepSeek Functional integration case
- reusable method, FunctionSpec, MacroSpec, family, binding, closure, retry, or
  explanation code where the existing catalog is insufficient
- optionally, a neutral mechanism manifest and asset under
  `internal/functional-few-shot-manifests/` and
  `internal/functional-few-shots/`

The authored ProblemIR `input` contains only `problem_id`, `pattern`,
`problem_type`, `display`, `original_text`, `scopes`, `entities`, `facts`, and
`question_goals`.

Do not put expected answers, runtime paths, method chains, derived coordinates,
helper objects introduced by a solution, or compatibility projections in
ProblemIR. Definitional objects stated by the problem belong in ProblemIR;
objects invented by a solution are declared by the producing Functional call.

## FunctionalPlan Contract

An authored or model-produced plan uses `functional_plan/v1` and contains scoped
public calls:

- `call_id`: stable candidate-local identifier;
- `capability_id`: exact public Function or Macro;
- `args`: wire, call-result, condition, or semantic inputs;
- `return_bindings`: object or answer projections;
- concise `strategy` and `reason` text for presentation.

Keep public calls at reusable Function/Macro granularity. Do not expose internal
Macro invocation wiring, runtime paths, StateVersion IDs, expected answers, or
compiler selectors to the model.

For multi-question scope trees:

- place facts needed by sibling questions in their nearest common ancestor;
- keep truly private work in its child scope;
- never read a sibling-private state;
- let typed placement hoist equivalent shareable calls when exact inputs are
  visible; do not move private prerequisites merely to force sharing.

## Capability Design

### Method

A method states what mathematical relation it computes, its typed inputs and
outputs, applicability, checks, and unsupported cases. The Python `SPEC` is the
source of truth. Use abstract roles such as fixed point, moving point, target
parameter, or transformed path, not exam names or concrete point letters.

After changing a method, regenerate specs:

```bash
cd server
uv run python -m shuxueshuo_server.solver.runtime.methods.generate_specs
```

### Function And Macro

Use a Function for one public method capability. Use a Macro when a standard
public action owns multiple internal method invocations.

Declare:

- semantic argument roles and binding authority;
- cardinality and runtime input targets;
- Function adapter or Macro invocation graph/input aliases/selectors;
- public return/output-key mappings;
- identity policy, write mode, and result form;
- symbolic closure contract for parameter-solving capabilities.

The direct compiler must have enough declarative information to compile without
candidate search, reads-order inference, or handle-name heuristics.

### Family

Family matching uses structured `pattern/problem_type`. A family supplies base
and mechanism capability packs plus strategy principles. Family differences
should describe genuine mathematical structure, not a whitelist of problem IDs.

## Test-first Workflow

### 1. Establish The Problem Contract

- Choose a stable problem id such as `tj-2026-xiqing-yimo-25`.
- Encode the scope tree and each goal's target object and valid scope.
- Put expected answers only under `server/tests/solver/expected/`.
- Validate that each initial entity/fact is directly stated by the problem.
- Keep presentation metadata in `display`, not in the solver logic.

### 2. Add The Recorded Functional Fixture

Author the smallest complete FunctionalPlan that solves every required goal.
Run it through the default recorded entry, not a mocked PlannerOutput. Assert:

- typed reconciliation and direct compilation succeed;
- transactional writes and closure provenance are complete;
- exact StateVersion and scope dependencies are valid;
- answers and runtime checks match the expected fixture;
- explanation consumes canonical call IDs.

### 3. Add The DeepSeek Test

Network tests are opt-in. Use the default Functional provider and write artifacts
under the batch/debug directory. Success requires solver status, answers,
protocol, runtime, provenance, retry, closure, and explanation gates.

The default batch command is:

```bash
cd server
RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
uv run python -m shuxueshuo_server.solver.deepseek_functional_batch \
  --case all --samples-per-case 3 --concurrency 3 --max-attempts 3
```

### 4. Classify Failures Before Editing

Inspect raw FunctionalPlan, reconciliation, binding decisions, transaction
timeline, actual runtime results, typed writes, goal report, retry checkpoint,
and previous-attempt payload. Compare failed and successful attempts.

Classify in this order:

1. ProblemIR fact, scope, or goal gap.
2. Family routing or capability-pack gap.
3. Missing reusable method/Function/Macro.
4. Incomplete binding or direct compile contract.
5. Typed identity, scope, version, destination, or retry authority bug.
6. Symbolic closure contract or output validation gap.
7. Prompt or mechanism few-shot ambiguity.

Do not fix a planner mistake by matching the problem id, exam title, answer
value, call id, handle spelling, or concrete point name.

### 5. Generalize And Lock The Fix

- Add a focused production-path regression first.
- For scope/version bugs, add an anonymous C0.5 oracle scenario.
- For role bugs, add a C3 binding scenario with same-typed inputs swapped.
- For closure bugs, add unique/ambiguous/inconsistent and companion-output tests.
- Preserve exact runtime evidence in retry feedback without exposing typed IDs.
- Ensure failed transactions leave no writes or retry checkpoint entries.

### 6. Add A Few-shot Only When Needed

Few-shots teach mechanisms, not complete current-problem solutions. Select a
closed two-to-five-call subgraph from a verified authored FunctionalPlan,
neutralize call IDs and SemanticRefs with a manifest, and write a concise safety
annotation. Never include expected values or source-specific numbers.

Regenerate and validate assets with:

```bash
python tools/sync_strategy_few_shots.py
cd server && uv run pytest tests/solver/test_functional_few_shots.py -q
```

## Repair Principles

The repair loop replays full FunctionalPlan candidates but hard-locks only
goal-committed canonical calls and exact typed version chains. Runtime-verified
provisional results may be shown as evidence but remain editable.

Good repair feedback identifies:

- the failed canonical call and typed issue code;
- actual result form/value when prompt-safe;
- missing prerequisite role or invisible scope;
- ambiguous branches or missing closure constraints;
- locked calls and the repair cone.

It must not expose runtime paths, StateVersion IDs, expected answers, internal
builder IDs, or a problem-specific forced method chain.

## Handoff To Lesson Generation

After the solver path is stable, use `solver-to-lesson-page-onboarding`:

```text
verified Functional transaction artifacts
-> ExplanationSnapshot
-> LessonIR
-> VisualStepIR
-> interactions and animations
-> compiled lesson page
```

LessonIR and visual bindings should use canonical Functional call IDs. Keep page
rendering concerns out of solver onboarding unless a page failure reveals a
missing reusable runtime fact or explanation contract.

## Verification

Run focused tests while iterating, then:

```bash
cd server
uv run pytest tests/solver -q
git diff --check
```

Do not update recorded Functional fixtures from a failed or partially verified
attempt. A fixture is accepted only after typed reconciliation, direct compile,
transactional execution, goal verification, and provenance checks all pass.
