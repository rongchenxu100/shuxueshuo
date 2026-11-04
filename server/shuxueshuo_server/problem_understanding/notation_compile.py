"""Lexical binding and typed validation of the small mathematical language."""

import re
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dc_field

from jsonschema import Draft202012Validator

from .answer_requests import validate_goal_request
from .identity import encoded
from .normalization_report import from_normalization
from .notation_contract import schema
from .notation_parser import (
    BUILTINS,
    SUBSET_RELATIONS,
    NotationError,
    definition,
    node,
    parse,
)

ARITY = {
    "Dom": 1,
    "sqrt": 1,
    "abs": 1,
    "sum": 1,
    "mod": 2,
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
SET_OPERATIONS = {"∩", "∪"}


def value_set(ast):
    """A literal of numbers or scalar symbols such as {a,1}; {A,B} names points."""
    return ast[0] in ("empty_set", "set_builder") or (
        ast[0] == "set"
        and not all(p[0] == "name" and p[1][:1].isupper() for p in ast[1:])
    )


def set_operand_names(ast):
    """Capitalized names standing as sets: the name itself or operands of ∩ / ∪."""
    if ast[0] == "name" and ast[1][:1].isupper():
        return [ast[1]]
    if ast[0] in SET_OPERATIONS:
        return [name for side in ast[1:3] for name in set_operand_names(side)]
    return []


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
    normalization_report: dict = dc_field(default_factory=dict)
    source_locations: dict = dc_field(default_factory=dict)
    # Per-scope bound facts in source order. Unlike source_locations, equal
    # bound ASTs in sibling scopes keep separate entries.
    scope_facts: dict = dc_field(default_factory=dict)
    # Proven redundant target names are audit records, never additional facts.
    abstract_target_aliases: dict = dc_field(default_factory=dict)

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
            "object_bindings": self.semantic_normalization.get("object_bindings", []),
            "normalization_proofs": self.semantic_normalization.get("proofs", []),
            "normalization_report": self.normalization_report,
            **({"abstract_target_aliases": self.abstract_target_aliases}
               if self.abstract_target_aliases else {}),
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


def _expression_texts(scope):
    for field in ("definitions", "facts"):
        for text in scope.get(field, ()):
            if isinstance(text, str):
                yield text
    for goal in scope.get("goals", ()):
        if not isinstance(goal, dict):
            continue
        for key in ("expression", "object", "symbol"):
            value = goal.get(key)
            if isinstance(value, str):
                yield value
    for child in scope.get("children", ()):
        yield from _expression_texts(child)


def _expression_ast(text):
    try:
        return definition(text)
    except (NotationError, RecursionError):
        try:
            return parse(text)
        except (NotationError, RecursionError):
            return None


def _is_zero_number(ast):
    return ast == ["number", "0"] or ast == ["number", "0.0"]


def _is_origin_tuple(ast):
    return (
        isinstance(ast, list)
        and ast
        and ast[0] == "tuple"
        and len(ast) == 3
        and _is_zero_number(ast[1])
        and _is_zero_number(ast[2])
    )


def _is_axes_constant(ast):
    return (
        isinstance(ast, list)
        and len(ast) == 2
        and ast[0] in ("name", "axis_constant")
        and ast[1] in ("x_axis", "y_axis")
    )


def _is_axes_intersection(ast):
    if not (isinstance(ast, list) and ast and ast[0] == "∩" and len(ast) == 3):
        return False
    return {_axes_name(ast[1]), _axes_name(ast[2])} == {"x_axis", "y_axis"}


def _axes_name(ast):
    if _is_axes_constant(ast):
        return ast[1]
    return None


def _mentions_point_letter(ast, letter):
    if not isinstance(ast, list) or not ast:
        return False
    if ast[0] == "name":
        name = ast[1]
        if name == letter:
            return True
        if (
            isinstance(name, str)
            and re.fullmatch(r"[A-Z]{2,}", name)
            and letter in name
        ):
            return True
    return any(_mentions_point_letter(child, letter) for child in children(ast))


def _coordinate_frame_signal(ast):
    if not isinstance(ast, list) or not ast:
        return False
    kind = ast[0]
    if kind == "curve_definition":
        return True
    if (
        kind in ("name", "axis_constant")
        and len(ast) == 2
        and ast[1]
        in (
            "x_axis",
            "y_axis",
        )
    ):
        return True
    if kind == "call" and len(ast) >= 2 and ast[1] in ("x", "y"):
        return True
    if kind == "tuple" and len(ast) == 3:
        return True
    return any(_coordinate_frame_signal(child) for child in children(ast))


def _o_definition_kind(ast):
    """Classify an expression's effect on point O: origin, conflict, or None."""
    if not isinstance(ast, list) or not ast:
        return None
    kind = ast[0]
    if kind == "=" and len(ast) == 3:
        for point, value in ((ast[1], ast[2]), (ast[2], ast[1])):
            if not isinstance(point, list) or not isinstance(value, list) or not value:
                continue
            if point == ["name", "O"]:
                if _is_origin_tuple(value) or _is_axes_intersection(value):
                    return "origin"
                if value[0] in ("tuple", "call", "+", "∩", "set"):
                    return "conflict"
            if point[0] == "set" and any(p == ["name", "O"] for p in point[1:]):
                if _is_axes_intersection(value):
                    return "origin"
                if value[0] in ("∩", "set"):
                    return "conflict"
    if kind == "∈" and len(ast) == 3 and ast[1] == ["name", "O"]:
        locus = ast[2]
        if _is_axes_constant(locus) or _is_axes_intersection(locus):
            return None
        return "conflict"
    if kind == "role" and len(ast) >= 3 and ast[1] == "O" and ast[2] == "moving":
        return "conflict"
    for child in children(ast):
        status = _o_definition_kind(child)
        if status:
            return status
    return None


def coordinate_origin_default(root):
    """Whether root should receive the code default O=(0,0).

    Matches problem-math-notation-review: coordinate frame + referenced O + no
    conflicting definition. Explicit root O=(0,0) is left to the candidate.
    """
    has_frame = False
    mentions_o = False
    conflict = False
    root_has_origin = False
    for text in root.get("definitions", ()) + root.get("facts", ()):
        if not isinstance(text, str):
            continue
        ast = _expression_ast(text)
        if ast is None:
            continue
        if _o_definition_kind(ast) == "origin":
            root_has_origin = True
    for text in _expression_texts(root):
        ast = _expression_ast(text)
        if ast is None:
            if "x_axis" in text or "y_axis" in text:
                has_frame = True
            continue
        has_frame = has_frame or _coordinate_frame_signal(ast)
        mentions_o = mentions_o or _mentions_point_letter(ast, "O")
        status = _o_definition_kind(ast)
        if status == "conflict":
            conflict = True
    return has_frame and mentions_o and not conflict and not root_has_origin


class Scope:
    def __init__(self, report, path, parent=None):
        self.report, self.path, self.parent = report, path, parent
        self.local = {}
        self.functions = dict(parent.functions) if parent else {}
        self.abstract_functions = set(parent.abstract_functions) if parent else set()

    def lookup(self, name):
        if name in self.local:
            return self.local[name]
        return self.parent.lookup(name) if self.parent else None

    def declare(self, name, kind, *, local=False):
        if name in ("x_axis", "y_axis") or (
            name in BUILTINS and name not in ("x", "y")
        ):
            raise NotationError("binding.reserved_name", name)
        existing = self.local.get(name) if local else self.lookup(name)
        if existing:
            if existing["kind"] != kind:
                raise NotationError("binding.type_conflict", name)
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
            raise NotationError("binding.unknown_or_invisible", name)
        if kind and value["kind"] != kind:
            raise NotationError("binding.type_conflict", name)
        return node("ref", value["ref"], value["kind"])

    def set_like(self, ast):
        if ast[0] == "set_difference":
            return True
        if value_set(ast):
            return True
        if ast[0] == "name":
            found = self.lookup(ast[1])
            return bool(found) and found["kind"] == "set"
        return ast[0] in SET_OPERATIONS and any(self.set_like(p) for p in ast[1:])

    def set_declarations(self, ast):
        """A capitalized name related to a finite set by ⊆, =, ∩ or ∪ is a set,
        including operands nested in ∩ and ∪ (A ∪ B = {1,2,3} makes A and B sets)."""
        kind = ast[0]
        if kind in SUBSET_RELATIONS or (
            kind in ("=", "!=", *SET_OPERATIONS)
            and any(self.set_like(side) for side in ast[1:3])
        ):
            for side in ast[1:3]:
                for name in set_operand_names(side):
                    self.declare(name, "set")
        if (ast[:2] == ["call", "sum"] and len(ast) == 3
                and ast[2][0] == "name" and ast[2][1][:1].isupper()):
            self.declare(ast[2][1], "set")
        for child in children(ast):
            self.set_declarations(child)

    def declarations(self, ast):
        kind = ast[0]
        intersection = point_intersection_pair(ast)
        if intersection:
            self.declare(intersection[0][1], "point")
        if kind in ("curve_definition", "function_definition", "function_input_relation"):
            self.declare(
                ast[1],
                "curve" if kind == "curve_definition" else "function",
                local=True,
            )
            if kind in ("function_definition", "function_input_relation"):
                self.functions[ast[1]] = ast
            return
        if kind == "role":
            self.declare(ast[1], "point")
            return
        if kind == "=":
            left, right = ast[1:]
            for name, value in ((left, right), (right, left)):
                if name[0] == "name" and (
                    value[0] == "tuple"
                    or (value[0] == "call" and value[1] in ("midpoint", "vertex"))
                    or (value[0] == "+" and value[2][0] == "tuple")
                ):
                    self.declare(name[1], "point")
            for side in (left, right):
                if side[0] == "set" and not value_set(side):
                    for p in side[1:]:
                        if p[0] == "name":
                            self.declare(p[1], "point")
        if kind in ("∈", "∉") and ast[1][0] == "name":
            if (
                ast[2][0] == "real"
                or ast[2][0] in ("interval", "tuple")
                or self.set_like(ast[2])
            ):
                self.declare(ast[1][1], "scalar")
            elif kind == "∈":
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
        if kind in ("number", "real", "infinity", "definition_prose", "empty_set"):
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
            if name in ("x", "y"):
                return self.reference(name, "scalar", introduce=True)
            raise NotationError("binding.unknown_or_invisible", name)
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
        if kind == 'function_input_relation':
            return node(kind, self.reference(ast[1], 'function'),
                        self.bind(ast[3], {ast[2]: 'function_argument'}, depth + 1),
                        self.bind(ast[4], {ast[2]: 'function_argument'}, depth + 1))
        if kind == '=' and any(side[:2] == ['call', 'Dom'] for side in ast[1:]):
            sides = [bind(side) for side in ast[1:]]
            sides = [node('interval', False, False, *side[1:]) if side[0] == 'tuple' else side
                     for side in sides]
            return node('=', *sides)
        if kind in ("quantifier", "set_builder"):
            *head, name, domain, body = ast[1:]
            domain = bind(domain)
            if domain[0] == "tuple":
                domain = node("interval", False, False, *domain[1:])
            if domain[0] not in ("real", "interval"):
                raise NotationError("binding.quantifier_domain")
            variable = f"quantified_{len(bound)}"
            return node(
                kind,
                *head,
                variable,
                domain,
                self.bind(body, {**bound, name: variable}, depth + 1),
            )
        if kind == "extremum":
            body = bind(ast[3])
            hints = [self.reference(x) for x in ast[2]]
            return node(kind, ast[1], hints, body)
        if kind == "call":
            name, args = ast[1], ast[2:]
            if name == 'piecewise':
                if len(args) not in (4, 6, 8):
                    raise NotationError('binding.call_arity', name)
                return node('call', name, *[bind(p) for p in args])
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
                    raise NotationError("binding.ambiguous_angle_shorthand", packed)
                return node(
                    "call", "angle", *[self.reference(p, "point") for p in packed]
                )
            if name not in ARITY and name not in ("fixed", "moving"):
                if (name not in self.functions and name not in self.abstract_functions) or len(args) != 1:
                    raise NotationError("binding.unknown_function", name)
                return node(
                    "function_call", self.reference(name, "function"), bind(args[0])
                )
            if name in ARITY and len(args) != ARITY[name]:
                raise NotationError("binding.call_arity", name)
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
        if kind == "∈" and ast[2][0] == "tuple":
            return node(
                "∈",
                bind(ast[1]),
                node("interval", False, False, *[bind(x) for x in ast[2][1:]]),
            )
        if kind == "interval":
            return node(kind, ast[1], ast[2], bind(ast[3]), bind(ast[4]))
        if kind == "set_difference":
            base = bind(ast[1])
            if base[0] == "tuple":
                base = node("interval", False, False, *base[1:])
            return node(kind, base, bind(ast[2]))
        if kind in SET_OPERATIONS:
            parts = [bind(part) for part in ast[1:]]
            return node(kind, *[node("interval", False, False, *part[1:])
                                if part[0] == "tuple" else part for part in parts])
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
    if kind == "infinity":
        return "infinite_endpoint"
    if kind == "ref":
        return ast[2]
    if kind in ("real", "interval"):
        if kind == "interval":
            if len(ast) != 5:
                raise NotationError("type.interval_endpoint")
            for index, endpoint in enumerate(ast[3:]):
                if endpoint[0] == "infinity":
                    if ast[index + 1]:
                        raise NotationError("type.closed_infinite_endpoint")
                    if endpoint[1] != (-1 if index == 0 else 1):
                        raise NotationError("type.infinite_endpoint_direction")
                elif typecheck(endpoint) != "scalar":
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
    if kind == 'function_input_relation':
        if typecheck(ast[2]) != 'scalar' or typecheck(ast[3]) != 'scalar':
            raise NotationError('type.function_relation')
        return 'boolean'
    if kind == "function_call":
        if typecheck(ast[2]) != "scalar":
            raise NotationError("type.function_argument")
        return "scalar"
    if kind == "quantifier":
        if typecheck(ast[3]) != "domain" or typecheck(ast[4]) != "boolean":
            raise NotationError("type.quantifier")
        return "boolean"
    if kind == "set_builder":
        if typecheck(ast[2]) != "domain" or typecheck(ast[3]) != "boolean":
            raise NotationError("type.set_builder")
        return "set"
    if kind == "extremum":
        typ = typecheck(ast[3])
        if typ not in ("scalar", "length", "angle", "area"):
            raise NotationError("type.extremum")
        return typ
    if kind == "empty_set":
        return "set"
    if kind == "set":
        types = [typecheck(x) for x in ast[1:]]
        if all(t == "point" for t in types):
            return "point_set"
        if all(t == "scalar" for t in types):
            return "set"
        raise NotationError("type.point_collection")
    if kind == "endpoints":
        if any(typecheck(x) != "point" for x in ast[1:]):
            raise NotationError("type.point_collection")
        return "endpoints"
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
        if name == 'piecewise':
            if len(types) not in (4, 6, 8) or types != ['scalar', 'boolean'] * (len(types) // 2):
                raise NotationError('type.piecewise_branches')
            return 'scalar'
        if name in POINT_ARGS:
            if not types or any(t != "point" for t in types):
                raise NotationError("type.point_arguments", name)
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
            "Dom": "function",
            "axis": "curve",
            "vertex": "curve",
            "x": "point",
            "y": "point",
            "area": "triangle",
            "sqrt": "scalar",
            "abs": "scalar",
            "sum": "set",
            "mod": "scalar",
            "tan": "angle",
            "bisects": "endpoints",
            "cut_ratio": "endpoints",
        }[name]
        if any(t != required for t in types):
            raise NotationError("type.call_arguments", name)
        return {
            "Dom": "domain",
            "axis": "locus",
            "vertex": "point",
            "area": "area",
            "bisects": "boolean",
        }.get(name, "scalar")
    if kind in ("and", "or"):
        if any(typecheck(x) != "boolean" for x in ast[1:]):
            raise NotationError("type.logic")
        return "boolean"
    if kind == "set_difference":
        if len(ast) != 3:
            raise NotationError("type.set_difference")
        left_type, right_type = typecheck(ast[1]), typecheck(ast[2])
        if left_type not in ("domain", "set") or right_type != "set":
            raise NotationError("type.set_difference")
        return "domain" if left_type == "domain" else "set"
    if kind in SET_OPERATIONS:
        types = [typecheck(x) for x in ast[1:]]
        if all(t == "set" for t in types):
            return "set"
        if all(t in ("domain", "set") for t in types):
            return "domain"
        if kind == "∪":
            raise NotationError("type.set_operation")
        if any(t not in ("locus", "curve") for t in types):
            raise NotationError("type.intersection")
        return "locus"
    if kind in ("∈", "∉"):
        a, b = map(typecheck, ast[1:])
        allowed = {("scalar", "set")}
        if kind == "∈":
            allowed |= {("point", "locus"), ("point", "curve"), ("scalar", "domain")}
        if (a, b) not in allowed:
            raise NotationError("type.membership")
        return "boolean"
    if kind in SUBSET_RELATIONS:
        if any(typecheck(x) != "set" for x in ast[1:]):
            raise NotationError("type.subset")
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
        if "infinite_endpoint" in (a, b):
            raise NotationError("type.infinity_outside_interval")
        compatible = (
            a == b
            or {a, b} <= {"scalar", "length", "angle", "area"}
            or {a, b} == {"point", "coordinates"}
            or {a, b} == {"locus", "point_set"}
            or {a, b} <= {"domain", "set"}
        )
        if not compatible or (
            kind not in ("=", "!=")
            and a in ("point", "locus", "curve", "point_set", "set")
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
        """Validate the original extraction envelope, including its family fields."""
        return self._validate(payload, schema())

    def validate_root(self, root, defs=None):
        """Compile a mathematical scope without an extraction-envelope contract.

        The mathematical compiler remains shared with validate; no synthetic
        family classification is inserted for newer callers. ``defs`` lets a
        newer contract (whose Scope may allow more goal kinds) check the scope
        against its own schema instead of the frozen v1 one.
        """
        root_schema = {
            "$defs": defs or schema()["$defs"],
            "type": "object",
            "required": ["root"],
            "additionalProperties": False,
            "properties": {"root": {"$ref": "#/$defs/Scope"}},
        }
        return self._validate({"root": root}, root_schema)

    def _validate(self, payload, contract):
        report = Report()
        try:
            errors = list(Draft202012Validator(contract).iter_errors(payload))
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
                report.normalization_report = from_normalization(
                    report.semantic,
                    report.semantic_normalization,
                    proofs=report.semantic_normalization.get("proofs", []),
                ).to_payload()
        except (NotationError, RecursionError, ValueError, TypeError) as exc:
            report.issues.append(
                {
                    "path": getattr(exc, "path", None) or "/root",
                    "code": "notation.invalid",
                    "reason_code": getattr(exc, "code", "internal.exception"),
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
        compiled = []
        if path == "r" and coordinate_origin_default(source):
            # Coordinate-frame default: visible root O=(0,0) before child scopes
            # bind references such as ∠ACO or OM. See problem-math-notation-review.
            origin = env.declare("O", "point")
            compiled.append(
                [
                    "=",
                    ["ref", origin["ref"], "point"],
                    ["tuple", ["number", "0"], ["number", "0"]],
                ]
            )
            report.defaults.append(
                {
                    "ref": origin["ref"],
                    "domain": "origin",
                    "origin": "code_default",
                }
            )
        # Set names first, so a ∈ M is typed by M even when it precedes {a} ⊆ M.
        # Repeat until nothing new is declared: A = B, B = C, C = {1,2} must not
        # depend on fact order. Each productive pass declares a name, so it ends.
        set_sources = [
            ast
            for field in ("definitions", "facts")
            for text in source[field]
            if isinstance(text, str) and (ast := _expression_ast(text)) is not None
        ]
        while True:
            known = len(report.objects)
            for ast in set_sources:
                try:
                    env.set_declarations(ast)
                except NotationError:
                    pass
            if len(report.objects) == known:
                break
        expressions = []
        from .notation_abstract_domain import target_naming_aliases

        target_aliases = target_naming_aliases(source, path, env)
        for field in ("definitions", "facts"):
            for index, text in enumerate(source[field]):
                location = f"{path}.{field}[{index}]"
                try:
                    if location in target_aliases:
                        report.abstract_target_aliases[location] = target_aliases[location]
                        report.units[location] = {
                            "scope": path, "collection": field, "index": index,
                        }
                        continue
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
                            "reason_code": getattr(exc, "code", "internal.exception"),
                            "message": str(exc),
                        }
                    )
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
                report.scope_facts.setdefault(path, []).append(
                    {"value": value, "path": location, "source": text}
                )
                # Keep the original LLM-facing expression attached to the
                # bound AST.  Normalization may derive internal facts from
                # this AST, but must be able to report the source JSON path
                # and source text without rewriting the candidate.
                report.source_locations[encoded(value).decode()] = {
                    "path": location,
                    "source": text,
                }
                report.record_intersections(value, location, text)
            except (NotationError, RecursionError) as exc:
                report.issues.append(
                    {
                        "path": location,
                        "source": text,
                        "code": "notation.bind",
                        "reason_code": getattr(exc, "code", "internal.exception"),
                        "message": str(exc),
                    }
                )
        goals = []
        for index, goal in enumerate(source["goals"]):
            try:
                validate_goal_request(goal)
                if 'pricing' in goal:
                    from .notation_piecewise_modeling import compile_pricing
                    goals.append(compile_pricing(goal, f'{path}.goals[{index}]'))
                    continue
                if goal['kind'] in ('find_monotonic_intervals', 'prove_monotonicity_on_interval'):
                    from .notation_function_graph import compile_function_graph
                    goals.append(compile_function_graph(goal, f'{path}.goals[{index}]'))
                    continue
                if goal['kind'] in ('select_function_graph', 'draw_function_graph', 'solve_graph_inequality'):
                    from .notation_function_graph import compile_function_graph
                    goals.append(compile_function_graph(goal, f'{path}.goals[{index}]'))
                    continue
                if goal['kind'] in ('select_range_domain', 'find_extrema_expression'):
                    from .notation_range_tasks import compile_range_task

                    goals.append(compile_range_task(goal, f'{path}.goals[{index}]', env))
                    continue
                if goal['kind'] == 'find_function_formula' or (goal['kind'] in ('find_value', 'find_range') and 'relation' in goal):
                    from .notation_function_formula import compile_function_formula

                    goals.append(compile_function_formula(goal, f'{path}.goals[{index}]'))
                    continue
                if goal['kind'] == 'find_translation_range':
                    from .notation_translation_range import compile_translation_range

                    goals.append(compile_translation_range(goal, f'{path}.goals[{index}]'))
                    continue
                if goal['kind'] == 'finite_sum':
                    from .notation_evaluation import compile_finite_sum

                    goals.append(compile_finite_sum(goal, f'{path}.goals[{index}]', env))
                    continue
                if goal['kind'] == 'match_range':
                    function = env.bind(parse(goal['object']))
                    parameter = env.bind(parse(goal['symbol']))
                    image = env.bind(parse(goal['range']))
                    if image[0] == 'tuple':
                        image = node('interval', False, False, *image[1:])
                    if typecheck(function) != 'function' or typecheck(parameter) != 'scalar' or typecheck(image) not in ('domain', 'set'):
                        raise NotationError('type.goal_match_range_fields')
                    goals.append({'kind': 'match_range', 'target': parameter, 'function': function, 'range': image})
                    continue
                if goal['kind'] == 'compare_functions':
                    from .notation_function_comparison import compile_comparison

                    goals.append(compile_comparison(goal, f'{path}.goals[{index}]'))
                    continue
                if goal['kind'] in ('find_abstract_domain', 'find_abstract_domain_parameter', 'find_abstract_range'):
                    from .notation_abstract_domain import compile_abstract_domain

                    goals.append(compile_abstract_domain(goal, f'{path}.goals[{index}]'))
                    continue
                target = next(
                    k for k in ("expression", "object", "symbol") if k in goal
                )
                value = env.bind(parse(goal[target]))
                typ = typecheck(value)
                expected = {
                    "find_coordinates": ("point",),
                    "find_equation": ("curve", "function"),
                    "find_range": ("function",) if target == "object" else ("scalar",),
                    "find_domain": ("function",),
                    "match_domain": ("function",),
                    "find_count": ("set",),
                }.get(goal["kind"], ("scalar", "length", "angle", "area"))
                if typ not in expected:
                    raise NotationError("type.goal_target")
                # match_domain binds the function via object; symbol is the
                # sought parameter and domain is the prescribed Dom(f).
                if goal["kind"] == "match_domain":
                    if target != "object" or "symbol" not in goal or "domain" not in goal:
                        raise NotationError("type.goal_match_domain_fields")
                    value = env.bind(parse(goal["object"]))
                    if typecheck(value) != "function":
                        raise NotationError("type.goal_target")
                    parameter = env.bind(parse(goal["symbol"]))
                    if typecheck(parameter) != "scalar":
                        raise NotationError("type.goal_parameter")
                    domain = env.bind(parse(goal["domain"]))
                    if domain[0] == "tuple":
                        domain = node("interval", False, False, *domain[1:])
                    if typecheck(domain) not in ("domain", "set"):
                        raise NotationError("type.goal_input_domain")
                    goals.append({
                        "kind": "match_domain",
                        "target": value,
                        "parameter": parameter,
                        "domain": domain,
                    })
                    continue
                result = {"kind": goal["kind"], "target": value}
                if 'answer_request' in goal:
                    result['answer_request'] = deepcopy(goal['answer_request'])
                if "input_domain" in goal:
                    domain = env.bind(parse(goal["input_domain"]))
                    if domain[0] == "tuple":
                        domain = node("interval", False, False, *domain[1:])
                    if typecheck(domain) not in ("domain", "set"):
                        raise NotationError("type.goal_input_domain")
                    result["input_domain"] = domain
                for field in ("variables", "in_terms_of"):
                    if field in goal:
                        result[field] = [env.reference(p) for p in goal[field]]
                goals.append(result)
            except (NotationError, RecursionError) as exc:
                report.issues.append(
                    {
                        "path": getattr(exc, 'path', None) or f"{path}.goals[{index}]",
                        "source": goal,
                        "code": "notation.goal",
                        "reason_code": getattr(exc, "code", "internal.exception"),
                        "message": str(exc),
                    }
                )
        from .notation_abstract_domain import validate_abstract_knowledge

        validate_abstract_knowledge(goals)
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
