"""Typed notation -> code-owned projection graph; no domain drafts or golden data.

The graph reuses the runtime projector's entity/relation vocabulary. Every
lowered unit retains its original JSON pointer and the premises of its rule.
It is deliberately not a VerifiedProblem, nor an accepted extraction context.
"""

from dataclasses import dataclass

import sympy as sp

from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemEntity,
    ProblemFact,
    ProblemGoal,
    ProblemGraph,
    ProblemScope,
    ProblemSource,
    ProblemUnitRecord,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash, thaw_json

from .notation_compile import NotationValidator
from .notation_normalization import conjuncts


class BindingError(ValueError):
    def __init__(self, code, path, message):
        self.code, self.path, self.message = code, path, message
        super().__init__(f"{code} at {path}: {message}")

    def payload(self):
        return {"code": self.code, "path": self.path, "message": self.message}


def refs(ast):
    if not isinstance(ast, list):
        return set()
    if ast and ast[0] == "ref":
        return {ast[1]}
    return set().union(*(refs(a) for a in ast))


def call(ast, name):
    return isinstance(ast, list) and ast[:2] == ["call", name]


def equality(ast, first, second):
    if ast[0] != "=":
        return None
    for a, b in ((ast[1], ast[2]), (ast[2], ast[1])):
        if first(a) and second(b):
            return a, b
    return None


@dataclass
class LoweredNotation:
    report: object
    graph: ProblemGraph
    units: dict
    provenance: dict
    motion_bindings: list


