# Method Solver Current Architecture

## Summary

Method Solver turns canonical `ProblemIR` into a verified `SolverResult`. The
only LLM planning protocol is `functional_plan/v1`:

```text
canonical ProblemIR
  -> RuntimeProjection
  -> structural FamilyRegistry match
  -> FunctionalPlan provider (recorded or DeepSeek)
  -> typed reconciliation and binding ledger
  -> direct Function/Macro compiler
  -> transactional call execution
  -> runtime-grounded StateVersion commits
  -> typed goal verification and retry checkpoint
  -> goal-reachable PlannerOutput
  -> InvocationExecutor
  -> ResultBuilder
  -> SolverResult
```

`StepPlan`, `MethodInvocation`, `PlannerOutput`, and `InvocationExecutor` remain
internal execution structures. The retired StepIntent LLM protocol is not part
of this path.

## Sources Of Truth

The authored problem source is:

```text
internal/solver-fixtures/<problem_id>.json
```

Its `input` contains only structured problem facts: `problem_id`, `pattern`,
`problem_type`, display metadata, original text, scopes, entities, facts, and
question goals. It must not contain expected answers, runtime paths, solution
facts, helper objects introduced by a solution, or a method chain.

Other artifacts have narrower roles:

- `server/tests/solver/expected/*.expected.json`: answer oracle for tests.
- `internal/functional-plan-fixtures/*.functional-plan.json`: authored recorded
  planner output used by offline regression.
- `internal/functional-few-shot-manifests/*.manifest.json`: extraction rules for
  anonymous mechanism examples.
- `internal/functional-few-shots/*.functional-few-shot.json`: prompt-safe
  `functional_plan/v1` mechanism examples.
- method Python `SPEC`: Function contract source; generated method-spec JSON is
  derived data.
- `FunctionSpec` and `MacroSpec`: direct compiler contracts.

## Planning And Family Routing

`FamilyRegistry` matches production problems from structured `pattern` and
`problem_type`. An ambiguous match fails loudly. Exact problem-id routing is
reserved for deterministic debug providers and is not family admission.

The default Strategy provider is FunctionalPlan:

- `recorded` loads the authored FunctionalPlan fixture and runs the complete
  typed reconciliation, direct compile, transaction, goal, and output path.
- `deepseek` requests `functional_plan/v1`, validates it, and runs the same
  downstream path.

Planner failures do not fall back to another LLM protocol.

## Typed Reconciliation

Reconciliation resolves every public call argument to one identity class:

- materialized state: exact `StateVersionId`;
- condition: condition identity;
- identity-only object: `MathObjectId`;
- call-local value: canonical producer call and public return.

B1 allocates typed state, B2 owns canonicalization and scope placement, B3
finalizes logical and runtime-destination writers, and B4 owns committed retry
version restoration. Handles and runtime paths are compatibility or physical
projection values, not semantic identity.

C3's binding ledger records why each value belongs to each method argument.
Argument role and authority are therefore stable under wire order, aliases,
scope placement, and retry call-id changes.

## Direct Compilation

The Functional direct compiler consumes prepared typed calls:

- Functions map public args through `FunctionSpec.adapter` to method inputs.
- Macros compile their declared invocation graph, aliases, selectors, and
  public-return mappings.
- exact/latest state selection happens before compilation through the typed
  state-read index;
- B1 allocations and B3 destination manifests determine promotions;
- compilation does not search alternative capabilities or reconstruct identity
  from reads order, handle text, or runtime paths.

The compiler emits existing `StepPlan` and `MethodInvocation` objects. Those
remain the stable executor boundary.

## Transactional Execution

Canonical Functional calls execute in typed DAG order. Each call forks the
current `RuntimeContext`; method execution, output validation, symbolic closure,
and B3 finalization happen on that branch. The branch is committed only when the
whole public Function or Macro succeeds.

Consequences:

- a failed call leaves no declaration, promotion, or StateVersion behind;
- dependents are blocked while independent branches may continue;
- aliases and eliminated calls are never executed;
- actual values determine result form, free symbols, and optional returns;
- only verified, goal-reachable calls enter the final `PlannerOutput`.

The Orchestrator re-executes that aggregate output for the public solver result;
transactional runtime values are not reused as the final answer cache.

## Symbolic Closure

Parameter-solving capabilities declare `SymbolicClosureSpec`. The shared
runtime closure executor owns target identity, equations, branch classification,
constraints, substitutions, residual symbols, and companion-output validation.
Only a validated unique result can be committed.

Closure provenance is persisted with StateVersions and consumed by Context,
retry checkpoints, goal verification, and Explanation. Method-local first-branch
selection or static free-symbol refinement is not authoritative.

## Context And Retry

`planner-state-context/v2` stores typed runtime observations and committed
Functional retry checkpoints. It does not persist runtime values for reuse.
Every retry restores committed canonical calls, replays them, and verifies the
same computation key, binding signature, StateVersion chain, scope, destination,
and closure signature.

Retry feedback can expose prompt-safe actual results and compact closure facts,
but never StateVersion IDs, runtime paths, expected answers, or internal builder
identifiers.

## Explanation And Visual Pipeline

Explanation consumes canonical, runtime-verified, goal-reachable calls and
their actual writes. Presentation scope is independent from runtime execution
scope. Symbolic closure teaching traces are deduplicated by semantic signature.

Lesson and visual fixtures refer to canonical Functional call IDs. The page
pipeline is:

```text
solver result and transaction artifacts
  -> ExplanationSnapshot
  -> LessonIR
  -> VisualStepIR
  -> compiled lesson page
```

## Few-shot Maintenance

Functional few-shots teach anonymous mathematical mechanisms, not whole
problem answers. Regenerate their plan portion with:

```bash
python tools/sync_strategy_few_shots.py
```

The tool reads manifests plus authored FunctionalPlan fixtures and preserves
any human-authored annotation. Stored examples must remain strict,
prompt-safe `functional_plan/v1` payloads.

## Adding A Capability

1. Define or extend the reusable method and Python `SPEC`.
2. Add a `FunctionSpec` or declarative `MacroSpec` compiler contract.
3. Declare semantic roles, authority, cardinality, runtime targets, returns,
   identity policy, and write mode.
4. Add direct method/compiler tests, including ambiguous and unsupported cases.
5. Add the capability to the appropriate capability pack or family.
6. Validate transactional execution, typed provenance, retry, and explanation.

Do not branch on problem id, exam title, answer value, or concrete point name in
generic runtime code.

## Verification

Recorded default path:

```bash
cd server
uv run pytest tests/solver/test_strategy_planner_functional_plan.py -q
```

Real Functional batch:

```bash
cd server
RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
uv run python -m shuxueshuo_server.solver.deepseek_functional_batch \
  --case all --samples-per-case 3 --concurrency 3 --max-attempts 3
```

The batch summary must report FunctionalPlan v1, transactional Context
authority, authoritative closure, and the direct compiler.
