"""Math argument spelling in the existing content/Scope-repair prompts."""

from copy import deepcopy

from ._paths import repo_root
from .method_math_arguments import (
    MATH_EXPRESSIONS,
    MethodMathArgumentContract,
    MethodMathArgumentError,
    _pointer,
)
from .scoped_functional_few_shots import load_scoped_functional_few_shot


class MathStrategyPayloadBuilder:
    """Decorate the original builder without changing its authority or rules."""

    def __init__(self, base, resolver):
        self.base, self.resolver = base, resolver

    def _adapt(self, payload):
        resolver = self.resolver
        payload = deepcopy(payload)
        payload["argument_encoding"] = MATH_EXPRESSIONS
        root = deepcopy(resolver.candidate["root"])
        for scope, pointer in resolver.scope_paths.items():
            _pointer({"root": root}, pointer)["scope_ref"] = scope
        for goal in resolver.context.goal_views:
            pointer = resolver.bundle.provenance[goal.goal_unit_id]["path"]
            _pointer({"root": root}, pointer)["goal_ref"] = goal.answer_ref.ref
        payload["problem_planning_context"] = {"root": root}

        def spellings(refs):
            result = []
            for ref in refs:
                expressions = [
                    e
                    for s in resolver.sources
                    if s.authority.semantic_ref.ref == ref
                    for e in s.expressions
                ]
                if not expressions:
                    raise MethodMathArgumentError(
                        "planner.math_schema_spelling_unavailable",
                        "$",
                        f"No mathematical spelling for schema ref {ref}",
                        configuration=True,
                    )
                result.extend(expressions)
            return list(dict.fromkeys(result))

        for cap in payload["functional_capability_catalog"]["capabilities"]:
            original = resolver.catalog.get(cap["capability_id"])
            math_args = []
            for argument in cap.get("args", []):
                declared = next(a for a in original.args if a.name == argument["name"])
                contract = MethodMathArgumentContract.from_argument(declared).to_payload()
                if "allowed_refs" in argument:
                    allowed_spellings = spellings(argument["allowed_refs"])
                    # Prefer a real spelling when the catalog has a closed
                    # source set; the generic example remains valid for open
                    # arguments and capabilities without enumerated sources.
                    if allowed_spellings:
                        contract["preferred_examples"] = allowed_spellings[:3]
                if (
                    argument["name"] == "right_angle_equal_length"
                    and cap["capability_id"]
                    in {
                        "right_angle_equal_length_candidates",
                        "right_angle_equal_length_construct_and_select",
                    }
                ):
                    for name, note, example in (
                        ("angle", "直角条件；只写基本等式。", "∠CAD=90°"),
                        ("equal_length", "等长条件；只写基本等式。", "AC=AD"),
                    ):
                        primitive = deepcopy(contract)
                        primitive.update(
                            form="equation",
                            preferred_examples=[example],
                            fallback_examples=[],
                            invalid_examples=["∠CAD=90° ∧ AC=AD"],
                            note=note,
                        )
                        math_args.append({"name": name, "math_argument": primitive})
                    continue
                if argument["name"] == "path_minimum_target":
                    example = (
                        "sqrt(2)*MN+AN"
                        if cap["capability_id"] == "weighted_axis_path_minimum"
                        else "EG+FG"
                    )
                    contract.update(
                        domain_type="Expression",
                        form="path_sum",
                        preferred_examples=[example],
                        fallback_examples=[],
                        invalid_examples=[f"min({example})", "EG"],
                        note=(
                            "直接写要最小化的路径表达式；不要写 min(...)，"
                            "不要把路径拆成数组。"
                        ),
                    )
                    contract.pop("fact_types", None)
                math_args.append({"name": argument["name"], "math_argument": contract})
            cap["args"] = math_args
        # Enum constraints on SourceRef spellings are projected to math strings.
        # The prompt exposes one math contract per argument; the original,
        # full output schema still validates the decoded candidate.
        schema = payload["output_json_schema"]
        definitions = schema["$defs"]

        def is_source(node, seen=()):
            if not isinstance(node, dict):
                return False
            ref = node.get("$ref", "")
            if ref == "#/$defs/source_ref":
                return True
            if ref.startswith("#/$defs/") and ref not in seen:
                return is_source(definitions[ref.rsplit("/", 1)[1]], (*seen, ref))
            return any(is_source(n, seen) for n in node.get("allOf", []))

        def visit(node):
            if isinstance(node, list):
                for item in node:
                    visit(item)
            elif isinstance(node, dict):
                if "enum" in node and is_source(node):
                    node["enum"] = spellings(node["enum"])
                for item in node.values():
                    visit(item)

        visit(schema)

        # Math mode splits the internal composite condition into two prompt
        # arguments.  The compiler still receives the original single source
        # ref after MethodMathArgumentResolver folds them back together.
        def split_right_angle_schema(node):
            if isinstance(node, list):
                for item in node:
                    split_right_angle_schema(item)
            elif isinstance(node, dict):
                capability = node.get("properties", {}).get("capability_id", {})
                if capability.get("const") in {
                    "right_angle_equal_length_candidates",
                    "right_angle_equal_length_construct_and_select",
                }:
                    args_schema = node.get("properties", {}).get("args")
                    if isinstance(args_schema, dict):
                        props = args_schema.get("properties", {})
                        props = {
                            key: value
                            for key, value in props.items()
                            if key != "right_angle_equal_length"
                        }
                        props.update(
                            {
                                "angle": {"$ref": "#/$defs/source_ref"},
                                "equal_length": {"$ref": "#/$defs/source_ref"},
                            }
                        )
                        args_schema["properties"] = props
                        args_schema["required"] = [
                            key
                            for key in args_schema.get("required", [])
                            if key != "right_angle_equal_length"
                        ] + ["angle", "equal_length"]
                for child in node.values():
                    split_right_angle_schema(child)

        split_right_angle_schema(schema)
        return payload

    def build_scoped(self, *args, **kwargs):
        payload = self._adapt(self.base.build_scoped(*args, **kwargs))
        selection = payload.get("functional_few_shot_selection")
        if selection is not None:
            example = load_scoped_functional_few_shot(
                selection["example_id"],
                directory=repo_root() / "internal" / "functional-few-shots-v2-math",
            )
            if example is None:
                raise MethodMathArgumentError(
                    "planner.math_example_missing",
                    "$",
                    selection["example_id"],
                    configuration=True,
                )
            payload["few_shot_examples"] = [example]
        if payload.get("previous_invalid_content"):
            payload["previous_invalid_content"], _ = self.resolver.transform(
                payload["previous_invalid_content"], encode=True
            )
        return payload

    def build_scope_repair(self, *args, **kwargs):
        payload = self._adapt(self.base.build_scope_repair(*args, **kwargs))
        payload["annotated_previous_plan"], _ = self.resolver.transform(
            payload["annotated_previous_plan"], encode=True
        )
        return payload