class NotationRuntimeLowerer:
    def lower(self, candidate, *, problem_id):
        self.report = NotationValidator().validate(candidate)
        if not self.report.ok:
            first = self.report.issues[0]
            raise BindingError(
                first["code"], first["path"], first.get("message", "invalid notation")
            )
        self.objects = {o["ref"]: o for o in self.report.objects}
        self.provenance, self.units, self.motion_bindings = {}, {}, []
        self.coordinate_conditions, self.covered_coordinates = [], set()
        root = self.scope(
            self.report.semantic, candidate["root"], ("problem",), "/root", []
        )
        for ast, source in self.coordinate_conditions:
            if stable_hash([source, ast]) not in self.covered_coordinates:
                raise BindingError(
                    "binding.unsupported_coordinate_condition",
                    source,
                    "coordinate condition has no executable binding",
                )
        graph = ProblemGraph(
            problem_id, candidate["family_id"], ProblemSource(""), root
        )
        for scope in root.iter_scopes():
            for kind, items in [
                ("scope", [scope]),
                ("entity", scope.entities),
                ("fact", scope.facts),
                ("goal", scope.goals),
            ]:
                for item in items:
                    self.provenance[item.unit_id]["scope_path"] = list(scope.path)
                    self.units[item.unit_id] = ProblemUnitRecord(
                        item.unit_id,
                        kind,
                        scope.path_id,
                        stable_hash(self.provenance[item.unit_id]),
                        getattr(item, "local_id", None),
                    )
        return LoweredNotation(
            self.report, graph, self.units, self.provenance, self.motion_bindings
        )

    def identity(self, path, rule, payload, premises=()):
        uid = "notation-unit:" + stable_hash([path, rule, payload])
        self.provenance[uid] = {
            "path": path,
            "rule": rule,
            "premises": sorted(set(premises)),
        }
        return uid

    def name(self, ast):
        if ast[0] != "ref":
            raise BindingError("binding.unsupported_object", self.pointer, str(ast))
        return self.objects[ast[1]]["name"]

    def algebra(self, ast):
        k = ast[0]
        if k == "number":
            return sp.Rational(ast[1])
        if k == "ref" and ast[2] == "scalar":
            return sp.Symbol(self.name(ast))
        if k == "bound" and ast[1] == "coordinate_x":
            return sp.Symbol("x")
        if k == "neg":
            return -self.algebra(ast[1])
        if k in ("+", "-", "*", "/", "^"):
            a, b = self.algebra(ast[1]), self.algebra(ast[2])
            return {
                "+": lambda: a + b,
                "-": lambda: a - b,
                "*": lambda: a * b,
                "/": lambda: a / b,
                "^": lambda: a**b,
            }[k]()
        if call(ast, "sqrt"):
            return sp.sqrt(self.algebra(ast[2]))
        raise BindingError("binding.unsupported_expression", self.pointer, str(ast))

    def text(self, ast):
        return sp.sstr(self.algebra(ast))

    def segment(self, ast):
        if not call(ast, "length"):
            raise BindingError("binding.expected_length", self.pointer, str(ast))
        return {"start": self.name(ast[2]), "end": self.name(ast[3])}

    def terms(self, ast):
        if ast[0] == "+":
            return self.terms(ast[1]) + self.terms(ast[2])
        if call(ast, "length"):
            return [{"scale": "1", "segment": self.segment(ast)}]
        if ast[0] == "*":
            for a, b in ((ast[1], ast[2]), (ast[2], ast[1])):
                if call(b, "length"):
                    scale = self.algebra(a)
                    if scale.is_positive is not True:
                        raise BindingError(
                            "binding.invalid_path_weight", self.pointer, str(scale)
                        )
                    return [{"scale": sp.sstr(scale), "segment": self.segment(b)}]
        raise BindingError("binding.unsupported_path", self.pointer, str(ast))

    def same_path(self, left, right):
        try:

            def signature(ast):
                terms = {}
                for item in self.terms(ast):
                    key = tuple(sorted(item["segment"].values()))
                    terms[key] = terms.get(key, 0) + sp.sympify(item["scale"])
                return terms

            return signature(left) == signature(right)
        except BindingError:
            return False

    def cover_coordinate(self, ast, source):
        self.covered_coordinates.add(stable_hash([source, ast]))

    def scope(self, tree, raw, path, pointer, inherited):
        self.pointer = pointer
        entries = []
        source_strings = [
            (f"{pointer}/{k}/{i}", text)
            for k in ("definitions", "facts")
            for i, text in enumerate(raw.get(k, []))
        ]
        if len(source_strings) != len(tree["facts"]):
            raise BindingError(
                "binding.source_alignment",
                pointer,
                "compiled facts differ from source units",
            )
        for ast, (source, text) in zip(tree["facts"], source_strings):
            for a in conjuncts([ast]):
                # Equivalent comparison direction must select the same branch.
                if a[0] == ">" and call(a[1], "x") and call(a[2], "x"):
                    a = ["<", a[2], a[1]]
                elif a[0] in (">", "<") and a[1] == ["number", "0"]:
                    a = [{">": "<", "<": ">"}[a[0]], a[2], a[1]]
                entries.append((a, source, text))
        visible = inherited + entries
        entities, facts, goals = [], [], []
        local_objects = [
            o for o in self.objects.values() if o["scope"] == tree["scope"]
        ]

        def entity(name, kind, source, rule="object_declaration", **attrs):
            uid = self.identity(source, rule, [kind, name, attrs])
            item = ProblemEntity(uid, name, kind, name, attrs)
            if not any(e.local_id == name for e in entities):
                entities.append(item)
            return name

        def fact(kind, source, rule="typed_relation", premises=(), **attrs):
            for existing in facts:
                if existing.kind == kind and thaw_json(existing.attributes) == attrs:
                    evidence = self.provenance[existing.unit_id]
                    evidence["premises"] = sorted(
                        set(evidence["premises"]) | {source} | set(premises)
                    )
                    return existing
            uid = self.identity(source, rule, [kind, attrs], premises)
            item = ProblemFact(uid, kind, attrs)
            if not any(f.unit_id == uid for f in facts):
                facts.append(item)
            return item

        def source_for(ref):
            return next((p for a, p, _ in entries if ref in refs(a)), pointer)

        curve_refs = {o["ref"] for o in self.objects.values() if o["kind"] == "curve"}
        coefficient_refs = set().union(
            *(refs(a[2]) for a, _, _ in visible if a[0] == "curve_definition")
        )
        # Only an independent coordinate parameter is dynamic. Coordinate aliases
        # on a curve never become optimization variables merely by being symbols.
        coordinate_aliases = set()
        alias_definitions = set()
        for a, _, _ in visible:
            pair = equality(
                a,
                lambda t: t[0] == "ref" and t[2] == "point",
                lambda t: t[0] == "tuple",
            )
            if (
                pair
                and pair[1][2][0] == "ref"
                and self.curve_membership(pair[0], visible)
            ):
                coordinate_aliases.add(pair[1][2][1])
                alias_definitions.add(stable_hash(a))
        for ast, source, _ in entries:
            if (
                refs(ast) & coordinate_aliases
                and stable_hash(ast) not in alias_definitions
                and ast[0] not in ("domain", "default_domain")
            ):
                raise BindingError(
                    "binding.coordinate_alias_constraint_unbound",
                    source,
                    "a coordinate alias needs an explicit binding before it can be independently constrained",
                )
        for o in local_objects:
            kind = {
                "point": "point",
                "scalar": "symbol",
                "curve": "quadratic_function",
            }.get(o["kind"])
            if not kind:
                raise BindingError(
                    "binding.unsupported_object", source_for(o["ref"]), o["kind"]
                )
            attrs = {}
            if kind == "symbol":
                attrs["role"] = (
                    "quadratic_coefficient"
                    if o["ref"] in coefficient_refs
                    else "coordinate_alias"
                    if o["ref"] in coordinate_aliases
                    else "dynamic_parameter"
                )
            entity(o["name"], kind, source_for(o["ref"]), **attrs)
        if any(a[0] == "curve_definition" for a, _, _ in entries):
            entity(
                "x",
                "symbol",
                next(p for a, p, _ in entries if a[0] == "curve_definition"),
                "curve_coordinate_variable",
                role="function_variable",
            )
        # Source assertions retain precise mathematics even when one expression
        # expands into several execution relations (intersection sets, states).
        for ast, source, text in entries:
            subjects = sorted({self.objects[r]["name"] for r in refs(ast)})
            fact("math_assertion", source, expression=text, subjects=subjects)
        for ast, source, _ in entries:
            self.pointer = source
            k = ast[0]
            if k == "curve_definition":
                polynomial = sp.Poly(self.algebra(ast[2]), sp.Symbol("x"))
                if polynomial.degree() != 2:
                    raise BindingError(
                        "binding.not_quadratic",
                        source,
                        "family requires a quadratic curve",
                    )
                fact(
                    "function_expression",
                    source,
                    function=self.name(ast[1]),
                    variable="x",
                    expression=self.text(ast[2]),
                )
            elif k in ("domain", "default_domain"):
                if ast[-1] != "real":
                    raise BindingError("binding.unsupported_domain", source, str(ast))
            elif k in (">", "<", ">=", "<=", "!="):
                a, b = ast[1:]
                if a[0] == "ref" and a[2] == "scalar":
                    fact(
                        "symbol_constraint",
                        source,
                        symbol=self.name(a),
                        operator=k,
                        value=self.text(b),
                    )
                elif b[0] == "ref" and b[2] == "scalar":
                    fact(
                        "symbol_constraint",
                        source,
                        symbol=self.name(b),
                        operator={
                            ">": "<",
                            "<": ">",
                            ">=": "<=",
                            "<=": ">=",
                            "!=": "!=",
                        }[k],
                        value=self.text(a),
                    )
                elif call(a, "x") or call(a, "y"):
                    # Coordinate order/signs are materialized below with their
                    # complete premises. No arbitrary coordinate inequality.
                    if not (call(b, a[1]) or b == ["number", "0"]):
                        raise BindingError(
                            "binding.unsupported_coordinate_condition", source, str(ast)
                        )
                    self.coordinate_conditions.append((ast, source))
                else:
                    raise BindingError(
                        "binding.unsupported_condition", source, str(ast)
                    )
            elif k == "∈":
                point, locus = ast[1:]
                if point[0] != "ref" or point[2] != "point":
                    if locus == ["set_constant", "ℝ"]:
                        continue
                    raise BindingError(
                        "binding.unsupported_membership", source, str(ast)
                    )
                if locus[0] == "ref" and locus[1] in curve_refs:
                    fact(
                        "point_on_curve",
                        source,
                        point=self.name(point),
                        curve=self.name(locus),
                    )
                elif call(locus, "axis"):
                    fact(
                        "point_on_axis",
                        source,
                        point=self.name(point),
                        axis="symmetry",
                        curve=self.name(locus[2]),
                    )
                elif call(locus, "segment"):
                    fact(
                        "point_on_segment",
                        source,
                        point=self.name(point),
                        segment={
                            "start": self.name(locus[2]),
                            "end": self.name(locus[3]),
                        },
                    )
                elif call(locus, "ray"):
                    ray = entity(
                        self.name(locus[2]) + self.name(locus[3]),
                        "named_ray",
                        source,
                        "directed_ray",
                        origin=self.name(locus[2]),
                        through=self.name(locus[3]),
                    )
                    fact("point_on_ray", source, point=self.name(point), ray=ray)
                elif locus[0] == "∩":
                    self.intersection(locus, [point], source, visible, fact)
                else:
                    raise BindingError("binding.unsupported_locus", source, str(locus))
            elif k == "point_intersection_definition":
                self.intersection(ast[2], [ast[1]], source, visible, fact)
            elif call(ast, "square"):
                vertices = [self.name(x) for x in ast[2:]]
                polygon = entity(
                    "".join(vertices),
                    "polygon",
                    source,
                    "square_vertices",
                    vertices=vertices,
                )
                signs = [
                    (a, p)
                    for a, p, _ in visible
                    if a[0] == "<"
                    and call(a[1], "y")
                    and a[1][2] == ast[-1]
                    and a[2] == ["number", "0"]
                ]
                if len(signs) != 1:
                    raise BindingError(
                        "binding.square_orientation_ambiguous",
                        source,
                        "square orientation requires the visible last vertex below the x axis",
                    )
                self.cover_coordinate(*signs[0])
                fact(
                    "square",
                    source,
                    premises=[signs[0][1]],
                    polygon=polygon,
                    side={"start": vertices[0], "end": vertices[1]},
                    orientation={"relation": "below_x_axis", "point": vertices[-1]},
                )
            elif k == "=":
                self.equal(ast, source, visible, fact, entity)
            else:
                raise BindingError("binding.unsupported_relation", source, str(ast))
        # Two coordinate signs together establish a quadrant, retaining both.
        for o in self.objects.values():
            if o["kind"] != "point":
                continue
            signs = {}
            for a, p, _ in entries:
                if (
                    a[0] in (">", "<")
                    and (call(a[1], "x") or call(a[1], "y"))
                    and a[1][2][1] == o["ref"]
                    and a[2] == ["number", "0"]
                ):
                    signs[a[1][1]] = (a[0], p)
            if set(signs) == {"x", "y"}:
                quadrant = {
                    (">", ">"): "I",
                    ("<", ">"): "II",
                    ("<", "<"): "III",
                    (">", "<"): "IV",
                }[(signs["x"][0], signs["y"][0])]
                fact(
                    "quadrant_membership",
                    signs["x"][1],
                    premises=[v[1] for v in signs.values()],
                    point=o["name"],
                    quadrant=quadrant,
                )
                for a, p, _ in entries:
                    if (
                        a[0] in (">", "<")
                        and (call(a[1], "x") or call(a[1], "y"))
                        and a[1][2][1] == o["ref"]
                        and a[2] == ["number", "0"]
                    ):
                        self.cover_coordinate(a, p)
        self.check_attainment_goals(tree, pointer, visible)
        for i, goal in enumerate(tree["goals"]):
            source = f"{pointer}/goals/{i}"
            self.pointer = source
            kind, target = goal["kind"], goal["target"]
            if refs(target) & coordinate_aliases:
                raise BindingError(
                    "binding.coordinate_alias_goal_unbound",
                    source,
                    "a scalar answer for a coordinate alias has no registered runtime binding",
                )
            if kind == "find_coordinates" and call(target, "vertex"):
                name = entity("vertex", "point", source, "goal_vertex")
                fact(
                    "point_construction",
                    source,
                    "goal_vertex",
                    point=name,
                    construction="vertex",
                    owner=self.name(target[2]),
                )
                attrs = {"target": name}
                kind = "point_coordinate"
            elif (
                kind in ("find_coordinates", "find_equation", "find_value")
                and target[0] == "ref"
            ):
                kind = {
                    "find_coordinates": "point_coordinate",
                    "find_equation": "quadratic_equation",
                    "find_value": "parameter_value",
                }[kind]
                attrs = {"target": self.name(target)}
            elif kind == "find_minimum":
                self.bind_motion(target, goal.get("variables", []), source, visible)
                attrs = {"expression": {"terms": self.terms(target)}}
                kind = "minimum_value"
                fact("minimum_target", source, "goal_minimum", **attrs)
            else:
                raise BindingError("binding.unsupported_goal", source, str(goal))
            uid = self.identity(source, "goal", goal)
            goals.append(
                ProblemGoal(uid, kind, attrs.get("target", "min_value"), attrs)
            )
        children = tuple(
            self.scope(c, r, path + (f"c{i}",), f"{pointer}/children/{i}", visible)
            for i, (c, r) in enumerate(zip(tree["children"], raw.get("children", [])))
        )
        uid = self.identity(pointer, "scope", list(path))
        return ProblemScope(
            uid,
            path[-1],
            raw.get("label", "题目"),
            tuple(raw.get("definitions", []) + raw.get("facts", []))
            or (raw.get("label", "题目"),),
            tuple(entities),
            tuple(facts),
            tuple(goals),
            children,
            path,
        )

    def curve_membership(self, point, visible):
        matches = [
            (a, p)
            for a, p, _ in visible
            if a[0] == "∈" and a[1] == point and a[2][0] == "ref" and a[2][2] == "curve"
        ]
        if len({a[2][1] for a, _ in matches}) > 1:
            raise BindingError(
                "binding.curve_membership_ambiguous",
                self.pointer,
                "point has multiple candidate curves",
            )
        return matches[0] if matches else None

    def equal(self, ast, source, visible, fact, entity):
        pair = equality(ast, lambda a: a[0] == "∩", lambda a: a[0] == "set")
        if pair:
            return self.intersection(pair[0], pair[1][1:], source, visible, fact)
        pair = equality(
            ast, lambda a: a[0] == "ref" and a[2] == "point", lambda a: True
        )
        if pair:
            point, value = pair
            name = self.name(point)
            if value[0] == "tuple":
                membership = self.curve_membership(point, visible)
                if value[2][0] == "ref" and membership:
                    fact(
                        "point_construction",
                        source,
                        "coordinate_alias_on_curve",
                        premises=[membership[1]],
                        point=name,
                        construction="curve_at_x",
                        owner=self.name(membership[0][2]),
                        x_expression=self.text(value[1]),
                    )
                else:
                    fact(
                        "point_coordinate",
                        source,
                        point=name,
                        value=[self.text(t) for t in value[1:]],
                    )
                    if value[1:] == [["number", "0"], ["number", "0"]]:
                        fact(
                            "point_construction",
                            source,
                            "coordinate_origin",
                            point=name,
                            construction="origin",
                        )
                    elif (
                        value[2] == ["number", "0"]
                        and value[1][0] == "ref"
                        and not any(
                            value[1][1] in refs(a[2])
                            for a, _, _ in visible
                            if a[0] == "curve_definition"
                        )
                    ):
                        fact(
                            "point_on_axis",
                            source,
                            "zero_ordinate",
                            point=name,
                            axis="x",
                        )
            elif call(value, "vertex"):
                fact(
                    "point_construction",
                    source,
                    point=name,
                    construction="vertex",
                    owner=self.name(value[2]),
                )
            elif call(value, "midpoint"):
                fact(
                    "midpoint",
                    source,
                    point=name,
                    segment={"start": self.name(value[2]), "end": self.name(value[3])},
                )
            elif value[0] == "+" and value[1][0] == "ref" and value[2][0] == "tuple":
                fact(
                    "point_construction",
                    source,
                    point=name,
                    construction="translated_point",
                    owner=self.name(value[1]),
                    vector=[self.text(t) for t in value[2][1:]],
                )
            else:
                raise BindingError(
                    "binding.unsupported_point_definition", source, str(value)
                )
            return
        pair = equality(ast, lambda a: call(a, "x"), lambda a: True)
        if pair:
            coordinate, value = pair
            point = coordinate[2]
            membership = self.curve_membership(point, visible)
            if membership is None:
                raise BindingError(
                    "binding.coordinate_curve_missing",
                    source,
                    "x coordinate needs a unique curve membership",
                )
            fact(
                "point_construction",
                source,
                "coordinate_on_curve",
                premises=[membership[1]],
                point=self.name(point),
                construction="curve_at_x",
                owner=self.name(membership[0][2]),
                x_expression=self.text(value),
            )
            return
        pair = equality(ast, lambda a: a[0] == "extremum", lambda a: True)
        if pair:
            minimum, value = pair
            if minimum[1] != "min":
                raise BindingError("binding.unsupported_extremum", source, str(minimum))
            self.bind_motion(minimum[3], minimum[2], source, visible)
            terms = {"terms": self.terms(minimum[3])}
            fact("minimum_target", source, "minimum_path", expression=terms)
            if self.same_path(value, minimum[3]):
                fact("minimum_attained", source, expression=terms)
            else:
                fact(
                    "minimum_value_given",
                    source,
                    expression=terms,
                    value=self.text(value),
                )
            return
        pair = equality(ast, lambda a: call(a, "angle"), lambda a: a[0] == "degrees")
        if pair and self.algebra(pair[1][1]) == 90:
            fact(
                "right_angle",
                source,
                angle=dict(
                    zip(("start", "vertex", "end"), map(self.name, pair[0][2:]))
                ),
            )
            return
        pair = equality(ast, lambda a: a[0] == "+", lambda a: a[0] == "degrees")
        if pair and all(call(a, "angle") for a in pair[0][1:]):
            fact(
                "angle_sum",
                source,
                angles=[
                    dict(zip(("start", "vertex", "end"), map(self.name, a[2:])))
                    for a in pair[0][1:]
                ],
                value=self.text(pair[1][1]),
            )
            return
        try:
            left, right = self.terms(ast[1]), self.terms(ast[2])
        except BindingError:
            left = right = None
        if left and right and len(left) == len(right) == 1:
            if left[0]["scale"] == right[0]["scale"] == "1":
                fact(
                    "equal_length",
                    source,
                    left=left[0]["segment"],
                    right=right[0]["segment"],
                )
            else:
                fact("length_relation", source, left=left[0], right=right[0])
            return
        pair = equality(ast, lambda a: call(a, "length"), lambda a: True)
        if pair:
            fact(
                "length_value",
                source,
                segment=self.segment(pair[0]),
                power=1,
                value=self.text(pair[1]),
            )
            return
        pair = equality(
            ast, lambda a: a[0] == "ref" and a[2] == "scalar", lambda a: True
        )
        if pair:
            fact(
                "symbol_value",
                source,
                symbol=self.name(pair[0]),
                value=self.text(pair[1]),
            )
        else:
            expression = f"{self.text(ast[1])} = {self.text(ast[2])}"
            fact(
                "equation",
                source,
                expression=expression,
                symbols=sorted({self.objects[r]["name"] for r in refs(ast)}),
            )

    def intersection(self, locus, points, source, visible, fact):
        a, b = locus[1:]
        if a[0] == "axis_constant":
            a, b = b, a
        if b == ["axis_constant", "x_axis"] and call(a, "axis") and len(points) == 1:
            fact(
                "point_construction",
                source,
                point=self.name(points[0]),
                construction="axis_x_intercept",
                owner=self.name(a[2]),
            )
            return
        if a[0] == "ref" and a[2] == "curve" and b[0] == "axis_constant":
            axis = b[1]
            if axis == "y_axis" and len(points) == 1:
                fact(
                    "point_construction",
                    source,
                    point=self.name(points[0]),
                    construction="y_axis_intercept",
                    owner=self.name(a),
                )
                return
            if axis == "x_axis" and len(points) == 2:
                ordering = next(
                    (
                        (f, p)
                        for f, p, _ in visible
                        if f[0] == "<"
                        and call(f[1], "x")
                        and call(f[2], "x")
                        and {f[1][2][1], f[2][2][1]} == {p[1] for p in points}
                    ),
                    None,
                )
                if ordering:
                    self.cover_coordinate(*ordering)
                    for side, point in zip(
                        ("left", "right"), (ordering[0][1][2], ordering[0][2][2])
                    ):
                        fact(
                            "point_construction",
                            source,
                            "ordered_axis_roots",
                            premises=[ordering[1]],
                            point=self.name(point),
                            construction="x_axis_intercept",
                            owner=self.name(a),
                            side=side,
                        )
                else:
                    known = next(
                        (
                            (pt, f, p)
                            for pt in points
                            for f, p, _ in visible
                            if f[0] == "="
                            and f[1] == pt
                            and f[2][0] == "tuple"
                            and f[2][2] == ["number", "0"]
                        ),
                        None,
                    )
                    if known is None:
                        raise BindingError(
                            "binding.intersection_selection_ambiguous",
                            source,
                            "two roots require order or a provably distinct known root",
                        )
                    pt, coordinate, cp = known
                    premises = self.distinct_roots(a, coordinate[2][1], visible)
                    other = next(p for p in points if p != pt)
                    fact(
                        "point_construction",
                        source,
                        "distinct_quadratic_roots",
                        premises=[cp, *premises],
                        point=self.name(other),
                        construction="x_axis_intercept",
                        owner=self.name(a),
                        exclude_point=self.name(pt),
                    )
                for point in points:
                    fact(
                        "point_on_curve",
                        source,
                        "intersection_membership",
                        point=self.name(point),
                        curve=self.name(a),
                    )
                return
        if (
            all(call(x, "segment") or call(x, "line") for x in (a, b))
            and len(points) == 1
        ):
            pairs = {frozenset(p[1] for p in x[2:]) for x in (a, b)}
            for square, spointer, _ in visible:
                if call(square, "square") and pairs == {
                    frozenset((square[2][1], square[4][1])),
                    frozenset((square[3][1], square[5][1])),
                }:
                    fact(
                        "square_center",
                        source,
                        "square_diagonals",
                        premises=[spointer],
                        point=self.name(points[0]),
                        square="".join(self.name(p) for p in square[2:]),
                    )
                    for diagonal in (a, b):
                        if call(diagonal, "segment"):
                            fact(
                                "point_on_segment",
                                source,
                                "intersection_membership",
                                point=self.name(points[0]),
                                segment={
                                    "start": self.name(diagonal[2]),
                                    "end": self.name(diagonal[3]),
                                },
                            )
                    return
        raise BindingError("binding.unsupported_intersection", source, str(locus))

    def bind_motion(self, expression, explicit, source, visible):
        path_points = {
            r for r in refs(expression) if self.objects[r]["kind"] == "point"
        }
        allowed = set()
        premises = []
        coefficients = set().union(
            *(refs(a[2]) for a, _, _ in visible if a[0] == "curve_definition")
        )
        for ast, p, _ in visible:
            if (
                ast[0] == "∈"
                and ast[1][0] == "ref"
                and ast[1][1] in path_points
                and (call(ast[2], "segment") or call(ast[2], "ray"))
            ):
                allowed.add(ast[1][1])
                premises.append(p)
            pair = equality(
                ast,
                lambda a: a[0] == "ref" and a[2] == "point",
                lambda a: a[0] == "tuple",
            )
            if pair and pair[0][1] in path_points and pair[1][2] == ["number", "0"]:
                free = refs(pair[1][1]) - coefficients
                if len(free) == 1:
                    allowed.update(free)
                    premises.append(p)
                elif free:
                    raise BindingError(
                        "binding.motion_ambiguous",
                        source,
                        "axis motion must have a unique independent coordinate parameter",
                    )
            if call(ast, "square") and path_points.intersection(refs(ast)):
                for membership, mp, _ in visible:
                    if (
                        membership[0] == "∈"
                        and membership[1] == ast[3]
                        and call(membership[2], "axis")
                    ):
                        allowed.add(ast[3][1])
                        premises.extend([p, mp])
        if not allowed:
            raise BindingError(
                "binding.motion_ambiguous",
                source,
                "no unique supported motion mechanism is visible",
            )
        scalar_variables = {r for r in allowed if self.objects[r]["kind"] == "scalar"}
        if scalar_variables and len(allowed) != 1:
            raise BindingError(
                "binding.motion_ambiguous",
                source,
                "multiple independent motion variables are visible",
            )
        supplied = set().union(*(refs(v) for v in explicit))
        if explicit and supplied != allowed:
            raise BindingError(
                "binding.motion_variables_mismatch",
                source,
                "explicit minimum variables differ from the method motion binding",
            )
        self.motion_bindings.append(
            {
                "path": source,
                "expression": expression,
                "variables": sorted(allowed),
                "premises": sorted(set(premises)),
            }
        )

    def check_attainment_goals(self, tree, pointer, visible):
        paths = []
        attained = []
        for ast, p, _ in visible:
            pair = equality(
                ast, lambda a: a[0] == "extremum" and a[1] == "min", lambda a: True
            )
            if pair:
                paths.append(pair[0][3])
                if self.same_path(pair[1], pair[0][3]):
                    attained.append(pair[0][3])
        for i, goal in enumerate(tree["goals"]):
            if goal["kind"] != "find_coordinates" or goal["target"][0] != "ref":
                continue
            target = goal["target"][1]
            for expression in paths:
                dependent = refs(expression)
                for ast, _, _ in visible:
                    if call(ast, "square") and dependent.intersection(refs(ast)):
                        dependent |= refs(ast)
                if target not in dependent:
                    continue
                moving = any(
                    ast[0] == "∈"
                    and ast[1] == goal["target"]
                    and (
                        call(ast[2], "segment")
                        or call(ast[2], "ray")
                        or call(ast[2], "axis")
                    )
                    for ast, _, _ in visible
                )
                if moving and not any(self.same_path(expression, a) for a in attained):
                    raise BindingError(
                        "binding.attainment_state_required",
                        f"{pointer}/goals/{i}",
                        "a path value does not specify the moving point at attainment",
                    )

    def distinct_roots(self, curve, coordinate, visible):
        definition = next(
            (a, p)
            for a, p, _ in visible
            if a[0] == "curve_definition" and a[1] == curve
        )
        x = sp.Symbol("x")
        poly = self.algebra(definition[0][2])
        value = self.algebra(coordinate)
        root_equation = sp.expand(poly.subs(x, value))
        derivative = sp.diff(poly, x).subs(x, value)
        premises = [definition[1]]
        positive = {}
        for a, p, _ in visible:
            if (
                a[0] == ">"
                and a[1][0] == "ref"
                and a[1][2] == "scalar"
                and a[2] == ["number", "0"]
            ):
                name = self.name(a[1])
                positive[sp.Symbol(name)] = sp.Symbol(name, positive=True)
                premises.append(p)
        candidates = [derivative]
        for symbol in sorted(root_equation.free_symbols, key=str):
            coefficient = sp.diff(root_equation, symbol)
            if coefficient.is_number and coefficient.is_zero is False:
                replacement = sp.simplify(symbol - root_equation / coefficient)
                candidates.append(sp.simplify(derivative.subs(symbol, replacement)))
        if not any(sp.simplify(d.subs(positive)).is_zero is False for d in candidates):
            raise BindingError(
                "binding.intersection_distinctness_unproved",
                self.pointer,
                "the known quadratic root is not provably simple",
            )
        return premises
