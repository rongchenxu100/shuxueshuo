# FunctionalPlan Dynamic Few-shot Design

## Purpose

Strategy Planner few-shots teach a small, reusable mathematical mechanism using
the same `functional_plan/v1` wire schema as the current problem. They are not
recorded whole-problem answers and are not a second problem fact source.

The active asset flow is:

```text
authored FunctionalPlan fixture
  + mechanism extraction manifest
  + human annotation
  -> deterministic anonymous FunctionalPlan example
  -> validated selection index
  -> Strategy prompt
```

## Assets

- Source plans: `internal/functional-plan-fixtures/*.functional-plan.json`
- Extraction manifests:
  `internal/functional-few-shot-manifests/*.manifest.json`
- Prompt assets:
  `internal/functional-few-shots/*.functional-few-shot.json`
- Runtime implementation:
  `solver/runtime/functional_few_shots.py`
- Synchronizer: `tools/sync_strategy_few_shots.py`

The manifest selects a closed subgraph of two to five calls and declares:

- source call IDs;
- capability IDs and answer value types;
- family and capability-pack retrieval metadata;
- deterministic call-ID and SemanticRef neutralization;
- prompt-safe condition descriptions.

The stored asset may add a human-authored annotation:

```json
{
  "format": "functional_plan/v1",
  "annotation": {
    "purpose": "...",
    "use_when": "...",
    "key_idea": "...",
    "do_not_use_when": ["..."]
  },
  "scopes": []
}
```

Its `scopes` are generated deterministically from the source fixture and
manifest. The synchronizer preserves an annotation when present and rewrites
only the plan.

## Safety Rules

Prompt examples must:

- remain valid `functional_plan/v1`;
- contain a dependency-closed call subgraph;
- use anonymous call IDs and SemanticRefs;
- avoid canonical handles, runtime paths, expected answers, source problem IDs,
  builder IDs, and internal typed IDs;
- avoid concrete numeric values in explanatory text;
- describe when the mechanism applies and when it must not be copied.

The current problem and example problem are separate prompt regions. Example
objects, conditions, answer destinations, and names must never migrate into the
current candidate.

## Selection

Selection is deterministic and locked across retry:

1. prefer a compatible same-family mechanism;
2. otherwise choose a relevant cross-family mechanism;
3. otherwise use a capability-pack fallback;
4. select exactly one example;
5. in strict tests, exclude the current source problem;
6. persist `FunctionalFewShotSelectionRecord` for later attempts.

Compatibility requires that the current catalog contains every capability used
by the example. Retrieval considers family, capability packs, capability IDs,
and answer value types. It does not compare expected values.

## Maintenance

Regenerate every asset:

```bash
python tools/sync_strategy_few_shots.py
```

Regenerate one mechanism:

```bash
python tools/sync_strategy_few_shots.py quadratic-constraints-vertex
```

The command fails when the source fixture, manifest coverage, dependency
closure, neutralization map, annotation, or prompt safety contract is invalid.

Add a new example only when it teaches a reusable mechanism not already covered.
Prefer a short closed subgraph over a complete solution. First commit and test
the authored FunctionalPlan fixture, then write the extraction manifest and
annotation, run the synchronizer, and add selection/safety tests.

## Regression Requirements

- Every manifest has exactly one generated asset.
- Every asset equals deterministic projection from its current source fixture.
- Stored assets expose only FunctionalPlan fields plus `annotation`.
- Selection is deterministic and stable across retry.
- Same-problem exclusion works in strict tests.
- Prompt rendering does not reveal annotation metadata or typed runtime data as
  candidate wire fields.
- Full solver regression remains green after regeneration.

Focused tests:

```bash
cd server
uv run pytest tests/solver/test_functional_few_shots.py -q
```
