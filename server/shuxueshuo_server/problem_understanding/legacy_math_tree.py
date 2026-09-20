"""Read-only legacy-domain adapter for migration audits, not Solver admission.

Relations are translated structurally, without serializing the old domain to
notation and parsing it again. Only the comparison normalization is shared.
Unknown constructs fail closed. No answers, fixture IDs or source prose are used.
"""

import ast
from copy import deepcopy
from functools import reduce

from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft

from .notation_compile import Report, typecheck
from .notation_normalization import normalize_bound


class LegacyTreeError(ValueError):
    pass


def call(name, *args):
    return ["call", name, *args]


def number(value):
    return ["number", str(value)]


class LegacyMathTree:
    def __init__(self):
        self.report = Report()
        self.coverage = []
        self.annotations = []
        self.scopes = []

    def build(self, payload):
        # Preserve the production parser as the old source boundary.
        draft = ProblemDraft.create(payload)
        self.report.semantic = self.scope(draft.graph.root_scope.wire_payload(), "r")
        self.report.semantic_normalization = normalize_bound(
            self.report.semantic, self.report.objects
        )
        return self.report

    def scope(self, source, path, inherited=None):
        env = dict(inherited or {})
        self.scopes.append(
            {"scope": path, "legacy_id": source["id"], "label": source["label"]}
        )
        for i, item in enumerate(source["entities"]):
            location = f"{path}.entities[{i}]"
            kind = item["kind"]
            if kind == "symbol" and item.get("role") == "function_variable":
                env[item["id"]] = ["bound", "coordinate_x"]
                self.annotations.append(
                    {
                        "path": location,
                        "kind": "bound_function_variable",
                        "source": item,
                    }
                )
            elif kind in ("point", "symbol", "quadratic_function"):
                mapped = {"symbol": "scalar", "quadratic_function": "curve"}.get(
                    kind, kind
                )
                ref = f"{path}:{mapped}:{item['id']}"
                env[item["id"]] = ["ref", ref, mapped]
                self.report.objects.append(
                    {"ref": ref, "name": item["id"], "kind": mapped, "scope": path}
                )
                if mapped == "scalar":
                    self.report.defaults.append(
                        {"ref": ref, "domain": "real", "origin": "code_default"}
                    )
            elif kind in ("polygon", "named_ray", "named_line"):
                # Named geometric composites are resolved after all point declarations.
                env[item["id"]] = {"composite": item}
            else:
                raise LegacyTreeError(f"unsupported entity at {location}: {kind}")
            self.coverage.append({"path": location, "kind": kind, "category": "entity"})

        def ref(name):
            value = env.get(name)
            if value is None:
                raise LegacyTreeError(
                    f"unknown or invisible legacy name {name!r} at {path}"
                )
            if isinstance(value, dict):
                item = value["composite"]
                if item["kind"] == "polygon":
                    if len(item["vertices"]) != 4:
                        raise LegacyTreeError(
                            "audit only supports four-vertex legacy polygons"
                        )
                    return call("quadrilateral", *(ref(p) for p in item["vertices"]))
                if item["kind"] == "named_ray":
                    return call("ray", ref(item["origin"]), ref(item["through"]))
                if item["kind"] == "named_line" and len(item["points"]) == 2:
                    return call("line", *(ref(p) for p in item["points"]))
                raise LegacyTreeError(f"unsupported named line at {path}: {item}")
            return deepcopy(value)

        for item in source["entities"]:
            if item["kind"] in ("polygon", "named_ray", "named_line"):
                self.annotations.append(
                    {
                        "scope": path,
                        "kind": "composite_identity",
                        "source": item,
                        "ast": ref(item["id"]),
                    }
                )

        def scalar(text):
            text = str(text).strip().replace("−", "-").replace("^", "**")
            if len(text) > 1024:
                raise LegacyTreeError("legacy scalar length limit")
            try:
                syntax = ast.parse(text, mode="eval")
            except (SyntaxError, RecursionError) as exc:
                raise LegacyTreeError(f"invalid legacy scalar {text!r}") from exc
            if sum(1 for _ in ast.walk(syntax)) > 256:
                raise LegacyTreeError("legacy scalar node limit")

            def visit(node, depth=0):
                if depth > 32:
                    raise LegacyTreeError("legacy scalar depth limit")
                if isinstance(node, ast.Name):
                    return ref(node.id)
                if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                    return number(ast.get_source_segment(text, node))
                if isinstance(node, ast.UnaryOp) and isinstance(
                    node.op, (ast.UAdd, ast.USub)
                ):
                    value = visit(node.operand, depth + 1)
                    return ["neg", value] if isinstance(node.op, ast.USub) else value
                if isinstance(node, ast.BinOp):
                    op = {
                        ast.Add: "+",
                        ast.Sub: "-",
                        ast.Mult: "*",
                        ast.Div: "/",
                        ast.Pow: "^",
                    }.get(type(node.op))
                    if op:
                        return [
                            op,
                            visit(node.left, depth + 1),
                            visit(node.right, depth + 1),
                        ]
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "sqrt"
                    and len(node.args) == 1
                    and not node.keywords
                ):
                    return call("sqrt", visit(node.args[0], depth + 1))
                raise LegacyTreeError(f"unsupported scalar syntax in {text!r}")

            return visit(syntax.body)

        def segment(value):
            return [ref(value["start"]), ref(value["end"])]

        def length(value):
            return call("length", *segment(value))

        def angle(value):
            return call(
                "angle", ref(value["start"]), ref(value["vertex"]), ref(value["end"])
            )

        def path_expression(value):
            terms = [
                ["*", scalar(t["scale"]), length(t["segment"])] for t in value["terms"]
            ]
            if not terms:
                raise LegacyTreeError("empty legacy path expression")
            return reduce(lambda a, b: ["+", a, b], terms)

        def extremum(value):
            return ["extremum", "min", [], path_expression(value)]

        def on_axis(point, axis, curve=None):
            target = (
                call("axis", ref(curve))
                if axis == "symmetry"
                else ["axis_constant", f"{axis}_axis"]
            )
            return ["∈", point, target]

        def fact(item):
            kind = item["kind"]
            if kind == "function_expression":
                return [
                    [
                        "curve_definition",
                        ref(item["function"]),
                        scalar(item["expression"]),
                    ]
                ]
            if kind == "equation":
                pieces = item["expression"].split("=")
                if len(pieces) != 2:
                    raise LegacyTreeError(
                        "legacy equation must contain one equals sign"
                    )
                return [["=", scalar(pieces[0]), scalar(pieces[1])]]
            if kind in ("symbol_value", "symbol_constraint"):
                return [
                    [
                        item.get("operator", "="),
                        ref(item["symbol"]),
                        scalar(item["value"]),
                    ]
                ]
            if kind == "point_coordinate":
                return [
                    [
                        "=",
                        ref(item["point"]),
                        ["tuple", *(scalar(v) for v in item["value"])],
                    ]
                ]
            if kind == "point_construction":
                p, construction = ref(item["point"]), item["construction"]
                if construction == "origin":
                    return [["=", p, ["tuple", number(0), number(0)]]]
                owner = ref(item["owner"])
                if construction == "vertex":
                    return [["=", p, call("vertex", owner)]]
                if construction == "translated_point":
                    return [
                        [
                            "=",
                            p,
                            [
                                "+",
                                owner,
                                ["tuple", *(scalar(v) for v in item["vector"])],
                            ],
                        ]
                    ]
                if construction == "curve_at_x":
                    return [
                        ["∈", p, owner],
                        ["=", call("x", p), scalar(item["x_expression"])],
                    ]
                if construction == "axis_x_intercept":
                    return [
                        [
                            "∈",
                            p,
                            ["∩", call("axis", owner), ["axis_constant", "x_axis"]],
                        ]
                    ]
                if construction == "y_axis_intercept":
                    return [
                        ["=", ["∩", owner, ["axis_constant", "y_axis"]], ["set", p]]
                    ]
                if construction == "x_axis_intercept":
                    if "exclude_point" in item:
                        other = ref(item["exclude_point"])
                        return [
                            [
                                "=",
                                ["∩", owner, ["axis_constant", "x_axis"]],
                                ["set", other, p],
                            ],
                            ["!=", p, other],
                        ]
                    if "side" in item:
                        side = item["side"]
                        opposite = {"left": "right", "right": "left"}.get(side)
                        others = [
                            f
                            for f in source["facts"]
                            if f.get("construction") == construction
                            and f.get("owner") == item["owner"]
                            and f.get("side") == opposite
                        ]
                        if len(others) != 1:
                            raise LegacyTreeError(
                                "cannot resolve ordered intercept counterpart"
                            )
                        other = ref(others[0]["point"])
                        left, right = (p, other) if side == "left" else (other, p)
                        return [
                            [
                                "=",
                                ["∩", owner, ["axis_constant", "x_axis"]],
                                ["set", left, right],
                            ],
                            ["<", call("x", left), call("x", right)],
                        ]
                    return [["∈", p, ["∩", owner, ["axis_constant", "x_axis"]]]]
                raise LegacyTreeError(f"unsupported construction: {construction}")
            if kind == "point_on_curve":
                return [["∈", ref(item["point"]), ref(item["curve"])]]
            if kind == "point_on_curve_with_x":
                p, variable = ref(item["point"]), ref(item["x_symbol"])
                result = [["∈", p, ref(item["curve"])], ["=", call("x", p), variable]]
                if "x_range" in item:
                    result += [
                        [">", variable, scalar(item["x_range"][0])],
                        ["<", variable, scalar(item["x_range"][1])],
                    ]
                return result
            if kind == "point_on_axis":
                return [on_axis(ref(item["point"]), item["axis"], item.get("curve"))]
            if kind == "point_on_segment":
                return [
                    [
                        "∈",
                        ref(item["point"]),
                        call("segment", *segment(item["segment"])),
                    ]
                ]
            if kind == "point_on_ray":
                return [["∈", ref(item["point"]), ref(item["ray"])]]
            if kind == "quadrant_membership":
                signs = {
                    "第一象限": (">", ">"),
                    "第二象限": ("<", ">"),
                    "第三象限": ("<", "<"),
                    "第四象限": (">", "<"),
                }
                x, y = signs[item["quadrant"]]
                return [
                    [x, call("x", ref(item["point"])), number(0)],
                    [y, call("y", ref(item["point"])), number(0)],
                ]
            if kind == "right_angle":
                return [["=", angle(item["angle"]), ["degrees", number(90)]]]
            if kind == "angle_sum":
                total = reduce(
                    lambda a, b: ["+", a, b], [angle(a) for a in item["angles"]]
                )
                return [["=", total, ["degrees", scalar(item["value"])]]]
            if kind == "equal_length":
                return [["=", length(item["left"]), length(item["right"])]]
            if kind == "length_relation":
                return [
                    [
                        "=",
                        *[
                            ["*", scalar(item[s]["scale"]), length(item[s]["segment"])]
                            for s in ("left", "right")
                        ],
                    ]
                ]
            if kind == "length_value":
                return [
                    [
                        "=",
                        ["^", length(item["segment"]), number(item.get("power", 1))],
                        scalar(item["value"]),
                    ]
                ]
            if kind == "midpoint":
                return [
                    [
                        "=",
                        ref(item["point"]),
                        call("midpoint", *segment(item["segment"])),
                    ]
                ]
            if kind == "minimum_value_given":
                return [["=", extremum(item["expression"]), scalar(item["value"])]]
            if kind == "minimum_target":
                # A Solver target descriptor is not an extra given proposition.
                self.annotations.append(
                    {
                        "scope": path,
                        "kind": kind,
                        "target": path_expression(item["expression"]),
                        "source": item,
                    }
                )
                return []
            if kind == "square":
                polygon = ref(item["polygon"])
                side = segment(item["side"])
                if side not in ([polygon[2], polygon[3]], [polygon[3], polygon[2]]):
                    raise LegacyTreeError(
                        "square side differs from ordered first polygon edge"
                    )
                result = [call("square", *polygon[2:])]
                orientation = item.get("orientation")
                if orientation:
                    if orientation["relation"] != "below_x_axis":
                        raise LegacyTreeError("unsupported square orientation")
                    result.append(
                        ["<", call("y", ref(orientation["point"])), number(0)]
                    )
                return result
            if kind == "square_center":
                vertices = ref(item["square"])[2:]
                return [
                    [
                        "=",
                        ref(item["point"]),
                        call("midpoint", vertices[i], vertices[i + 2]),
                    ]
                    for i in (0, 1)
                ]
            raise LegacyTreeError(f"unsupported legacy fact: {kind}")

        facts = []
        for i, item in enumerate(source["facts"]):
            translated = fact(item)
            for value in translated:
                if typecheck(value) != "boolean":
                    raise LegacyTreeError(f"nonboolean legacy fact: {item}")
            facts.extend(translated)
            self.coverage.append(
                {
                    "path": f"{path}.facts[{i}]",
                    "kind": item["kind"],
                    "category": "fact",
                    "ast": translated,
                    "source": item,
                }
            )
        goals = []
        for i, item in enumerate(source["goals"]):
            kinds = {
                "point_coordinate": "find_coordinates",
                "quadratic_equation": "find_equation",
                "parameter_value": "find_value",
                "minimum_value": "find_minimum",
            }
            if item["kind"] not in kinds:
                raise LegacyTreeError(f"unsupported legacy goal: {item['kind']}")
            goal = {
                "kind": kinds[item["kind"]],
                "target": path_expression(item["expression"])
                if item["kind"] == "minimum_value"
                else ref(item["target"]),
            }
            goals.append(goal)
            self.coverage.append(
                {
                    "path": f"{path}.goals[{i}]",
                    "kind": item["kind"],
                    "category": "goal",
                    "ast": goal,
                    "source": item,
                }
            )
        return {
            "scope": path,
            "facts": facts,
            "goals": goals,
            "uncertainties": [],
            "children": [
                self.scope(c, f"{path}.c{i}", env)
                for i, c in enumerate(source["children"])
            ],
        }
