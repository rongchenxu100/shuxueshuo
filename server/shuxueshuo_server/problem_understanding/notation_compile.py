"""Lexical binding and typed validation of the small mathematical language."""

import re
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dc_field

from jsonschema import Draft202012Validator

from .identity import encoded
from .notation_contract import schema
from .notation_parser import BUILTINS, NotationError, definition, node, parse

ARITY = {
    "sqrt": 1,
    "tan": 1,
    "length": 2,
    "angle": 3,
    "triangle": 3,
    "area": 1,
    "segment": 2,
    "line": 2,
    "ray": 2,
    "midpoint": 2,
    "square": 4,
    "parallelogram": 4,
    "quadrilateral": 4,
    "bisects": 2,
    "cut_ratio": 2,
    "x": 1,
    "y": 1,
    "axis": 1,
    "vertex": 1,
}
POINT_ARGS = {
    "length",
    "angle",
    "triangle",
    "segment",
    "line",
    "ray",
    "midpoint",
    "square",
    "parallelogram",
    "quadrilateral",
    "fixed",
    "moving",
}
ENDPOINT_PAIR_ARGS = {"bisects", "cut_ratio"}


def endpoint_arguments(arg):
    """Typed endpoint syntax; never guess the meaning of bare AB elsewhere."""
    if arg[0] == "name" and re.fullmatch("[A-Z]{2}", arg[1]):
        return [node("name", p) for p in arg[1]]
    if arg[0] == "call" and arg[1] in ("line", "segment") and len(arg) == 4:
        return arg[2:]
    raise NotationError("binding.endpoint_pair")


def point_intersection_pair(ast):
    """Recognize a named-point shorthand, never coerce a general point set."""
    if ast[0] == "=":
        for point, locus in ((ast[1], ast[2]), (ast[2], ast[1])):
            if point[0] == "name" and locus[0] == "∩":
                return point, locus
    return None


@dataclass
class Report:
    issues: list = dc_field(default_factory=list)
    semantic: dict = dc_field(default_factory=dict)
    normalized: dict = dc_field(default_factory=dict)
    units: dict = dc_field(default_factory=dict)
    well_definedness_obligations: list = dc_field(default_factory=list)
    defaults: list = dc_field(default_factory=list)
    objects: list = dc_field(default_factory=list)
    semantic_normalization: dict = dc_field(default_factory=dict)
    source_locations: dict = dc_field(default_factory=dict)

    def record_intersections(self, ast, path, source):
        if ast[0] == "point_intersection_definition":
            self.source_locations[encoded(ast).decode()] = {
                "path": path,
                "source": source,
            }
        for child in children(ast):
            self.record_intersections(child, path, source)

    @property
    def ok(self):
        return not self.issues

    def payload(self):
        return {
            "ok": self.ok,
            "issues": self.issues,
            "defaults": self.defaults,
            "objects": self.objects,
            "well_definedness_obligations": self.well_definedness_obligations,
            "coordinate_bindings": self.semantic_normalization.get(
                "coordinate_bindings", []
            ),
            "normalization_proofs": self.semantic_normalization.get("proofs", []),
        }


def children(ast):
    return [x for x in ast[1:] if isinstance(x, list) and x and isinstance(x[0], str)]


def normalize(payload):
    value = deepcopy(payload)
    count = 0

    def visit(scope, depth):
        nonlocal count
        count += 1
        if depth > 12 or count > 128:
            raise NotationError("notation.scope_limit")
        scope.setdefault("label", "题目")
        for key in ("definitions", "facts", "goals", "children", "uncertainties"):
            scope.setdefault(key, [])
        for child in scope["children"]:
            visit(child, depth + 1)

    visit(value["root"], 0)
    return value


