# Path-Minimum Macro Redesign

Status: F5-F4.2 Runtime Authority Convergence complete; F5-F4.3 Path Macro
migration is next

The canonical authority-convergence plan is maintained in
[Track F F5-F4.2](problem-extraction-context-implementation-plan.md#f5-f4-2-runtime-authority-convergence).

This document records the F5-F4 audit of Planner-facing Macro contracts. It
separates the implemented `equal_length_ray_path_reduction` reference contract
from the remaining path-Macro migration.

## 1. Design Goal

The Planner should choose a high-level mathematical strategy and refer to
problem entities and Facts. It should not assemble internal Method calls,
choose runtime object views, or pass path implementation artifacts between
steps.

The target boundary is:

```text
LLM
  chooses a family Macro
  supplies problem Entity/Fact refs and optional mathematical role hints
    -> Macro candidate builder
    -> bounded shadow compile/runtime search
    -> runtime equivalence, identity, scope, Goal and provenance checks
    -> unique verified winner
    -> clean replay and commit
    -> primary mathematical result + internal geometric witness
```

An LLM-authored role is a preferred hypothesis, not authority. A unique
runtime-valid alternative may correct it. Multiple non-equivalent valid
alternatives must fail with a prompt-safe ambiguity diagnostic.

## 2. Current Inventory

There are seven registered `StepRecipeSpec` Macros:

1. `right_angle_equal_length_construct_and_select`
2. `curve_candidate_parameter_solve`
3. `two_moving_points_path_reduction`
4. `broken_path_straightening_and_select`
5. `path_minimum_by_straightened_distance`
6. `broken_path_straightening_minimum_expression`
7. `equal_length_ray_path_reduction`

Three additional capabilities are implemented as Methods but currently carry
Macro-level strategy responsibilities and must be migrated in the same track:

1. `square_path_dimension_reduction`
2. `weighted_axis_path_triangle_transform`
3. `linked_broken_path_minimum_expression`

Leaving these three outside the redesign would preserve the same Planner-facing
`PathWitness`, auxiliary-point and internal-wiring problems through a different
entry point.

## 3. Path Intermediate Types

The current pipeline exposes three conceptually different values:

```text
PathTransformation / PathWitness
  proof payload for an equivalent path transformation

PathCandidate
  a selected straightening construction and its internal endpoints

MinimumExpression
  a symbolic scalar expression consumed by later parameter solving
```

They should not be treated uniformly.

### 3.1 Remove From Planner Wire

The following are Macro implementation details and must not appear in Planner
prompt, response schema, `FunctionalPlan`, or retry repair wire:

- `PathTransformation` / `PathWitness`;
- `PathCandidate`;
- reflected or constructed auxiliary points that have no problem identity;
- `straightened_endpoint_1` / `straightened_endpoint_2`;
- internal moving loci produced only to connect two Methods;
- internal Method call and return names.

They remain authenticated runtime and explanation evidence.

### 3.2 Keep As A Mathematical Result

`MinimumExpression` remains a legitimate anonymous mathematical value. A later
parameter-solving step may consume it with `StepResultRef`.

All high-level path Macros should converge on one public return name:

```text
minimum_expression: MinimumExpression
```

The runtime result form determines whether it is an `open_expression` or a
`closed_value`. The Macro surface should not duplicate the same result as
`path_minimum_expression`, `evaluated_path_minimum_expression` and
`minimum_expression`.

### 3.3 Add An Internal Witness

Each path Macro should emit an authenticated, non-Planner-facing sidecar:

```text
PathMinimumWitness
  original_objective
  reduced_objective
  chosen_roles
  constructions
  equality_chain
  moving_locus
  minimum_segment
  attainment_condition
  minimizing_configuration?
  runtime_checks
  macro_search_report
```

The Solver uses `minimum_expression`; Explanation and Visual stages use the
witness. This prevents a black-box numerical result without making the LLM wire
carry internal geometry.

### 3.4 Verified Execution Envelope

`FunctionalPlan` records authored mathematical intent. Runtime facts do not get
written back into the Plan. Every Macro instead publishes evidence through the
shared immutable envelope:

```text
VerifiedFunctionalPlanExecution
  canonical_plan
  plan / planning-context / problem revision authority
  checkpoint_id
  scope-shaped execution tree
    step status
    actual outputs
    typed evidence
```

The checkpoint and verified execution reuse the same execution tree. They are
not separately projected copies. `PathMinimumWitness` is the first complete
Macro-specific evidence contract inside this envelope; other Macros currently
store their actual outputs and existing search reports in the same tree.

Retry receives only a prompt-safe `PathMinimumPromptWitness`. Explanation and
Visual consume the authenticated witness projection rather than reconstructing
auxiliary points, congruence, path replacement, or minimizers from trace prose.

## 4. Macro-by-Macro Audit

### 4.1 `right_angle_equal_length_construct_and_select`

Current input:

```text
right_angle_equal_length Fact
```

Current output:

```text
selected_target_point: Point
```

Planned contract:

```text
input:
  right_angle_equal_length Fact
  target Point when target identity is not uniquely selected by the Goal
  optional quadrant/direction/symbol constraint Facts

output:
  selected_point: Point

internal:
  ConstructedPointWitness with candidates, chosen branch and checks
```

This Macro is already close to the desired boundary. The main change is to make
candidate search authoritative and preserve a verified construction witness.

### 4.2 `curve_candidate_parameter_solve`

Current input:

```text
candidates: PointList
parabola: QuadraticFunction
target_point: Point
point_on_curve Fact?
symbol_constraint Fact?
```

Current output:

```text
selected_curve_point: Point
parameter_value: ParameterValue?
solved_parabola: Parabola?
```

Planned contract:

```text
input:
  candidate-producing geometry Fact or authenticated anonymous candidate result
  parabola Entity
  target Point
  point_on_curve Fact
  optional symbol constraint Fact

output:
  selected_curve_point
  parameter_value?
  solved_parabola?

internal:
  CurveCandidateSelectionWitness
```

`PointList` may remain an exact anonymous result for a genuinely reusable
candidate-producing step. Common construction-plus-filter patterns should use a
family composite Macro so the candidate list does not enter Planner wire.

### 4.3 `two_moving_points_path_reduction`

Current input:

```text
path_minimum_target Fact
optional Planner-authored moving_point
```

Current output:

```text
path_transformation: PathWitness
```

Planned replacement:

```text
two_moving_points_path_minimum

input:
  path_minimum_target Fact
  moving-point membership Facts
  length/proportion binding Fact
  optional moving-point role hint

output:
  minimum_expression
  minimizing_configuration? when requested by a Goal

internal:
  path reduction, locus recovery, straightening, distance and witness
```

The standalone reduction phase should no longer be Planner-visible.

### 4.4 `broken_path_straightening_and_select`

Current input consists of a `PathWitness`, moving locus, fixed endpoints and
line points. It returns a `PathCandidate`, an auxiliary point and straightened
endpoints.

Planned role: internal shared search engine only. It has no Planner-facing
contract after migration.

### 4.5 `path_minimum_by_straightened_distance`

Current input:

```text
endpoint_1
endpoint_2
parameter_value?
```

Current output:

```text
path_minimum_expression
evaluated_path_minimum_expression?
```

Planned role: internal distance primitive for family path Macros. A direct
distance capability may remain available only when the two endpoints themselves
are the problem-level mathematical inputs. Its public result is a single
`minimum_expression`.

### 4.6 `broken_path_straightening_minimum_expression`

Current input:

```text
path_transformation: PathWitness
moving_locus: Line?
parameter_value: Symbol?
```

Current output includes a selected scheme, auxiliary point, two internal
endpoints, a minimum expression and an evaluated expression.

Planned replacement:

```text
single_moving_point_path_minimum

input:
  path_minimum_target Fact
  moving-locus Fact
  optional moving-point role hint
  optional parameter Entity

output:
  minimum_expression
  minimizing_point? when requested

internal:
  straightening candidates, selected construction, endpoints and witness
```

### 4.7 `square_path_dimension_reduction`

Current input:

```text
path_minimum_target Fact
square Fact
midpoint Fact
square_center Fact
Planner-authored moving_point
```

Current output:

```text
path_transformation: PathWitness
```

Planned replacement:

```text
square_relation_path_minimum

input:
  path target, square, midpoint, center and relevant locus Facts
  optional moving-point role hint

output:
  minimum_expression
  minimizing_configuration? when requested

internal:
  square reduction, locus derivation, straightening and distance witness
```

### 4.8 Weighted Path Pair

The current two-step public pipeline is:

```text
weighted_axis_path_triangle_transform
  -> auxiliary_point
  -> path_transformation
  -> auxiliary_locus

linked_broken_path_minimum_expression
  consumes the three results plus four more public arguments
  -> minimum_expression
```

Planned replacement:

```text
weighted_axis_path_minimum

input:
  path_minimum_target Fact
  weight/binding Fact
  axis-membership Fact
  dynamic-constraint Fact
  optional moving/fixed role hints

output:
  minimum_expression

internal:
  weighted triangle construction, auxiliary point/locus, path equivalence,
  linked minimum calculation and witness
```

The path structure must come from `path_minimum_target`, not be smuggled through
a `minimum_value` Fact. The given minimum value remains a separate input to a
later parameter-solving capability.

### 4.9 `equal_length_ray_path_reduction`

Current required Fact inputs:

```text
path_minimum_target
equal_length_condition
point_on_segment
point_on_ray
```

Planner-authored roles are dynamically exposed only when the four Facts leave a
structural ambiguity:

```text
anchor
reference_point
ray_point
fixed_point
```

Public output:

```text
minimum_expression: MinimumExpression
```

The target boundary is:

```text
equal_length_ray_path_reduction

input:
  the four structured Facts
  optional role hints only when the Facts do not uniquely bind a role

output:
  minimum_expression
  segment_minimizing_point / ray_minimizing_point only when required by a Goal

internal:
  bounded role search
  auxiliary construction
  structural SAS and path-equivalence proof
  direct-intersection, reflection and endpoint minimum candidates
  exact attainment checks under the problem parameter domain
  PathMinimumWitness
```

The public capability ID remains stable. Internal point construction, Method
arguments and `PathMinimumWitness` never enter FunctionalPlan content.

## 5. Closed Decisions For Equal-Length Ray Path Minimum

F5-F4.1 fixes the following decisions:

1. Unique Fact structure hides all point roles. Only ambiguous roles are exposed
   as candidate-restricted enums; an authored value is a search hint.
2. The Macro searches bounded role assignments and finite minimum strategies.
   The auxiliary construction and equivalence proof are generated and verified
   from structured geometry, not authored as Planner choices.
3. `BN=MG` and the objective replacement require structural equal-length and SAS
   evidence. A sampled numeric equality is never accepted as proof.
4. Both minimizers stay in `PathMinimumWitness`. A point becomes a public return
   only when a Goal explicitly asks for that point.
5. Equivalent winners are ordered by call count, symbolic complexity and stable
   candidate ID. Non-equivalent valid winners fail with
   `functional.macro_search_ambiguous`.
6. Explanation and Visual receive constructions, equivalence proof, legal
   domain, selected strategy, minimum expression, minimizers and attainment
   checks. Candidate IDs, runtime paths and provenance identities remain
   authority/debug-only.

### 5.1 Authority Timing Closed

F5-F4.2 implements the full role-authority sequence before per-call F5-C
finalization:

```text
multiple structure-valid role candidates
  -> execute upstream dependencies
  -> isolated shadow compile/runtime for every candidate
  -> select one runtime-proven winner
  -> build that call's F5-C source binding from the winner
  -> clean replay and commit
```

`MacroPreparationAuthority` records authored hints, the scope-safe dependency
envelope, upstream exact-state signature, every verified role candidate and the
winner. Only the chosen objects enter finalized F5-C input bindings, source
units and provenance. The winner is then compiled and executed again from a
clean branch; shadow results are never copied into the transaction.

The implementation covers wrong authored hints, unique winners, equivalent
multi-winner tie-breaking, non-equivalent ambiguity, all-candidate failure,
budget limits, zero shadow writes and clean-replay drift. The old compiler-time
single-candidate rejection and post-execution single-candidate authentication
path have been removed.

The post-completion review also made the registry the sole owner of preparation
context construction and evidence creation. Shadow evaluation may convert only
an explicitly planner-repairable diagnostic into a rejected candidate;
configuration errors, contract drift and unknown exceptions fail immediately.
Upstream state and winner replay signatures use canonical typed payloads (and
SymPy structural representations), never Python `repr()`.

Equivalent-candidate tie-breaking uses the actual Method invocation count from
each shadow-lowered graph; a role candidate builder must not estimate or hardcode
that count. Mixed-scope Goal repair preserves frozen barriers only when the old
editable interval is provable: equal-cardinality replacements have an ordinal
mapping, while added or removed steps across three or more editable islands must
retain enough old step ids to identify their islands. An ambiguous renamed
replacement fails loud instead of using proportional placement.

The legacy debug `equal_length_ray_point` selector may still require one
structural candidate, but the recipe compiler never imports it or the role
candidate builder: runtime-search compilation consumes only the prepared winner
authority. F5-F4.3 must remove this second role-inference path (or route the
standalone debug Method through `MacroPreparationService`) before another Macro
is migrated; new Macros must not copy the selector pattern.

Until each remaining Macro has a registered candidate builder, validation
policy, lowerer, postcondition and evidence builder, it is deliberately exposed
as `direct`. At the end of F5-F4.2 the only production `runtime_search` Macro is
`equal_length_ray_path_reduction`.

## 6. Migration Order

1. **Done (F5-F4.1):** establish `equal_length_ray_path_reduction` as the
   reference Macro.
2. **Done (F5-F4.1):** add `PathMinimumWitness`, prompt projection, schema and
   `VerifiedFunctionalPlanExecution`.
3. **Done (F5-F4.2):** move runtime-search winner
   selection before per-call F5-C binding, converge Method reads on explicit
   read authority, and make Goal checkpoint v3 the sole production restore
   owner.
4. **Next (F5-F4.2R):** replace production binding selectors with typed
   `MethodInputSourceSpec | MethodInputDerivationSpec`, migrate the common
   quadratic vertical slice, and remove production `_select()` fallback before
   another Path Macro is enabled for runtime search.
5. **Pending (F5-F4.3):** migrate the three other path families to family-level
   pre-binding runtime-search Macros.
6. **Pending (F5-F4.3):** internalize generic straightening and distance phases.
7. **Pending (F5-F4.3):** migrate point-construction Macros and optional family
   composites.
8. **Pending (F5-F4.3):** add static guards forbidding internal Path types and
   Method wiring in Prompt,
   Plan and retry wire.
9. **Pending (F5-F4.3):** retire the standalone
   `equal_length_ray_point` debug selector and its bypass contract, or make the
   debug entry consume the same prepared role authority as production.

## 7. Completion Gates

```text
Planner prompt internal Path types == 0
Planner-authored internal Method arguments == 0
production semantic selectors == 0
production FunctionAdapterRegistry._select fallback == 0
unique runtime-valid role correction succeeds deterministically
non-equivalent runtime ambiguity fails loud
shadow candidate ghost writes == 0
winner clean replay drift == 0
minimum_expression and witness provenance coverage == 100%
Explanation can reconstruct every path proof without parsing LLM prose
```
