"""Mathematical spelling of existing Method inputs, never a second planner.

The result is the existing SourceRef wire form. Scope ownership, exact result
reads, latest-state selection, method preconditions and execution remain owned
by the ordinary FunctionalPlan compiler. No expression creates a source fact.
"""

import json
from copy import deepcopy
from dataclasses import dataclass

from shuxueshuo_server.problem_understanding.notation_compile import (
    NotationValidator,
    Report,
    Scope,
    typecheck,
)
from shuxueshuo_server.problem_understanding.notation_parser import NotationError, parse
from shuxueshuo_server.problem_understanding.notation_semantics import Canonical
from shuxueshuo_server.solver.extraction.source_identity import thaw_json

SOURCE_REFS = "source-ref"
MATH_EXPRESSIONS = "math-expression/v1"
_RIGHT_ANGLE_CAPABILITIES = frozenset(
    {
        "right_angle_equal_length_candidates",
        "right_angle_equal_length_construct_and_select",
    }
)
_PATH_TARGET_ARGUMENT = "path_minimum_target"


class MethodMathArgumentError(ValueError):
    def __init__(self, code, path, message, *, configuration=False):
        self.code, self.path, self.message = code, path, message
        self.configuration = configuration
        super().__init__(f"{code} at {path}: {message}")

    def to_payload(self):
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class MethodMathArgumentContract:
    """Derived from the executable public argument, not a parallel type table."""

    domain_type: str
    fact_types: tuple[str, ...]
    required: bool = True
    cardinality: str = "one"
    form: str = "object_reference"
    preferred_examples: tuple[str, ...] = ()
    fallback_examples: tuple[str, ...] = ()
    invalid_examples: tuple[str, ...] = ()
    note: str = ""
    accepts_curve_expression: bool = False

    @classmethod
    def from_argument(cls, argument):
        kinds = argument.prompt_fact_types or argument.accepted_condition_kinds
        if not kinds and argument.domain_type == "Fact":
            # These immutable value projections are already in the executable
            # facade (Equation and coefficient aggregation respectively).
            kinds = {
                "Equation": ("coefficient_relation", "segment_length_relation"),
                "AngleEquality": ("angle_equality",),
            }.get(argument.runtime_type, ())
        types = "|".join((*argument.accepted_item_types, argument.runtime_type)).split(
            "|"
        )
        return cls(
            argument.domain_type or argument.runtime_type,
            tuple(kinds),
            required=argument.required,
            cardinality=argument.cardinality,
            form=_math_form(argument),
            preferred_examples=_preferred_examples(argument),
            fallback_examples=("A=(-1,0)",)
            if argument.domain_type == "Point"
            else (),
            invalid_examples=("D ∈ Γ",)
            if argument.domain_type == "Point"
            else (),
            note=argument.description.strip(),
            accepts_curve_expression="Parabola" in types,
        )

    def accepts(self, ref):
        if self.domain_type == "Fact":
            return ref.kind == "fact" and ref.value_type in self.fact_types
        if (
            self.domain_type == "Expression"
            and self.accepts_curve_expression
            and ref.kind == "function"
        ):
            return True
        return ref.kind in {
            "Point": ("point",),
            "Symbol": ("symbol",),
            "QuadraticFunction": ("function",),
            "Expression": ("expression",),
            "Segment": ("segment",),
            "Line": ("line",),
            "Ray": ("ray",),
            "Polygon": ("polygon",),
        }.get(self.domain_type, ())

    def to_payload(self):
        return {
            "encoding": MATH_EXPRESSIONS,
            "domain_type": self.domain_type,
            "required": self.required,
            "cardinality": self.cardinality,
            "form": self.form,
            "preferred_examples": list(self.preferred_examples),
            "fallback_examples": list(self.fallback_examples),
            "invalid_examples": list(self.invalid_examples),
            **({"note": self.note} if self.note else {}),
            **({"fact_types": list(self.fact_types)} if self.fact_types else {}),
        }


def _math_form(argument):
    domain = argument.domain_type or argument.runtime_type
    if domain == "Fact":
        if set(argument.accepted_condition_kinds).intersection(
            {"right_angle", "equal_length", "right_angle_equal_length"}
        ):
            return "equation"
        return "membership" if argument.accepted_condition_kinds else "equation"
    if domain in {"Symbol", "SymbolList"}:
        return "symbol"
    if domain in {"Expression", "QuadraticFunction"} or "Parabola" in (
        argument.accepted_item_types or (argument.runtime_type,)
    ):
        return "curve_or_expression"
    return "object_reference"