class Scope:
    def __init__(self, report, path, parent=None):
        self.report, self.path, self.parent = report, path, parent
        self.local = {}
        self.functions = dict(parent.functions) if parent else {}

    def lookup(self, name):
        if name in self.local:
            return self.local[name]
        return self.parent.lookup(name) if self.parent else None

    def declare(self, name, kind, *, local=False):
        if name in ("x_axis", "y_axis") or name in BUILTINS:
            raise NotationError("binding.reserved_name:" + name)
        existing = self.local.get(name) if local else self.lookup(name)
        if existing:
            if existing["kind"] != kind:
                raise NotationError("binding.type_conflict:" + name)
            return existing
        identity = f"{self.path}:{kind}:{name}"
        value = {"ref": identity, "name": name, "kind": kind, "scope": self.path}
        self.local[name] = value
        self.report.objects.append(value)
        if kind == "scalar":
            self.report.defaults.append(
                {"ref": identity, "domain": "real", "origin": "code_default"}
            )
        return value

    def reference(self, name, kind=None, *, introduce=False):
        value = self.lookup(name)
        if value is None and introduce:
            value = self.declare(name, kind or "scalar")
        if value is None:
            raise NotationError("binding.unknown_or_invisible:" + name)
        if kind and value["kind"] != kind:
            raise NotationError("binding.type_conflict:" + name)
        return node("ref", value["ref"], value["kind"])

    def declarations(self, ast):
        kind = ast[0]
        intersection = point_intersection_pair(ast)
        if intersection:
            self.declare(intersection[0][1], "point")
        if kind in ("curve_definition", "function_definition"):
            self.declare(
                ast[1],
                "curve" if kind == "curve_definition" else "function",
                local=True,
            )
            if kind == "function_definition":
                self.functions[ast[1]] = ast
            return
        if kind == "role":
            self.declare(ast[1], "point")
            return
        if kind == "=":
            left, right = ast[1:]
            if left[0] == "name" and (
                right[0] == "tuple"
                or (right[0] == "call" and right[1] in ("midpoint", "vertex"))
                or (right[0] == "+" and right[2][0] == "tuple")
            ):
                self.declare(left[1], "point")
            for side in (left, right):
                if side[0] == "set":
                    for p in side[1:]:
                        if p[0] == "name":
                            self.declare(p[1], "point")
        if kind == "∈" and ast[1][0] == "name":
            if ast[2][0] == "real" or ast[2][0] in ("interval", "tuple"):
                self.declare(ast[1][1], "scalar")
            else:
                self.declare(ast[1][1], "point")
        # Operator signatures establish point identity, not geometric facts.
        # Existing visible objects are reused; siblings are never searched.
        if kind == "call":
            points = ast[2:] if ast[1] in POINT_ARGS else []
            # A packed angle is a reference to existing points, never a
            # declaration of a new three-letter point or guessed endpoints.
            if ast[1] == "angle" and len(ast) == 3:
                points = []
            if ast[1] in ENDPOINT_PAIR_ARGS:
                points = [p for arg in ast[2:] for p in endpoint_arguments(arg)]
            for point in points:
                if point[0] == "name":
                    self.declare(point[1], "point")
        for child in children(ast):
            self.declarations(child)

    def bind(self, ast, bound=None, depth=0):
        bound = bound or {}
        if depth > 40:
            raise NotationError("binding.depth_limit")
        kind = ast[0]
        bind = lambda a: self.bind(a, bound, depth + 1)
        intersection = point_intersection_pair(ast)
        if intersection:
            # A distinct internal node retains the stronger "the intersection"
            # meaning until normalization proves existence and uniqueness.
            return node(
                "point_intersection_definition", *[bind(p) for p in intersection]
            )
        if kind in ("number", "real", "definition_prose"):
            return ast
        if kind == "name":
            name = ast[1]
            if name in bound:
                return node("bound", bound[name])
            if name in ("x_axis", "y_axis"):
                return node("axis_constant", name)
            if self.lookup(name):
                return self.reference(name)
            if re.fullmatch("[A-Z]{2}", name):
                return node(
                    "call", "length", *[self.reference(p, "point") for p in name]
                )
            if name[0].islower() and name not in BUILTINS:
                return self.reference(name, "scalar", introduce=True)
            raise NotationError("binding.unknown_or_invisible:" + name)
        if kind == "role":
            return node("role", self.reference(ast[1], "point"), ast[2])
        if kind == "curve_definition":
            return node(
                kind,
                self.reference(ast[1], "curve"),
                self.bind(ast[2], {"x": "coordinate_x"}, depth + 1),
            )
        if kind == "function_definition":
            return node(
                kind,
                self.reference(ast[1], "function"),
                self.bind(ast[3], {ast[2]: "function_argument"}, depth + 1),
            )
        if kind == "quantifier":
            domain = bind(ast[3])
            if domain[0] == "tuple":
                domain = node("interval", False, False, *domain[1:])
            if domain[0] not in ("real", "interval"):
                raise NotationError("binding.quantifier_domain")
            variable = f"quantified_{len(bound)}"
            return node(
                kind,
                ast[1],
                variable,
                domain,
                self.bind(ast[4], {**bound, ast[2]: variable}, depth + 1),
            )
        if kind == "extremum":
            body = bind(ast[3])
            hints = [self.reference(x) for x in ast[2]]
            return node(kind, ast[1], hints, body)
        if kind == "call":
            name, args = ast[1], ast[2:]
            if (
                name == "angle"
                and len(args) == 1
                and args[0][0] == "name"
                and re.fullmatch("[A-Z]{3}", args[0][1])
            ):
                packed = args[0][1]
                if (
                    self.lookup(packed)
                    or packed in bound
                    or any(p in bound for p in packed)
                ):
                    raise NotationError("binding.ambiguous_angle_shorthand:" + packed)
                return node(
                    "call", "angle", *[self.reference(p, "point") for p in packed]
                )
            if name not in ARITY and name not in ("fixed", "moving"):
                if name not in self.functions or len(args) != 1:
                    raise NotationError("binding.unknown_function:" + name)
                return node(
                    "function_call", self.reference(name, "function"), bind(args[0])
                )
            if name in ARITY and len(args) != ARITY[name]:
                raise NotationError("binding.call_arity:" + name)
            if name in ENDPOINT_PAIR_ARGS:
                pairs = [
                    node("endpoints", *[bind(p) for p in endpoint_arguments(arg)])
                    for arg in args
                ]
                self.report.well_definedness_obligations.append(
                    {
                        "scope": self.path,
                        "code": "unique_line_intersection",
                        "objects": pairs,
                    }
                )
                if name == "cut_ratio":
                    self.report.well_definedness_obligations.append(
                        {
                            "scope": self.path,
                            "code": "nonzero_cut_denominator",
                            "objects": pairs,
                        }
                    )
                return node("call", name, *pairs)
            return node("call", name, *[bind(p) for p in args])
        if kind == "∈" and ast[2][0] == "real":
            return node("default_domain", bind(ast[1]), "real")
        if kind == "interval":
            return node(kind, ast[1], ast[2], bind(ast[3]), bind(ast[4]))
        return node(kind, *[bind(p) for p in ast[1:]])


def typecheck(ast):
    kind = ast[0]
    if kind == "point_intersection_definition":
        if (
            typecheck(ast[1]) != "point"
            or ast[2][0] != "∩"
            or typecheck(ast[2]) != "locus"
        ):
            raise NotationError("type.point_intersection_definition")
        return "boolean"
    if kind in ("number", "bound"):
        return "scalar"
    if kind == "ref":
        return ast[2]
    if kind in ("real", "interval"):
        if kind == "interval" and any(typecheck(x) != "scalar" for x in ast[3:]):
            raise NotationError("type.interval_endpoint")
        return "domain"
    if kind == "axis_constant":
        return "locus"
    if kind == "certified_cut_ratio":
        if any(typecheck(arg) != "endpoints" for arg in ast[1:]):
            raise NotationError("type.certified_cut_ratio")
        return "scalar"
    if kind == "object_declaration":
        if ast[1][:2] != ["call", "segment"] or typecheck(ast[1]) != "locus":
            raise NotationError("type.object_declaration")
        return "boolean"
    if kind == "default_domain":
        if typecheck(ast[1]) != "scalar":
            raise NotationError("type.scalar_domain")
        return "boolean"
    if kind in ("definition_prose", "role"):
        return "boolean"
    if kind in ("curve_definition", "function_definition"):
        if typecheck(ast[2]) != "scalar":
            raise NotationError("type.function_body")
        return "boolean"
    if kind == "function_call":
        if typecheck(ast[2]) != "scalar":
            raise NotationError("type.function_argument")
        return "scalar"
    if kind == "quantifier":
        if typecheck(ast[3]) != "domain" or typecheck(ast[4]) != "boolean":
            raise NotationError("type.quantifier")
        return "boolean"
    if kind == "extremum":
        typ = typecheck(ast[3])
        if typ not in ("scalar", "length", "angle", "area"):
            raise NotationError("type.extremum")
        return typ
    if kind in ("set", "endpoints"):
        if any(typecheck(x) != "point" for x in ast[1:]):
            raise NotationError("type.point_collection")
        return "point_set" if kind == "set" else "endpoints"
    if kind == "tuple":
        if len(ast) != 3 or any(typecheck(x) != "scalar" for x in ast[1:]):
            raise NotationError("type.coordinates")
        return "coordinates"
    if kind == "degrees":
        if typecheck(ast[1]) != "scalar":
            raise NotationError("type.degrees")
        return "angle"
    if kind == "call":
        name = ast[1]
        types = [typecheck(x) for x in ast[2:]]
        if name in POINT_ARGS:
            if not types or any(t != "point" for t in types):
                raise NotationError("type.point_arguments:" + name)
            return {
                "length": "length",
                "angle": "angle",
                "triangle": "triangle",
                "midpoint": "point",
                "line": "locus",
                "ray": "locus",
                "segment": "locus",
            }.get(name, "boolean")
        required = {
            "axis": "curve",
            "vertex": "curve",
            "x": "point",
            "y": "point",
            "area": "triangle",
            "sqrt": "scalar",
            "tan": "angle",
            "bisects": "endpoints",
            "cut_ratio": "endpoints",
        }[name]
        if any(t != required for t in types):
            raise NotationError("type.call_arguments:" + name)
        return {
            "axis": "locus",
            "vertex": "point",
            "area": "area",
            "bisects": "boolean",
        }.get(name, "scalar")
    if kind in ("and", "or"):
        if any(typecheck(x) != "boolean" for x in ast[1:]):
            raise NotationError("type.logic")
        return "boolean"
    if kind == "∩":
        if any(typecheck(x) not in ("locus", "curve") for x in ast[1:]):
            raise NotationError("type.intersection")
        return "locus"
    if kind == "∈":
        a, b = map(typecheck, ast[1:])
        if (a, b) not in (("point", "locus"), ("point", "curve"), ("scalar", "domain")):
            raise NotationError("type.membership")
        return "boolean"
    if kind == "neg":
        typ = typecheck(ast[1])
        if typ not in ("scalar", "length", "angle", "area"):
            raise NotationError("type.negation")
        return typ
    if kind in ("⟂", "∥"):
        if any(typecheck(x) != "locus" for x in ast[1:]):
            raise NotationError("type.line_relation")
        return "boolean"
    a, b = map(typecheck, ast[1:])
    if kind in ("=", "!=", "<", "<=", ">", ">="):
        compatible = (
            a == b
            or {a, b} <= {"scalar", "length", "angle", "area"}
            or {a, b} == {"point", "coordinates"}
            or {a, b} == {"locus", "point_set"}
        )
        if not compatible or (
            kind not in ("=", "!=") and a in ("point", "locus", "curve", "point_set")
        ):
            raise NotationError("type.relation")
        return "boolean"
    if kind == "+" and (a, b) in (("point", "coordinates"), ("coordinates", "point")):
        return "point"
    if a not in ("scalar", "length", "angle", "area") or b not in (
        "scalar",
        "length",
        "angle",
        "area",
    ):
        raise NotationError("type.arithmetic")
    if kind in ("+", "-"):
        if a != b and "scalar" not in (a, b):
            raise NotationError("type.dimension")
        return b if a == "scalar" else a
    if kind == "/" and a == b:
        return "scalar"
    if kind == "*" and a == b == "length":
        return "area"
    return a if b == "scalar" else b