def _preferred_examples(argument):
    domain = argument.domain_type or argument.runtime_type
    if domain == "Point":
        return ("A",)
    if domain in {"Symbol", "SymbolList"}:
        return ("b",)
    if domain == "Fact":
        if "minimum_value" in argument.accepted_condition_kinds:
            return ("min(sqrt(2)*MN+AN)=21/4",)
        return ("a=1",)
    if domain in {"QuadraticFunction", "Expression"}:
        return ("Γ",)
    return ()


class _ReadOnlyScope(Scope):
    def declare(self, name, kind, *, local=False):
        raise NotationError("binding.unknown_or_invisible", name)


def _pointer(value, pointer):
    for part in pointer.strip("/").split("/"):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _render(ast):
    kind = ast[0]
    if kind in ("name", "number"):
        return ast[1]
    if kind == "neg":
        return f"(-{_render(ast[1])})"
    if kind == "extremum":
        variables = "_{" + ",".join(ast[2]) + "}" if ast[2] else ""
        return f"{ast[1]}{variables}({_render(ast[3])})"
    if kind == "call":
        return f"{ast[1]}({','.join(_render(a) for a in ast[2:])})"
    if kind in ("+", "-", "*", "/", "^", "=", "!=", "<", ">", "<=", ">=", "∈"):
        return f"({_render(ast[1])}{kind}{_render(ast[2])})"
    raise NotationError("planner.math_render_unsupported", kind)


def _extrema(ast):
    if isinstance(ast, list):
        if ast and ast[0] == "extremum":
            yield ast
        else:
            for child in ast[1:]:
                yield from _extrema(child)


def _unwrapped_minimum_expression(text):
    """Return the body of an unindexed ``min(...)`` spelling, if present."""

    try:
        extrema = tuple(_extrema(parse(text)))
    except (NotationError, ValueError, TypeError, RecursionError):
        return None
    if len(extrema) != 1:
        return None
    operator, variables, body = extrema[0][1], extrema[0][2], extrema[0][3]
    if operator != "min":
        return None
    return _render(body)


def _contains_extremum(text):
    try:
        return any(True for _ in _extrema(parse(text)))
    except (NotationError, ValueError, TypeError, RecursionError):
        return False


@dataclass(frozen=True)
class _Source:
    authority: object
    expressions: tuple[str, ...]
    source_paths: tuple[str, ...]