class NotationValidator:
    def validate(self, payload):
        report = Report()
        try:
            errors = list(Draft202012Validator(schema()).iter_errors(payload))
            if errors:
                report.issues = [
                    {
                        "path": "/" + "/".join(map(str, e.absolute_path)),
                        "code": "schema.invalid",
                        "message": e.message,
                    }
                    for e in errors[:32]
                ]
                return report
            report.normalized = normalize(payload)
            report.semantic = self.scope(report.normalized["root"], report, "r")
            if report.ok:
                from .notation_normalization import normalize_bound

                report.semantic_normalization = normalize_bound(
                    report.semantic,
                    report.objects,
                    source_locations=report.source_locations,
                )
        except (NotationError, RecursionError, ValueError, TypeError) as exc:
            report.issues.append(
                {
                    "path": getattr(exc, "path", None) or "/root",
                    "code": "notation.invalid",
                    "message": str(exc),
                    **(
                        {"source": exc.source}
                        if getattr(exc, "source", None) is not None
                        else {}
                    ),
                }
            )
        return report

    def scope(self, source, report, path, parent=None):
        env = Scope(report, path, parent)
        expressions = []
        for field in ("definitions", "facts"):
            for index, text in enumerate(source[field]):
                location = f"{path}.{field}[{index}]"
                try:
                    # Both collections use the same math-object recognition.
                    # Keep the original field/path for audit, not for typing.
                    ast = definition(text, known_functions=env.functions)
                    expressions.append((ast, location, text))
                    env.declarations(ast)
                    report.units[location] = {
                        "scope": path,
                        "collection": field,
                        "index": index,
                    }
                except (NotationError, RecursionError) as exc:
                    report.issues.append(
                        {
                            "path": location,
                            "source": text,
                            "code": "notation.parse",
                            "message": str(exc),
                        }
                    )
        compiled = []
        for ast, location, text in expressions:
            try:
                value = env.bind(ast)
                value_type = typecheck(value)
                if value[:2] == ["call", "segment"] and value_type == "locus":
                    # A standalone segment is an object mention (e.g. connect
                    # B,C), not an additional relation. Keep the typed original
                    # for audit; the comparison projection removes it.
                    value = node("object_declaration", value)
                elif value_type != "boolean":
                    raise NotationError("type.fact_must_be_relation")
                compiled.append(value)
                report.record_intersections(value, location, text)
            except (NotationError, RecursionError) as exc:
                report.issues.append(
                    {
                        "path": location,
                        "source": text,
                        "code": "notation.bind",
                        "message": str(exc),
                    }
                )
        goals = []
        for index, goal in enumerate(source["goals"]):
            try:
                target = next(
                    k for k in ("expression", "object", "symbol") if k in goal
                )
                value = env.bind(parse(goal[target]))
                typ = typecheck(value)
                expected = {
                    "find_coordinates": ("point",),
                    "find_equation": ("curve", "function"),
                    "find_range": ("scalar",),
                }.get(goal["kind"], ("scalar", "length", "angle", "area"))
                if typ not in expected:
                    raise NotationError("type.goal_target")
                result = {"kind": goal["kind"], "target": value}
                if "at" in goal:
                    result["at"] = env.bind(parse(goal["at"]))
                    if typecheck(result["at"]) != "boolean":
                        raise NotationError("type.goal_at")
                    report.record_intersections(
                        result["at"], f"{path}.goals[{index}]", goal
                    )
                for field in ("variables", "in_terms_of"):
                    if field in goal:
                        result[field] = [env.reference(p) for p in goal[field]]
                goals.append(result)
            except (NotationError, RecursionError) as exc:
                report.issues.append(
                    {
                        "path": f"{path}.goals[{index}]",
                        "source": goal,
                        "code": "notation.goal",
                        "message": str(exc),
                    }
                )
        result = {
            "scope": path,
            "facts": compiled,
            "goals": goals,
            "uncertainties": source["uncertainties"],
            "children": [],
        }
        for i, child in enumerate(source["children"]):
            result["children"].append(self.scope(child, report, f"{path}.c{i}", env))
        return result