class MethodMathArgumentResolver:
    def __init__(self, bundle, planning_context, binding_catalog, capability_catalog):
        if not hasattr(bundle, "candidate") or not hasattr(bundle, "provenance"):
            raise MethodMathArgumentError(
                "planner.math_source_unavailable",
                "$",
                "Mathematical argument encoding requires a notation bundle.",
                configuration=True,
            )
        if (
            planning_context.bundle_authority_token != bundle.authority_token
            or binding_catalog.planning_context_id
            != planning_context.planning_context_id
        ):
            raise MethodMathArgumentError(
                "planner.math_authority_drift",
                "$",
                "Math source and binding authority differ.",
                configuration=True,
            )
        binding_catalog.verify_authority()
        self.bundle, self.context = bundle, planning_context
        self.bindings, self.catalog = binding_catalog, capability_catalog
        self.candidate = thaw_json(bundle.candidate)
        self.parents = {s.scope_id: s.parent_scope_id for s in planning_context.scopes}
        self.goal_owners = {
            g.answer_ref.ref: g.owner_scope_id for g in planning_context.goal_views
        }
        self.environments = {}
        self.scope_paths = {}
        report = NotationValidator().validate(self.candidate)
        if not report.ok:
            raise MethodMathArgumentError(
                "planner.math_source_invalid",
                "$",
                "Notation source no longer validates.",
                configuration=True,
            )
        env_by_pointer = {}

        def environment(node, pointer="/root", path="r", parent=None):
            env = _ReadOnlyScope(Report(), path, parent)
            env.local.update(
                {o["name"]: o for o in report.objects if o["scope"] == path}
            )
            env_by_pointer[pointer] = env
            for i, child in enumerate(node.get("children", [])):
                environment(child, f"{pointer}/children/{i}", f"{path}.c{i}", env)

        environment(self.candidate["root"])
        for scope in planning_context.scopes:
            pointer = bundle.provenance[scope.source_scope_unit_id]["path"]
            self.environments[scope.scope_id] = env_by_pointer[pointer]
            self.scope_paths[scope.scope_id] = pointer
        self.entities = {
            e.unit_id: e
            for s in bundle.source_graph.root_scope.iter_scopes()
            for e in s.entities
        }
        self.facts = {
            f.unit_id: f
            for s in bundle.source_graph.root_scope.iter_scopes()
            for f in s.facts
        }
        self.sources = tuple(
            self._source(a)
            for a in planning_context.ref_authorities.values()
            if a.usage == "input"
        )
        self._keys = {}

    def _source(self, authority):
        paths = tuple(
            sorted(
                {self.bundle.provenance[u]["path"] for u in authority.source_unit_ids}
            )
        )
        ref = authority.semantic_ref
        expressions = []
        if ref.kind != "fact":
            for uid in authority.source_unit_ids:
                entity = self.entities.get(uid)
                if entity:
                    source = _pointer(
                        self.candidate, self.bundle.provenance[uid]["path"]
                    )
                    if entity.kind == "named_ray":
                        expressions.append(
                            f"ray({entity.attributes['origin']},{entity.attributes['through']})"
                        )
                        continue
                    if entity.kind == "polygon":
                        expressions.append(
                            f"quadrilateral({','.join(entity.attributes['vertices'])})"
                        )
                        continue
                    # An unnamed constructed object (e.g. vertex(Γ)) retains
                    # its source expression rather than a compiler-made label.
                    expressions.append(
                        source["object"]
                        if isinstance(source, dict) and "object" in source
                        else entity.local_id
                    )
        elif ref.value_type != "math_assertion":
            for pointer in paths:
                source = _pointer(self.candidate, pointer)
                if isinstance(source, dict):
                    if source.get("kind") == "find_minimum":
                        expressions.append(f"min({source['expression']})")
                elif isinstance(source, str):
                    if ref.value_type == "path_minimum_target":
                        expressions.extend(_render(v) for v in _extrema(parse(source)))
                    else:
                        expressions.append(source)
            if ref.value_type == "right_angle_equal_length" and len(expressions) > 1:
                # The executable relation remains one trusted source ref, but
                # the math prompt exposes its two primitive spellings.  Both
                # spellings bind back to this same relation; no composite Fact
                # syntax is shown to the model.
                angle_expression = None
                equal_expression = None
                for unit_id in authority.source_unit_ids:
                    fact = self.facts.get(unit_id)
                    if fact is None:
                        continue
                    attrs = fact.attributes
                    if fact.kind == "right_angle":
                        angle = attrs.get("angle", {})
                        angle_expression = (
                            f"∠{angle['start']}{angle['vertex']}{angle['end']}=90°"
                        )
                    elif fact.kind == "equal_length":
                        left, right = attrs.get("left", {}), attrs.get("right", {})
                        equal_expression = (
                            f"{left['start']}{left['end']}={right['start']}{right['end']}"
                        )
                primitive = [
                    item for item in (angle_expression, equal_expression) if item
                ]
                expressions = primitive or [
                    " ∧ ".join(f"({e})" for e in expressions)
                ]
        return _Source(authority, tuple(dict.fromkeys(expressions)), paths)

    def _key(self, text, scope_id):
        cache_key = (scope_id, text)
        if cache_key in self._keys:
            return self._keys[cache_key]
        bound = self.environments[scope_id].bind(parse(text))
        kind = typecheck(bound)
        # Canonical math treats extrema as inert path atoms. Validate explicit
        # motion hints against phase-two proofs before its canonicalizer drops
        # the hints; min_b(S) must never acquire min_n(S)'s binding.
        for extremum in _extrema(bound):
            if extremum[2]:
                variables = {v[1] for v in extremum[2]}
                body = Canonical().math(extremum[3])
                scope_pointer = self.scope_paths[scope_id]
                if not any(
                    set(motion["variables"]) == variables
                    and (
                        scope_pointer == motion["path"].rsplit("/", 2)[0]
                        or scope_pointer.startswith(
                            motion["path"].rsplit("/", 2)[0] + "/children/"
                        )
                    )
                    and Canonical().math(thaw_json(motion["expression"])) == body
                    for motion in self.bundle.motion_bindings
                ):
                    raise NotationError("binding.motion_variables_mismatch")
        canonical = Canonical()
        if kind == "boolean":
            value = canonical.logic([bound])
        elif kind in ("scalar", "length", "area", "angle"):
            value = [kind, canonical.math(bound)]
        else:
            value = [kind, canonical.tree(bound)]
        if canonical.obligations:
            raise NotationError("planner.math_unproved_equivalence")
        result = json.dumps(value, sort_keys=True, ensure_ascii=False)
        self._keys[cache_key] = result
        return result

    def _visible(self, scope_id, owner):
        while scope_id is not None:
            if scope_id == owner:
                return True
            scope_id = self.parents[scope_id]
        return False

    def _point_for_coordinate(self, wanted, *, scope_id):
        """Map a coordinate fact spelling back to its existing Point identity.

        This is deliberately a narrow fallback for a common model spelling
        such as ``A=(-1,0)``.  The coordinate fact must already be visible and
        share source ownership with exactly one visible Point declaration; no
        Point is synthesized and sibling scopes are never searched.
        """
        coordinate_sources = []
        for source in self.sources:
            ref = source.authority.semantic_ref
            if ref.kind != "fact" or ref.value_type != "point_coordinate":
                continue
            if not self._visible(scope_id, source.authority.owner_scope_id):
                continue
            for spelling in source.expressions:
                try:
                    if self._key(spelling, source.authority.owner_scope_id) == wanted:
                        coordinate_sources.append(source)
                        break
                except (NotationError, ValueError, TypeError, RecursionError):
                    continue
        if len(coordinate_sources) != 1:
            return None
        coordinate = coordinate_sources[0]
        coordinate_units = set(coordinate.authority.source_unit_ids)
        point_sources = []
        for source in self.sources:
            ref = source.authority.semantic_ref
            if ref.kind != "point" or not self._visible(
                scope_id, source.authority.owner_scope_id
            ):
                continue
            if coordinate_units.intersection(source.authority.source_unit_ids):
                point_sources.append(source)
        if len(point_sources) != 1:
            return None
        return point_sources[0], coordinate

    @staticmethod
    def _condition_arg_name(capability_id, arg_name):
        if capability_id in _RIGHT_ANGLE_CAPABILITIES and arg_name in {
            "angle",
            "equal_length",
        }:
            return "right_angle_equal_length"
        return arg_name

    def _primitive_condition_spellings(self, ref, *, scope_id):
        for source in self.sources:
            if source.authority.semantic_ref.ref != ref:
                continue
            if not self._visible(scope_id, source.authority.owner_scope_id):
                continue
            if source.authority.semantic_ref.value_type == "right_angle_equal_length":
                return tuple(source.expressions)
        return ()

    def resolve(
        self,
        capability_id,
        arg_name,
        expression,
        *,
        scope_id,
        path="$.args",
        output=False,
    ):
        if not isinstance(expression, str):
            # StepResultRef and malformed non-string values retain their exact
            # shape; the existing compiler owns their type and visibility checks.
            return deepcopy(expression), None
        if scope_id not in self.parents:
            raise MethodMathArgumentError(
                "functional.math_scope_unknown", path, "Unknown owning Scope."
            )
        cap = self.catalog.get(capability_id)
        if cap is None:
            return expression, None
        arg_name = self._condition_arg_name(capability_id, arg_name)
        arg = next(
            (a for a in cap.args if a.name == arg_name or arg_name in a.aliases), None
        )
        if not output and arg is None:
            return expression, None  # Preserve existing unknown-argument diagnostics.
        plain_path_target = (
            not output
            and arg_name == _PATH_TARGET_ARGUMENT
        )
        contract = (
            None
            if output
            else MethodMathArgumentContract.from_argument(arg)
        )
        if plain_path_target and _contains_extremum(expression):
            raise MethodMathArgumentError(
                "functional.math_argument_invalid",
                path,
                "path_minimum_target expects the path expression itself, such as EG+FG; "
                "the minimum operator is supplied by the Method.",
            )
        try:
            wanted = self._key(expression, scope_id)
        except (NotationError, ValueError, TypeError, RecursionError) as exc:
            raise MethodMathArgumentError(
                "functional.math_argument_invalid", path, str(exc)
            ) from exc
        matches = []
        for source in self.sources:
            a = source.authority
            if not self._visible(scope_id, a.owner_scope_id):
                continue
            if output and a.semantic_ref.kind == "fact":
                continue
            if plain_path_target:
                if not (
                    a.semantic_ref.kind == "fact"
                    and a.semantic_ref.value_type == "path_minimum_target"
                ):
                    continue
            elif contract and not contract.accepts(a.semantic_ref):
                continue
            for spelling in source.expressions:
                candidates = [spelling]
                if plain_path_target:
                    unwrapped = _unwrapped_minimum_expression(spelling)
                    if unwrapped is not None:
                        candidates.append(unwrapped)
                for candidate in candidates:
                    try:
                        key = self._key(candidate, a.owner_scope_id)
                    except (NotationError, ValueError, TypeError, RecursionError):
                        continue
                    if key == wanted:
                        matches.append(source)
                        break
                if matches and matches[-1] is source:
                    break
        # A Point argument normally uses its object spelling.  Accept a
        # coordinate equality only as a unique, source-backed fallback and
        # return the existing Point ref to the unchanged compiler.
        coordinate_evidence = None
        if not matches and contract and contract.domain_type == "Point":
            fallback = self._point_for_coordinate(wanted, scope_id=scope_id)
            if fallback is not None:
                matches.append(fallback[0])
                coordinate_evidence = fallback[1]
        if len(matches) != 1:
            raise MethodMathArgumentError(
                "functional.math_argument_ambiguous"
                if matches
                else "functional.math_argument_unresolved",
                path,
                f"{capability_id}.{arg_name}: {expression!r} matches {len(matches)} visible typed sources.",
            )
        source = matches[0]
        ref = source.authority.semantic_ref.ref
        # Do not grant visibility that the original binding catalog would deny.
        self.bindings.resolve_input_binding(scope_id=scope_id, local_ref=ref)
        source_paths = list(source.source_paths)
        source_unit_ids = list(source.authority.source_unit_ids)
        if coordinate_evidence is not None:
            source_paths.extend(path for path in coordinate_evidence.source_paths if path not in source_paths)
            source_unit_ids.extend(
                uid for uid in coordinate_evidence.authority.source_unit_ids
                if uid not in source_unit_ids
            )
        return ref, {
            "path": path,
            "expression": expression,
            "ref": ref,
            "scope_ref": scope_id,
            "source_paths": source_paths,
            "source_unit_ids": source_unit_ids,
        }

    def spelling(
        self, ref, *, scope_id, capability_id=None, arg_name=None, output=False
    ):
        if not isinstance(ref, str):
            return deepcopy(ref)
        candidates = [
            s
            for s in self.sources
            if s.authority.semantic_ref.ref == ref
            and self._visible(scope_id, s.authority.owner_scope_id)
        ]
        for source in candidates:
            if arg_name == _PATH_TARGET_ARGUMENT:
                for expression in source.expressions:
                    unwrapped = _unwrapped_minimum_expression(expression)
                    if unwrapped is not None:
                        return unwrapped
            for expression in source.expressions:
                try:
                    resolved, _ = self.resolve(
                        capability_id,
                        arg_name,
                        expression,
                        scope_id=scope_id,
                        output=output,
                    )
                except MethodMathArgumentError:
                    continue
                if resolved == ref:
                    return expression
        raise MethodMathArgumentError(
            "planner.math_spelling_unavailable",
            "$",
            f"No unique mathematical spelling for {scope_id}/{capability_id}.{arg_name}: {ref}",
            configuration=True,
        )

    def transform(self, payload, *, encode=False):
        """Only rewrite call args/targets; all ownership/repair fields survive."""
        value = deepcopy(payload)
        audit = []

        def step(item, scope, path):
            if not isinstance(item, dict):
                return
            cap = item.get("capability_id")
            capability = self.catalog.get(cap) if isinstance(cap, str) else None
            if capability is None:
                return
            for field in ("args", "output_targets"):
                args = item.get(field)
                if not isinstance(args, dict):
                    continue
                if (
                    field == "args"
                    and cap in _RIGHT_ANGLE_CAPABILITIES
                    and encode
                    and "right_angle_equal_length" in args
                ):
                    ref = args.pop("right_angle_equal_length")
                    spellings = self._primitive_condition_spellings(
                        ref, scope_id=scope
                    )
                    if len(spellings) == 2:
                        args["angle"], args["equal_length"] = spellings
                    else:
                        args["right_angle_equal_length"] = ref
                if (
                    field == "args"
                    and cap in _RIGHT_ANGLE_CAPABILITIES
                    and not encode
                    and ("angle" in args or "equal_length" in args)
                ):
                    primitive_items = [
                        (name, args.pop(name))
                        for name in ("angle", "equal_length")
                        if name in args
                    ]
                    resolved = []
                    for name, expression in primitive_items:
                        result, record = self.resolve(
                            cap,
                            name,
                            expression,
                            scope_id=scope,
                            path=f"{path}.{field}.{name}",
                        )
                        resolved.append(result)
                        if record:
                            audit.append(record)
                    if resolved and len(set(resolved)) == 1:
                        args["right_angle_equal_length"] = resolved[0]
                    elif resolved:
                        raise MethodMathArgumentError(
                            "functional.math_argument_ambiguous",
                            f"{path}.{field}",
                            "直角与等长条件没有绑定到同一个受信关系。",
                        )
                combined_condition = (
                    field == "args"
                    and cap in _RIGHT_ANGLE_CAPABILITIES
                    and not encode
                    and "right_angle_equal_length" in args
                )
                for name, original in list(args.items()):
                    if combined_condition and name == "right_angle_equal_length":
                        continue
                    if field == "args" and not any(
                        a.name == name or name in a.aliases for a in capability.args
                    ):
                        continue
                    items = original if isinstance(original, list) else [original]
                    converted = []
                    for i, expression in enumerate(items):
                        location = f"{path}.{field}.{name}" + (
                            f"[{i}]" if isinstance(original, list) else ""
                        )
                        if encode:
                            result = self.spelling(
                                expression,
                                scope_id=scope,
                                capability_id=cap,
                                arg_name=name,
                                output=field == "output_targets",
                            )
                        else:
                            result, record = self.resolve(
                                cap,
                                name,
                                expression,
                                scope_id=scope,
                                path=location,
                                output=field == "output_targets",
                            )
                            if record:
                                audit.append(record)
                        converted.append(result)
                    args[name] = (
                        converted if isinstance(original, list) else converted[0]
                    )

        def steps(items, scope, path):
            if isinstance(items, (list, tuple)):
                for i, item in enumerate(items):
                    step(item, scope, f"{path}[{i}]")

        if not isinstance(value, dict):
            return value, audit

        def mapping(node, key):
            result = node.get(key, {})
            return result if isinstance(result, dict) else {}

        for scope, items in mapping(value, "scope_steps").items():
            steps(items, scope, f"$.scope_steps.{scope}")
        for goal, body in mapping(value, "goal_plans").items():
            if isinstance(body, dict) and goal in self.goal_owners:
                steps(
                    body.get("steps"),
                    self.goal_owners[goal],
                    f"$.goal_plans.{goal}.steps",
                )
        for scope, replacement in mapping(value, "scope_replacements").items():
            if isinstance(replacement, dict):
                steps(
                    replacement.get("scope_steps"),
                    scope,
                    f"$.scope_replacements.{scope}.scope_steps",
                )
                for goal, body in mapping(replacement, "goals").items():
                    if isinstance(body, dict):
                        steps(
                            body.get("steps"),
                            scope,
                            f"$.scope_replacements.{scope}.goals.{goal}.steps",
                        )

        # Prompt projection only. Saved plans/checkpoints stay canonical and
        # are never decoded through this path on restore.
        def annotated(node, path):
            if not isinstance(node, dict):
                return
            scope = node.get("scope_ref")
            steps(node.get("scope_steps"), scope, f"{path}.scope_steps")
            for goal, body in mapping(node, "goals").items():
                if isinstance(body, dict):
                    steps(body.get("steps"), scope, f"{path}.goals.{goal}.steps")
            for i, child in enumerate(node.get("children", [])):
                annotated(child, f"{path}.children[{i}]")

        if encode and "root_scope" in value:
            annotated(value["root_scope"], "$.root_scope")
        return value, audit
