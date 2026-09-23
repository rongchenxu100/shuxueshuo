"""Standalone bounded proof search and local certificate replay (no Runtime).

Premises are explicitly supplied by the caller. A successful conditional proof
never asserts feasibility, complete solution enumeration, or execution authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from fractions import Fraction as Q
from functools import partial
from hashlib import sha256

import sympy as sp

from .expression_parser import (
    MathNode,
    MathParseError,
    ParsedMath,
    parse_math_expression,
    parse_math_relation,
)
from .proof_algebra import (
    ONE,
    ZERO,
    Arithmetic,
    ProofFailure,
    digest,
    domains,
    expr,
    freeze,
    from_node,
    names,
    number,
    rat,
    signed_integer,
    substitute,
    walk,
)

RELATIONS = {"=", "!=", ">", ">=", "<", "<="}
SIGNS = {"=": {0}, "!=": {-1, 1}, ">": {1}, ">=": {0, 1}, "<": {-1}, "<=": {-1, 0}}
REVERSE = {"=": "=", "!=": "!=", ">": "<", "<": ">", ">=": "<=", "<=": ">="}
RULES = (
    "given",
    "constant",
    "polynomial",
    "difference",
    "sign",
    "scale",
    "equal_sign",
    "square_equal",
    "root_square",
    "monotone",
    "transitive",
    "weaken",
    "factor_nonzero",
    "interval",
    "substitution",
    "guard",
    "all",
    "witness",
    "exists",
)
RULESET_VERSION = "bounded-real-proof/v1"
RULESET_HASH = digest({"version": RULESET_VERSION, "rules": RULES})


@dataclass(frozen=True)
class ProofLimits:
    premises: int = 16
    variables: int = 4
    radicals: int = 4
    equations: int = 4
    polynomial_degree: int = 12
    polynomial_terms: int = 128
    coefficient_bits: int = 4096
    reductions: int = 256
    depth: int = 32
    nodes: int = 512
    attempts: int = 512
    branches: int = 8
    algebraic_degree: int = 16
    refinements: int = 128


@dataclass(frozen=True)
class ProofContext:
    symbols: Mapping[str, sp.Symbol]
    premises: Mapping[str, ParsedMath] = field(default_factory=dict)
    limits: ProofLimits = field(default_factory=ProofLimits)
    scope_id: str = "authoring"


@dataclass(frozen=True)
class ProofNode:
    node_id: str
    rule_id: str
    conclusion: tuple
    children: tuple[str, ...]
    premises: tuple[str, ...]
    input_nodes: tuple[dict, ...]
    certificate: dict

    def to_payload(self):
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True)
class ProofResult:
    status: str
    code: str | None = None
    diagnostic: str | None = None
    proof: dict | None = None
    branches: tuple[dict, ...] = ()

    def to_payload(self):
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True)
class Witness:
    assignments: Mapping[str, ParsedMath]
    # A single real parameter on a rational closed interval. This is a
    # candidate domain, validated by the witness rule, not a new source fact.
    parameter: str | None = None
    interval: tuple[str, str] | None = None


class _Budget:
    def __init__(self, limits):
        self.limits, self.counts = limits, {}
        if not isinstance(limits, ProofLimits) or any(
            type(v) is not int or v <= 0 for v in asdict(limits).values()
        ):
            raise ProofFailure(
                "invalid_input", "positive integer proof limits required"
            )

    def use(self, field, amount=1):
        self.counts[field] = self.counts.get(field, 0) + amount
        if self.counts[field] > getattr(self.limits, field):
            raise ProofFailure("proof_limit", f"{field} budget exhausted")


def _document(parsed):
    return {
        "source": parsed.source,
        "source_path": parsed.source_path,
        "step": parsed.step,
    }


def _checked(parsed, symbols, *, relation=True):
    if not isinstance(parsed, ParsedMath):
        raise ProofFailure("invalid_input", "ParsedMath required")
    parse = parse_math_relation if relation else parse_math_expression
    replayed = parse(parsed.source, symbols)
    if (
        replayed.ast != parsed.ast
        or replayed.tree != parsed.tree
        or replayed.normalized_source != parsed.normalized_source
        or replayed.source_map != parsed.source_map
        or replayed.obligations != parsed.obligations
    ):
        raise ProofFailure(
            "invalid_input", "parsed syntax or obligations were modified"
        )
    return replayed


def _read_document(document, symbols, *, relation=True):
    if not isinstance(document, dict) or set(document) != {
        "source",
        "source_path",
        "step",
    }:
        raise ProofFailure("invalid_proof", "invalid source document")
    if document["source_path"] is not None and not isinstance(
        document["source_path"], str
    ):
        raise ProofFailure("invalid_proof", "invalid source path")
    if document["step"] is not None and type(document["step"]) is not int:
        raise ProofFailure("invalid_proof", "invalid source step")
    return (parse_math_relation if relation else parse_math_expression)(
        document["source"], symbols
    )


def _relation(e):
    return isinstance(e, tuple) and len(e) == 3 and e[0] in RELATIONS


def _factors(e):
    if e[0] == "mul":
        return {e[1], e[2]} | _factors(e[1]) | _factors(e[2])
    if e[0] == "pow" and signed_integer(e[2]) != 0:
        return {e[1]} | _factors(e[1])
    return set()


def _root_claims(root):
    return (
        (">=", root[1], ZERO),
        (">=", root, ZERO),
        ("=", ("pow", root, number(2)), root[1]),
    )


def _ordered(g):
    if g[0] in {">", ">="}:
        return g
    if g[0] in {"<", "<="}:
        return (REVERSE[g[0]], g[2], g[1])
    return None


def _diff(g):
    return expr("sub", g[1], g[2])


def _holds(sign, operator):
    return sign in SIGNS[operator]


def _failure(exc, branches=()):
    if isinstance(exc, ProofFailure):
        return ProofResult("not_proved", exc.code, str(exc), branches=branches)
    return ProofResult("not_proved", "invalid_input", str(exc), branches=branches)


def _noncyclic(mapping):
    pending, done = set(), set()

    def visit(name):
        if name in pending:
            raise ProofFailure("proof_missing", "cyclic substitution")
        if name in done:
            return
        pending.add(name)
        for dependency in names(mapping[name]) & mapping.keys():
            visit(dependency)
        pending.remove(name)
        done.add(name)

    for name in mapping:
        visit(name)


class _Environment:
    def __init__(self, context, request, *, budget=None):
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        if not isinstance(context.scope_id, str) or not context.scope_id:
            raise ProofFailure("invalid_input", "explicit scope identity required")
        self.scope_id = context.scope_id
        self.budget = budget or _Budget(context.limits)
        self.witness_replay_budget = self.budget
        self.arithmetic = Arithmetic(self.budget)
        if (
            len(context.symbols) > context.limits.variables
            or len(context.premises) > context.limits.premises
        ):
            raise ProofFailure("proof_limit", "context size limit")
        if any(
            not isinstance(k, str) or not isinstance(v, sp.Symbol) or v.is_real is False
            for k, v in context.symbols.items()
        ):
            raise ProofFailure("invalid_input", "named real scalar symbols required")
        # Never consume caller-provided positive/negative Symbol assumptions.
        self.symbols = {
            name: sp.Symbol(name, real=True) for name in sorted(context.symbols)
        }
        self.documents, self.sources, self.premises = {}, {}, {}
        for key, parsed in sorted(context.premises.items()):
            if not isinstance(key, str) or not key:
                raise ProofFailure("invalid_input", "nonempty premise IDs required")
            checked = _checked(parsed, self.symbols)
            self.premises[key] = from_node(checked.ast)
            self.documents["premise:" + key] = _document(parsed)
            self.sources["premise:" + key] = checked
        self.request = request
        self._request_sources(request)
        self.context_hash = digest(
            {
                "scope_id": self.scope_id,
                "symbols": sorted(self.symbols),
                "premises": {k: self.documents["premise:" + k] for k in self.premises},
                "limits": asdict(context.limits),
            }
        )
        self.nodes = []
        self.by_id = {}
        self.depths = {}
        self._check_context()

    def _request_sources(self, request):
        shapes = {
            "relation": {"kind", "candidate"},
            "domain": {"kind", "candidate"},
            "bundle": {"kind", "relations", "expressions"},
            "witness": {
                "kind",
                "witnesses",
                "requirements",
                "mode",
                "selected_branch",
                "require_parameterized",
            },
        }
        if not isinstance(request, dict) or set(request) != shapes.get(
            request.get("kind"), set()
        ):
            raise ProofFailure("invalid_input", "invalid proof request shape")
        if request["kind"] in {"relation", "domain"}:
            parsed = _read_document(
                request["candidate"],
                self.symbols,
                relation=request["kind"] == "relation",
            )
            self.documents["candidate"] = request["candidate"]
            self.sources["candidate"] = parsed
        elif request["kind"] == "bundle":
            if len(request["relations"]) > 32 or len(request["expressions"]) > 4:
                raise ProofFailure("proof_limit", "witness bundle size limit")
            for kind, relation in (("relations", True), ("expressions", False)):
                for i, doc in enumerate(request[kind]):
                    key = f"bundle_{'relation' if relation else 'expression'}:{i}"
                    self.documents[key], self.sources[key] = (
                        doc,
                        _derived_source(
                            doc, self.symbols, self.budget, relation=relation
                        ),
                    )
        elif request["kind"] == "witness":
            # Witness proofs are built in the original context. Requirements and
            # assignments are source documents, not silently promoted premises.
            if (
                not 1 <= len(request["witnesses"]) <= self.budget.limits.branches
                or not 1 <= len(request["requirements"]) <= 16
            ):
                raise ProofFailure("proof_limit", "witness request size limit")
            if request["require_parameterized"] and any(
                w["parameter"] is None for w in request["witnesses"]
            ):
                raise ProofFailure(
                    "proof_missing", "range attainment requires a parameterization"
                )
            if (
                request["mode"] not in {"all", "exists"}
                or type(request["require_parameterized"]) is not bool
                or (request["mode"] == "all" and request["selected_branch"] is not None)
                or (
                    request["mode"] == "exists"
                    and (
                        type(request["selected_branch"]) is not int
                        or not 0
                        <= request["selected_branch"]
                        < len(request["witnesses"])
                    )
                )
            ):
                raise ProofFailure("invalid_input", "invalid witness mode")
            for witness in request["witnesses"]:
                if set(witness) != {
                    "assignments",
                    "parameter",
                    "interval",
                } or not isinstance(witness["assignments"], dict):
                    raise ProofFailure("invalid_input", "invalid witness shape")
            requirement_symbols = dict(self.symbols)
            for witness in request["witnesses"]:
                if witness["parameter"] is not None:
                    requirement_symbols[witness["parameter"]] = sp.Symbol(
                        witness["parameter"], real=True
                    )
            for i, doc in enumerate(request["requirements"]):
                key = f"requirement:{i}"
                self.documents[key], self.sources[key] = (
                    doc,
                    _read_document(doc, requirement_symbols),
                )
            for i, witness in enumerate(request["witnesses"]):
                parameter = witness["parameter"]
                local = dict(self.symbols)
                if parameter is not None:
                    if parameter in local or not isinstance(parameter, str):
                        raise ProofFailure("invalid_input", "parameter must be fresh")
                    local[parameter] = sp.Symbol(parameter, real=True)
                for name, doc in witness["assignments"].items():
                    if name not in self.symbols:
                        raise ProofFailure("invalid_input", "unknown assigned symbol")
                    key = f"assignment:{i}:{name}"
                    self.documents[key], self.sources[key] = (
                        doc,
                        _read_document(doc, local, relation=False),
                    )
        else:
            raise ProofFailure("invalid_input", "unknown proof request")

    def refs(self, conclusion, premise_ids):
        keys = [k for k in self.sources if not k.startswith("premise:")]
        keys.extend("premise:" + k for k in premise_ids)
        if conclusion[0] in {"witness", "exists"}:
            keys.extend("premise:" + k for k in self.premises)
        keys = sorted(set(keys))
        result = []
        for key in sorted(keys):
            parsed, doc = self.sources[key], self.documents[key]
            # Include the root plus exact originating subexpressions when they
            # exist. Derived expressions are linked through child proofs.
            selected = [parsed.ast]
            if _relation(conclusion):
                selected.extend(
                    n
                    for n in parsed.ast.walk()
                    if from_node(n) in conclusion[1:] and n.path != parsed.ast.path
                )
            for node in selected:
                result.append(
                    {
                        "document": key,
                        "source_sha256": sha256(doc["source"].encode()).hexdigest(),
                        "source_path": doc["source_path"]
                        if doc["source_path"] is not None
                        else "/sources/"
                        + key.replace("~", "~0").replace("/", "~1")
                        + "/source",
                        "node_path": node.path,
                        "span": list(node.span),
                    }
                )
        return tuple(result)

    def add(self, rule, conclusion, children=(), certificate=None):
        self.budget.use("nodes")
        children = tuple(children)
        certificate = certificate or {}
        used = set().union(*(set(self.by_id[c].premises) for c in children))
        if rule == "given":
            used.add(certificate["premise_id"])
        premises = tuple(sorted(used))
        node = ProofNode(
            f"p{len(self.nodes):04d}",
            "math." + rule,
            conclusion,
            children,
            premises,
            self.refs(conclusion, premises),
            certificate,
        )
        self.check_node(node)
        self.check_depth(node)
        self.nodes.append(node)
        self.by_id[node.node_id] = node
        return node.node_id

    def check_depth(self, node):
        depth = 1 + max((self.depths[c] for c in node.children), default=0)
        if node.rule_id == "math.witness":
            depth = max(depth, 1 + _payload_depth(node.certificate["proof"]))
        if depth > self.budget.limits.depth:
            raise ProofFailure("proof_limit", "proof tree depth limit")
        self.depths[node.node_id] = depth

    def guarded(self, node_id, expected=None):
        node = self.by_id[node_id]
        if node.rule_id != "math.guard" or (
            expected is not None and node.conclusion != expected
        ):
            raise ProofFailure("invalid_proof", "guarded relation dependency required")
        return node.conclusion

    def _check_context(self):
        a = self.arithmetic
        items = list(self.premises.values())
        for g in items:
            try:
                if g[0] == "=":
                    a.equation_divisor(g)
                difference = _diff(g)
                constant = a.constant_expression(difference) if names(g) else difference
                if constant is None:
                    continue
                sign, _ = a.constant_certificate(constant)
            except ProofFailure as exc:
                if exc.code != "proof_missing":
                    raise
                continue
            if not _holds(sign, g[0]):
                raise ProofFailure("inconsistent_premises", "false constant premise")
        for i, g in enumerate(items):
            for h in items[:i]:
                ratio = a.proportional(_diff(g), _diff(h))
                if ratio:
                    signs = {s * (1 if ratio > 0 else -1) for s in SIGNS[h[0]]}
                    if not SIGNS[g[0]] & signs:
                        raise ProofFailure(
                            "inconsistent_premises", "opposite source premises"
                        )
        bounds = self.bounds()
        for name in self.symbols:
            for lo in bounds.get((name, "lower"), []):
                for hi in bounds.get((name, "upper"), []):
                    if lo[0] > hi[0] or (lo[0] == hi[0] and (lo[2] or hi[2])):
                        raise ProofFailure(
                            "inconsistent_premises", "empty source interval"
                        )

    def bounds(self):
        result = {}
        for key, g in self.premises.items():
            op, x, y = g
            if y[0] == "symbol":
                x, y, op = y, x, REVERSE[op]
            if x[0] != "symbol" or op not in {"=", ">", ">=", "<", "<="}:
                continue
            endpoint = self.arithmetic.literal_rational(y)
            if endpoint is None:
                continue
            if op == "=":
                for side in ("lower", "upper"):
                    result.setdefault((x[1], side), []).append((endpoint, key, False))
                continue
            side = "lower" if op in {">", ">="} else "upper"
            result.setdefault((x[1], side), []).append(
                (endpoint, key, op in {">", "<"})
            )
        return result

    def interval_certificate(self, e, lower_id, upper_id):
        a = self.arithmetic
        variables = names(e)
        if len(variables) != 1:
            raise ProofFailure("proof_missing", "univariate interval required")
        name = next(iter(variables))
        bounds = self.bounds()
        lo = next(
            (x[0] for x in bounds.get((name, "lower"), []) if x[1] == lower_id), None
        )
        hi = next(
            (x[0] for x in bounds.get((name, "upper"), []) if x[1] == upper_id), None
        )
        if lo is None or hi is None or lo > hi:
            raise ProofFailure("invalid_proof", "invalid interval premises")
        numerator, denominator = a.rational(e)
        if set(denominator) != {()} or not denominator[()]:
            raise ProofFailure(
                "proof_missing", "polynomial interval expression required"
            )
        coefficients = [Q(0), Q(0), Q(0)]
        for m, c in numerator.items():
            if m and (len(m) != 1 or m[0][0] != "s:" + name or m[0][1] > 2):
                raise ProofFailure("proof_missing", "interval degree exceeds two")
            coefficients[m[0][1] if m else 0] = c / denominator[()]
        points = [lo, hi]
        if coefficients[2]:
            vertex = -coefficients[1] / (2 * coefficients[2])
            if lo < vertex < hi:
                points.append(vertex)
        values = [
            a.check_q(coefficients[0] + coefficients[1] * x + coefficients[2] * x * x)
            for x in points
        ]
        return {
            "lower": lower_id,
            "upper": upper_id,
            "points": [str(x) for x in points],
            "values": [str(x) for x in values],
        }

    def check_node(self, node):
        """Local rule verification only: no call to the search engine."""
        rule = node.rule_id.removeprefix("math.")
        if rule not in RULES or node.rule_id != "math." + rule:
            raise ProofFailure("invalid_proof", "unknown proof rule")
        if any(c not in self.by_id for c in node.children):
            raise ProofFailure("invalid_proof", "forward or cyclic proof dependency")
        used = set().union(*(set(self.by_id[c].premises) for c in node.children))
        if rule == "given":
            used.add(node.certificate.get("premise_id"))
        if tuple(sorted(used)) != node.premises or node.input_nodes != self.refs(
            node.conclusion, node.premises
        ):
            raise ProofFailure("invalid_proof", "provenance mismatch")
        g, cert, a = node.conclusion, node.certificate, self.arithmetic
        if _relation(g):
            _validate_expression(g, self.symbols, self.budget, relation=True)
            a.roots([g])
        if rule == "guard":
            if not _relation(g) or not node.children:
                raise ProofFailure("invalid_proof", "invalid domain guard")
            core = self.by_id[node.children[0]]
            if core.conclusion != g or core.rule_id in {
                "math.guard",
                "math.all",
                "math.witness",
                "math.exists",
            }:
                raise ProofFailure("invalid_proof", "invalid core proof")
            required = domains(g)
            actual = tuple(self.guarded(c) for c in node.children[1:])
            if actual != required or cert:
                raise ProofFailure(
                    "invalid_proof", "missing or altered domain obligations"
                )
            return
        if rule == "all":
            actual = tuple(self.guarded(c) for c in node.children)
            if g != ("all", *actual) or cert:
                raise ProofFailure("invalid_proof", "invalid conjunction")
            return
        if rule in {"witness", "exists"}:
            self.check_witness_node(node)
            return
        if not _relation(g):
            raise ProofFailure("invalid_proof", "relation conclusion required")
        children = [self.guarded(c) for c in node.children]
        if rule == "given":
            if (
                children
                or cert != {"premise_id": cert.get("premise_id")}
                or self.premises.get(cert["premise_id"]) != g
            ):
                raise ProofFailure("invalid_proof", "wrong source premise")
        elif rule == "constant":
            sign, expected = a.constant_certificate(_diff(g), supplied=cert)
            if children or cert != expected or not _holds(sign, g[0]):
                raise ProofFailure("invalid_proof", "invalid exact comparison")
        elif rule == "transitive":
            target = _ordered(g)
            chain = [_ordered(c) for c in children]
            if not target or len(chain) != 2 or any(x is None for x in chain) or cert:
                raise ProofFailure("invalid_proof", "invalid order chain")
            first, second = chain
            if (
                first[1] != target[1]
                or first[2] != second[1]
                or second[2] != target[2]
                or (target[0] == ">" and first[0] == second[0] == ">=")
            ):
                raise ProofFailure("invalid_proof", "invalid order transitivity")
        elif rule == "weaken":
            if len(children) != 1:
                raise ProofFailure("invalid_proof", "one signed premise required")
            ratio = a.proportional(_diff(g), _diff(children[0]))
            possible = {
                x * (1 if ratio and ratio > 0 else -1) for x in SIGNS[children[0][0]]
            }
            if (
                not ratio
                or cert != {"ratio": str(ratio)}
                or not possible <= SIGNS[g[0]]
            ):
                raise ProofFailure(
                    "invalid_proof", "invalid signed premise normalization"
                )
        elif rule == "factor_nonzero":
            if (
                len(children) != 1
                or children[0][0] != "!="
                or children[0][2] != ZERO
                or g[0] != "!="
                or g[2] != ZERO
                or cert
            ):
                raise ProofFailure("invalid_proof", "nonzero product required")
            if g[1] not in _factors(children[0][1]):
                raise ProofFailure(
                    "invalid_proof", "expression is not a product factor"
                )
        elif rule == "difference":
            if children != [(g[0], _diff(g), ZERO)] or cert:
                raise ProofFailure("invalid_proof", "invalid difference transformation")
        elif rule == "polynomial":
            if g[0] != "=" or set(cert) != {"equations", "roots", "multipliers"}:
                raise ProofFailure("invalid_proof", "invalid polynomial certificate")
            eq_ids = cert["equations"]
            if len(eq_ids) > self.budget.limits.equations or len(eq_ids) != len(
                set(eq_ids)
            ):
                raise ProofFailure("proof_limit", "equation count limit")
            equations = [self.premises[k] for k in eq_ids]
            if any(e[0] != "=" for e in equations):
                raise ProofFailure("invalid_proof", "equality premise required")
            roots = a.roots([g, *equations])
            if cert["roots"] != list(roots):
                raise ProofFailure("invalid_proof", "radical identity mismatch")
            required = list(
                dict.fromkeys(
                    [
                        *equations,
                        *(claim for r in roots.values() for claim in _root_claims(r)),
                    ]
                )
            )
            if children != required:
                raise ProofFailure(
                    "invalid_proof", "missing equation or radical-domain evidence"
                )
            divisors = [a.equation_divisor(e) for e in equations] + [
                a.root_polynomial(r) for r in roots.values()
            ]
            if len(cert["multipliers"]) != len(divisors):
                raise ProofFailure("invalid_proof", "multiplier count mismatch")
            total = {}
            for multiplier, divisor in zip(cert["multipliers"], divisors, strict=True):
                total = a.add(total, a.mul(a.decode(multiplier), divisor))
            if total != a.difference(g):
                raise ProofFailure(
                    "invalid_proof", "polynomial identity does not replay"
                )
        elif rule == "sign":
            self.check_sign(g, children, cert)
        elif rule == "scale":
            if len(children) != 2 or cert or g[2] != ZERO:
                raise ProofFailure("invalid_proof", "invalid scaling")
            premise, factor_sign = children
            if factor_sign[2] != ZERO:
                raise ProofFailure("invalid_proof", "invalid factor sign")
            expected = expr("mul", _diff(premise), factor_sign[1])
            if a.difference(("=", g[1], expected)):
                raise ProofFailure("invalid_proof", "scaling identity mismatch")
            possible = {x * y for x in SIGNS[premise[0]] for y in SIGNS[factor_sign[0]]}
            if not possible <= SIGNS[g[0]]:
                raise ProofFailure("invalid_proof", "unproved multiplier direction")
        elif rule == "equal_sign":
            if len(children) != 2 or cert or g[2] != ZERO:
                raise ProofFailure("invalid_proof", "invalid equality sign transfer")
            eq, sign = children
            if eq[0] != "=" or eq[1] != g[1] or sign != (g[0], eq[2], ZERO):
                raise ProofFailure("invalid_proof", "equality transfer mismatch")
        elif rule == "root_square":
            if (
                g[0] != "="
                or g[1][0] != "pow"
                or g[1][1][0] != "sqrt"
                or signed_integer(g[1][2]) != 2
                or g[2] != g[1][1][1]
                or children != [(">=", g[2], ZERO)]
                or cert
            ):
                raise ProofFailure(
                    "invalid_proof", "principal root identity requires its domain"
                )
        elif rule == "square_equal":
            required = [
                (">=", g[1], ZERO),
                (">=", g[2], ZERO),
                ("=", ("pow", g[1], number(2)), ("pow", g[2], number(2))),
            ]
            if g[0] != "=" or children != list(dict.fromkeys(required)) or cert:
                raise ProofFailure(
                    "invalid_proof", "square equality lacks nonnegative sides"
                )
        elif rule == "monotone":
            x, y = g[1:]
            if x[0] == y[0] == "sqrt":
                required = [(g[0], x[1], y[1])]
            elif x[:2] == y[:2] == ("div", ONE):
                required = [
                    (">", x[2], ZERO),
                    (">", y[2], ZERO),
                    (REVERSE[g[0]], x[2], y[2]),
                ]
            else:
                raise ProofFailure("invalid_proof", "unknown monotonicity")
            if children != list(dict.fromkeys(required)) or cert:
                raise ProofFailure("invalid_proof", "monotonicity evidence mismatch")
        elif rule == "interval":
            expected = self.interval_certificate(_diff(g), cert["lower"], cert["upper"])
            values = [Q(v) for v in expected["values"]]
            possible = (
                {0}
                if min(values) == max(values) == 0
                else (
                    {-1}
                    if max(values) < 0
                    else {1}
                    if min(values) > 0
                    else {0, 1}
                    if min(values) >= 0
                    else {-1, 0}
                    if max(values) <= 0
                    else {-1, 0, 1}
                )
            )
            if (
                cert != expected
                or children
                != list(
                    dict.fromkeys(
                        [self.premises[cert["lower"]], self.premises[cert["upper"]]]
                    )
                )
                or not possible <= SIGNS[g[0]]
            ):
                raise ProofFailure(
                    "invalid_proof", "interval extrema do not prove goal"
                )
        elif rule == "substitution":
            if (
                set(cert) != {"bindings"}
                or len(cert["bindings"]) > self.budget.limits.equations
            ):
                raise ProofFailure("invalid_proof", "invalid substitution certificate")
            mapping = {}
            eqs = []
            for entry in cert["bindings"]:
                equation = self.premises[entry["premise_id"]]
                side = entry["side"]
                if (
                    equation[0] != "="
                    or side not in (1, 2)
                    or equation[side][0] != "symbol"
                ):
                    raise ProofFailure("invalid_proof", "invalid substitution equation")
                name = equation[side][1]
                if name in mapping:
                    raise ProofFailure("invalid_proof", "duplicate substitution target")
                mapping[name] = equation[3 - side]
                eqs.append(equation)
            _noncyclic(mapping)
            if (
                children != list(dict.fromkeys([*eqs, substitute(g, mapping)]))
                or not mapping
            ):
                raise ProofFailure("invalid_proof", "invalid simultaneous substitution")

    def check_sign(self, g, children, cert):
        if g[2] != ZERO or cert or any(c[2] != ZERO for c in children):
            raise ProofFailure("invalid_proof", "invalid sign rule")
        e, desired = g[1], SIGNS[g[0]]
        op = e[0]
        values = [SIGNS[c[0]] for c in children]
        if op == "neg" and len(children) == 1 and children[0][1] == e[1]:
            possible = {-x for x in values[0]}
        elif (
            op in {"add", "sub", "mul", "div"}
            and len(children) == 2
            and [c[1] for c in children] == list(e[1:])
        ):
            possible = set()
            for x in values[0]:
                for y in values[1]:
                    if op == "sub":
                        y = -y
                    if op in {"mul", "div"}:
                        if op == "div" and y == 0:
                            raise ProofFailure(
                                "invalid_proof",
                                "division sign needs nonzero denominator",
                            )
                        possible.add(x * y)
                    elif x == -y and x != 0:
                        possible.update({-1, 0, 1})
                    else:
                        possible.add((x + y > 0) - (x + y < 0))
        elif op == "pow":
            exponent = signed_integer(e[2])
            if exponent == 0 and not children:
                possible = {1}
            elif exponent % 2 == 0 and not children and exponent > 0:
                possible = {0, 1}
            elif len(children) == 1 and children[0][1] == e[1]:
                if exponent < 0 and 0 in values[0]:
                    raise ProofFailure("invalid_proof", "negative power at zero")
                possible = {abs(x) if exponent % 2 == 0 else x for x in values[0]}
            else:
                raise ProofFailure("invalid_proof", "power sign evidence mismatch")
        elif (
            op == "sqrt"
            and len(children) == 1
            and children[0][1] == e[1]
            and values[0] <= {0, 1}
        ):
            possible = values[0]
        else:
            raise ProofFailure("invalid_proof", "unsupported sign derivation")
        if not possible <= desired:
            raise ProofFailure("invalid_proof", "sign evidence is insufficient")

    def check_witness_node(self, node):
        # Implemented below: witness proofs use a checked child proof bundle per
        # simultaneous assignment, with its own replay under substituted context.
        if node.rule_id == "math.exists":
            if set(node.certificate) != {"selected_branch"}:
                raise ProofFailure("invalid_proof", "invalid existential certificate")
            selected = node.certificate.get("selected_branch")
            if type(selected) is not int or len(node.children) != 1:
                raise ProofFailure(
                    "invalid_proof", "explicit existential branch required"
                )
            child = self.by_id[node.children[0]]
            if (
                child.rule_id != "math.witness"
                or child.certificate["index"] != selected
                or node.conclusion != ("exists", selected)
            ):
                raise ProofFailure("invalid_proof", "existential witness mismatch")
            return
        if set(node.certificate) != {"index", "proof"}:
            raise ProofFailure("invalid_proof", "invalid witness certificate")
        index = node.certificate["index"]
        if node.children or node.conclusion != ("witness", index):
            raise ProofFailure("invalid_proof", "invalid witness root")
        child_context, expected_request = _witness_problem(self, index)
        bundle = node.certificate["proof"]
        if freeze_json(bundle["request"]) != freeze_json(expected_request):
            raise ProofFailure(
                "invalid_proof", "witness omitted or altered a requirement"
            )
        result = _replay(bundle, child_context, budget=self.witness_replay_budget)
        if result.status != "proved":
            raise ProofFailure(
                result.code or "invalid_proof",
                result.diagnostic or "witness replay failed",
            )

    def payload(self, roots):
        return {
            "schema_version": RULESET_VERSION,
            "ruleset_hash": RULESET_HASH,
            "context_hash": self.context_hash,
            "request": self.request,
            "sources": self.documents,
            "nodes": [n.to_payload() for n in self.nodes],
            "roots": list(roots),
        }


class _Search(_Environment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Child nodes were already charged while constructing their proofs.
        # Attachment still checks every certificate, with a separate validation
        # budget shared across branches. Independent replay uses one budget for
        # both parent and nested nodes through _Environment instead.
        self.witness_replay_budget = _Budget(self.budget.limits)
        self.cache, self.active = {}, set()

    def need(self, goal):
        if goal in self.cache:
            found = self.cache[goal]
            if found is None:
                raise ProofFailure(
                    "proof_missing", "no bounded proof for requested relation"
                )
            return found
        if goal in self.active:
            raise ProofFailure("proof_missing", "cyclic proof dependency")
        if len(self.active) >= self.budget.limits.depth:
            raise ProofFailure("proof_limit", "proof depth limit")
        self.budget.use("attempts")
        self.active.add(goal)
        try:
            guards = [self.need(d) for d in domains(goal)]
            core = self.core(goal)
            result = self.add("guard", goal, (core, *guards))
            self.cache[goal] = result
            return result
        except ProofFailure as exc:
            if exc.code == "proof_missing":
                # Failure through an active ancestor is context-dependent; do
                # not cache failures and suppress a later independent proof.
                pass
            raise
        finally:
            self.active.remove(goal)

    def attempt(self, function):
        self.budget.use("attempts")
        try:
            return function()
        except ProofFailure as exc:
            if exc.code != "proof_missing":
                raise
            return None

    def raw(self, rule, goal, required=(), cert=None):
        required = (
            tuple(required)
            if rule in {"sign", "scale", "equal_sign", "transitive"}
            else tuple(dict.fromkeys(required))
        )
        return self.add(rule, goal, tuple(self.need(g) for g in required), cert)

    def core(self, g):
        a = self.arithmetic
        for key, premise in self.premises.items():
            if premise == g:
                return self.add("given", g, certificate={"premise_id": key})
        if not names(g):
            sign, certificate = a.constant_certificate(_diff(g))
            if _holds(sign, g[0]):
                return self.add("constant", g, certificate=certificate)
            raise ProofFailure("proof_missing", "exact constant comparison is false")
        for premise in self.premises.values():
            ratio = a.proportional(_diff(g), _diff(premise))
            if (
                ratio
                and {x * (1 if ratio > 0 else -1) for x in SIGNS[premise[0]]}
                <= SIGNS[g[0]]
            ):
                found = self.attempt(
                    partial(self.raw, "weaken", g, [premise], {"ratio": str(ratio)})
                )
                if found:
                    return found
        ordered = _ordered(g)
        if ordered and all(e[0] in {"symbol", "rat"} for e in g[1:]):
            for premise in self.premises.values():
                first = _ordered(premise)
                if first and first[1] == ordered[1] and first[2] != ordered[2]:
                    second_op = ">=" if ordered[0] == ">=" or first[0] == ">" else ">"
                    found = self.attempt(
                        partial(
                            self.raw,
                            "transitive",
                            g,
                            [premise, (second_op, first[2], ordered[2])],
                        )
                    )
                    if found:
                        return found
        if g[0] == "!=":
            for strict in (">", "<"):
                found = self.attempt(
                    partial(
                        self.raw, "weaken", g, [(strict, g[1], g[2])], {"ratio": "1"}
                    )
                )
                if found:
                    return found
        if g[0] == "=":
            if (
                g[1][0] == "pow"
                and g[1][1][0] == "sqrt"
                and signed_integer(g[1][2]) == 2
                and g[2] == g[1][1][1]
            ):
                return self.raw("root_square", g, [(">=", g[2], ZERO)])
            found = self.attempt(partial(self.polynomial, g))
            if found:
                return found
            if (
                g[1] != ZERO
                and g[2] != ZERO
                and g[1][0] != "pow"
                and g[2][0] != "pow"
                and any(n[0] == "sqrt" for n in walk(g))
            ):
                required = [
                    (">=", g[1], ZERO),
                    (">=", g[2], ZERO),
                    ("=", ("pow", g[1], number(2)), ("pow", g[2], number(2))),
                ]
                found = self.attempt(partial(self.raw, "square_equal", g, required))
                if found:
                    return found
        if g[1][0] == g[2][0] == "sqrt":
            found = self.attempt(
                partial(self.raw, "monotone", g, [(g[0], g[1][1], g[2][1])])
            )
            if found:
                return found
        if g[1][:2] == g[2][:2] == ("div", ONE):
            required = [
                (">", g[1][2], ZERO),
                (">", g[2][2], ZERO),
                (REVERSE[g[0]], g[1][2], g[2][2]),
            ]
            found = self.attempt(partial(self.raw, "monotone", g, required))
            if found:
                return found
        if g[2] != ZERO:
            return self.raw("difference", g, [(g[0], _diff(g), ZERO)])
        if g[0] == "!=" and g[2] == ZERO:
            for premise in self.premises.values():
                for product in (premise[1], premise[2], _diff(premise)):
                    if product != g[1] and g[1] in _factors(product):
                        found = self.attempt(
                            partial(
                                self.raw, "factor_nonzero", g, [("!=", product, ZERO)]
                            )
                        )
                        if found:
                            return found
        # Exact polynomial multiples of a signed premise preserve or reverse
        # its sign only after the multiplier sign has itself been proved.
        for key, premise in self.premises.items():
            if premise[0] == "=":
                continue
            factor = a.factor(g[1], _diff(premise))
            if factor is None:
                continue
            for op in (">", "<", ">=", "<=", "!=", "="):
                possible = {x * y for x in SIGNS[premise[0]] for y in SIGNS[op]}
                if possible <= SIGNS[g[0]]:
                    found = self.attempt(
                        partial(self.raw, "scale", g, [premise, (op, factor, ZERO)])
                    )
                    if found:
                        return found
        found = self.attempt(partial(self.sign, g))
        if found:
            return found
        found = self.attempt(partial(self.interval, g))
        if found:
            return found
        # Transfer a known sign across an explicitly supplied equation.
        for premise in self.premises.values():
            if premise[0] == "=":
                for left, right in (premise[1:], premise[1:][::-1]):
                    if left == g[1] and right != left:
                        found = self.attempt(
                            partial(
                                self.raw,
                                "equal_sign",
                                g,
                                [("=", left, right), (g[0], right, ZERO)],
                            )
                        )
                        if found:
                            return found
        found = self.attempt(partial(self.substitution, g))
        if found:
            return found
        raise ProofFailure("proof_missing", "no registered rule proves the relation")

    def polynomial(self, g):
        a = self.arithmetic
        equations = [
            (key, p) for key, p in self.premises.items() if p[0] == "=" and p != g
        ]
        # First try an identity independent of premises; unused equations must
        # not create unnecessary domain or provenance dependencies.
        for selected in ([], equations):
            if len(selected) > self.budget.limits.equations:
                raise ProofFailure("proof_limit", "equation premise budget")
            roots = a.roots([g, *(p for _, p in selected)])
            divisors = [a.equation_divisor(p) for _, p in selected] + [
                a.root_polynomial(r) for r in roots.values()
            ]
            quotients, remainder = a.reduce(a.difference(g), divisors)
            if remainder:
                quotients = a.linear_combination(a.difference(g), divisors)
                if quotients is None:
                    continue
            used = [item for item, quotient in zip(selected, quotients) if quotient]
            if len(used) != len(selected):
                selected = used
                roots = a.roots([g, *(p for _, p in selected)])
                divisors = [a.equation_divisor(p) for _, p in selected] + [
                    a.root_polynomial(r) for r in roots.values()
                ]
                quotients, remainder = a.reduce(a.difference(g), divisors)
                if remainder:
                    quotients = a.linear_combination(a.difference(g), divisors)
                    if quotients is None:
                        continue
            required = [p for _, p in selected] + [
                claim for r in roots.values() for claim in _root_claims(r)
            ]
            cert = {
                "equations": [k for k, _ in selected],
                "roots": list(roots),
                "multipliers": [a.encode(q) for q in quotients],
            }
            return self.raw("polynomial", g, required, cert)
        raise ProofFailure("proof_missing", "polynomial remainder is nonzero")

    def sign(self, g):
        e, op = g[1], g[0]
        kind = e[0]
        if kind == "neg":
            return self.raw("sign", g, [(REVERSE[op], e[1], ZERO)])
        if kind == "pow":
            exponent = signed_integer(e[2])
            if exponent == 0 and 1 in SIGNS[op]:
                return self.raw("sign", g)
            if exponent > 0 and exponent % 2 == 0 and {0, 1} <= SIGNS[op]:
                return self.raw("sign", g)
            options = ["!=", "=", ">", "<", ">=", "<="] if exponent % 2 == 0 else [op]
            for required in options:
                possible = {abs(s) if exponent % 2 == 0 else s for s in SIGNS[required]}
                if possible <= SIGNS[op] and (
                    exponent >= 0 or 0 not in SIGNS[required]
                ):
                    found = self.attempt(
                        partial(self.raw, "sign", g, [(required, e[1], ZERO)])
                    )
                    if found:
                        return found
        if kind == "sqrt":
            required = op if op in {">", ">=", "="} else ">" if op == "!=" else "="
            if op != "<":
                return self.raw("sign", g, [(required, e[1], ZERO)])
        if kind in {"add", "sub", "mul", "div"}:
            # Short, deterministic sufficient sign combinations. Opposite sums
            # need an explicit relation/interval rule, never numerical probing.
            options = [
                (">", ">"),
                ("<", "<"),
                (">=", ">="),
                ("<=", "<="),
                (">", ">="),
                (">=", ">"),
                ("<", "<="),
                ("<=", "<"),
                (">", "<"),
                ("<", ">"),
                ("!=", "!="),
                ("=", "!="),
                ("=", "="),
                (">=", "<"),
                ("<=", ">"),
                (">", "<="),
                ("<", ">="),
            ]
            for x, y in options:
                children = [(x, e[1], ZERO), (y, e[2], ZERO)]
                try:
                    self.check_sign(g, children, {})
                except ProofFailure:
                    continue
                found = self.attempt(partial(self.raw, "sign", g, children))
                if found:
                    return found
        raise ProofFailure("proof_missing", "structural signs insufficient")

    def interval(self, g):
        if len(names(g)) != 1:
            raise ProofFailure("proof_missing", "no univariate interval")
        name = next(iter(names(g)))
        bounds = self.bounds()
        for lo in bounds.get((name, "lower"), []):
            for hi in bounds.get((name, "upper"), []):
                cert = self.interval_certificate(_diff(g), lo[1], hi[1])
                values = [Q(v) for v in cert["values"]]
                possible = (
                    {0}
                    if min(values) == max(values) == 0
                    else {1}
                    if min(values) > 0
                    else {-1}
                    if max(values) < 0
                    else {0, 1}
                    if min(values) >= 0
                    else {-1, 0}
                    if max(values) <= 0
                    else {-1, 0, 1}
                )
                if possible <= SIGNS[g[0]]:
                    return self.raw(
                        "interval",
                        g,
                        [self.premises[lo[1]], self.premises[hi[1]]],
                        cert,
                    )
        raise ProofFailure("proof_missing", "interval sign not established")

    def substitution(self, g):
        mapping, bindings, equations = {}, [], []
        for key, p in self.premises.items():
            if p[0] != "=":
                continue
            for side in (1, 2):
                if (
                    p[side][0] == "symbol"
                    and p[side][1] in names(g)
                    and p[side][1] not in names(p[3 - side])
                ):
                    name = p[side][1]
                    if name not in mapping:
                        mapping[name] = p[3 - side]
                        bindings.append({"premise_id": key, "side": side})
                        equations.append(p)
                    break
        if not mapping:
            raise ProofFailure("proof_missing", "no substitution")
        _noncyclic(mapping)
        return self.raw(
            "substitution",
            g,
            [*equations, substitute(g, mapping)],
            {"bindings": bindings},
        )


def _text(e):
    if e[0] == "rat":
        q = rat(e)
        return (
            str(q.numerator)
            if q.denominator == 1
            else f"({q.numerator}/{q.denominator})"
        )
    if e[0] == "symbol":
        return e[1]
    if e[0] == "neg":
        return f"(-{_text(e[1])})"
    if e[0] == "sqrt":
        return f"sqrt({_text(e[1])})"
    op = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^"}.get(e[0], e[0])
    return f"({_text(e[1])}{op}{_text(e[2])})"


def freeze_json(value):
    return json.loads(json.dumps(value, sort_keys=True))


def _validate_expression(e, symbols, budget, depth=0, relation=False):
    if depth > budget.limits.depth or not isinstance(e, tuple) or not e:
        raise ProofFailure("proof_limit", "derived expression depth limit")
    op = e[0]
    if relation:
        if not _relation(e):
            raise ProofFailure("invalid_proof", "relation required")
        return 1 + sum(
            _validate_expression(x, symbols, budget, depth + 1) for x in e[1:]
        )
    if op == "rat":
        if len(e) != 3 or any(
            not isinstance(x, str) or len(x) > budget.limits.coefficient_bits
            for x in e[1:]
        ):
            raise ProofFailure("invalid_proof", "invalid rational")
        Arithmetic(budget).check_q(rat(e))
        return 1
    if op == "symbol":
        if len(e) != 2 or e[1] not in symbols:
            raise ProofFailure("invalid_proof", "unknown derived symbol")
        return 1
    arity = {"neg": 1, "sqrt": 1, "add": 2, "sub": 2, "mul": 2, "div": 2, "pow": 2}.get(
        op
    )
    if arity is None or len(e) != arity + 1:
        raise ProofFailure("invalid_proof", "invalid scalar node")
    if op == "pow" and (signed_integer(e[2]) is None or abs(signed_integer(e[2])) > 12):
        raise ProofFailure("proof_limit", "derived power limit")
    count = 1 + sum(_validate_expression(x, symbols, budget, depth + 1) for x in e[1:])
    if count > 256:
        raise ProofFailure("proof_limit", "derived node limit")
    return count


def _derived_source(doc, symbols, budget, *, relation):
    # Simultaneous substitution is composed over validated ASTs. Re-parsing
    # would reject safe nested powers created by substitution (e.g. q17).
    if set(doc) != {"source", "expression", "source_path", "step"}:
        raise ProofFailure("invalid_proof", "invalid derived source")
    e = freeze(doc["expression"])
    _validate_expression(e, symbols, budget, relation=relation)
    if doc["source"] != _text(e) or len(doc["source"]) > 1024:
        raise ProofFailure("invalid_proof", "derived source mismatch")

    def node(value, offset=0, path="n"):
        text = _text(value)
        op = value[0]
        if op in {"rat", "symbol"}:
            return MathNode(
                op,
                (offset, offset + len(text)),
                text=str(rat(value)) if op == "rat" else value[1],
                path=path,
            )
        begin = offset + (5 if op == "sqrt" else 2 if op == "neg" else 1)
        left = node(value[1], begin, path + ".0")
        children = [left]
        if len(value) == 3:
            separator = {
                "add": "+",
                "sub": "-",
                "mul": "*",
                "div": "/",
                "pow": "^",
            }.get(op, op)
            children.append(node(value[2], left.span[1] + len(separator), path + ".1"))
        return MathNode(op, (offset, offset + len(text)), tuple(children), path=path)

    tree = node(e)
    return ParsedMath(
        doc["source"],
        doc["source"],
        tuple((i, i + 1) for i in range(len(doc["source"]))),
        tree,
        tree,
        (),
        doc["source_path"],
    )


def _witness_problem(env, index):
    request = env.request
    if type(index) is not int or not 0 <= index < len(request["witnesses"]):
        raise ProofFailure("invalid_proof", "invalid witness index")
    witness = request["witnesses"][index]
    if set(witness["assignments"]) != set(env.symbols):
        raise ProofFailure("invalid_input", "assign every original variable explicitly")
    mapping = {
        name: from_node(env.sources[f"assignment:{index}:{name}"].ast)
        for name in witness["assignments"]
    }
    _noncyclic(mapping)
    parameter, interval = witness["parameter"], witness["interval"]
    symbols, premises = {}, {}
    if parameter is None:
        if interval is not None or any(names(e) for e in mapping.values()):
            raise ProofFailure(
                "invalid_input", "finite witness must be a constant assignment"
            )
    else:
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ProofFailure("invalid_input", "closed rational interval required")
        if any(
            type(x) not in (str, int)
            or len(str(x)) > env.budget.limits.coefficient_bits
            for x in interval
        ):
            raise ProofFailure("proof_limit", "interval coefficient size limit")
        lo, hi = (Q(x) for x in interval)
        for bound in (lo, hi):
            env.arithmetic.check_q(bound)
        if lo > hi:
            raise ProofFailure(
                "inconsistent_premises", "empty witness parameter interval"
            )
        if any(names(e) - {parameter} for e in mapping.values()):
            raise ProofFailure(
                "invalid_input",
                "simultaneous parameterization leaves unresolved variables",
            )
        if request["require_parameterized"]:
            targets = [
                from_node(env.sources[f"requirement:{i}"].ast)
                for i in range(len(request["requirements"]))
            ]
            if not any(
                g[0] == "="
                and (
                    (g[1] == ("symbol", parameter) and parameter not in names(g[2]))
                    or (g[2] == ("symbol", parameter) and parameter not in names(g[1]))
                )
                for g in targets
            ):
                raise ProofFailure(
                    "proof_missing",
                    "range attainment needs an explicit target=parameter requirement",
                )
        symbols[parameter] = sp.Symbol(parameter, real=True)
        premises = {
            "parameter_lower": parse_math_relation(
                f"{parameter}>={_text(number(lo))}", symbols
            ),
            "parameter_upper": parse_math_relation(
                f"{parameter}<={_text(number(hi))}", symbols
            ),
        }
    relations = []
    for g in env.premises.values():
        relations.append(
            {
                "source": _text(substitute(g, mapping)),
                "expression": substitute(g, mapping),
                "source_path": None,
                "step": None,
            }
        )
    for i in range(len(request["requirements"])):
        g = from_node(env.sources[f"requirement:{i}"].ast)
        relations.append(
            {
                "source": _text(substitute(g, mapping)),
                "expression": substitute(g, mapping),
                "source_path": None,
                "step": None,
            }
        )
    expressions = [
        {"source": _text(e), "expression": e, "source_path": None, "step": None}
        for name, e in sorted(mapping.items())
    ]
    return ProofContext(
        symbols, premises, env.budget.limits, f"{env.scope_id}/witness/{index}"
    ), {
        "kind": "bundle",
        "relations": relations,
        "expressions": expressions,
    }


def _roots_for_request(env):
    kind = env.request["kind"]
    if kind == "relation":
        return (from_node(env.sources["candidate"].ast),)
    if kind == "domain":
        return (("all", *domains(from_node(env.sources["candidate"].ast))),)
    if kind == "bundle":
        goals = []
        for key, parsed in env.sources.items():
            if key.startswith("bundle_relation:"):
                goals.append(from_node(parsed.ast))
            elif key.startswith("bundle_expression:"):
                goals.extend(domains(from_node(parsed.ast)))
        return (("all", *dict.fromkeys(goals)),)
    mode = env.request["mode"]
    if mode == "exists":
        return (("exists", env.request["selected_branch"]),)
    return tuple(("witness", i) for i in range(len(env.request["witnesses"])))


def _run_request(context, request, *, budget=None):
    env = _Search(context, request, budget=budget)
    goals = _roots_for_request(env)
    roots = []
    for g in goals:
        if g[0] == "all":
            roots.append(env.add("all", g, tuple(env.need(h) for h in g[1:])))
        else:
            roots.append(env.need(g))
    return ProofResult("proved", proof=env.payload(roots))


def prove_relation(candidate: ParsedMath, context: ProofContext) -> ProofResult:
    try:
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        _checked(candidate, context.symbols)
        return _run_request(
            context, {"kind": "relation", "candidate": _document(candidate)}
        )
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        return _failure(exc)


def prove_domain(expression: ParsedMath, context: ProofContext) -> ProofResult:
    try:
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        _checked(expression, context.symbols, relation=False)
        return _run_request(
            context, {"kind": "domain", "candidate": _document(expression)}
        )
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        return _failure(exc)


def verify_witnesses(
    assignments: Sequence[Witness | Mapping[str, ParsedMath]],
    requirements: Sequence[ParsedMath],
    context: ProofContext,
    *,
    mode="all",
    selected_branch=None,
    require_parameterized=False,
) -> ProofResult:
    """Verify every submitted branch, or one explicitly selected existential one.

    ``require_parameterized`` is the range-attainment gate: endpoints cannot
    satisfy it. Completeness of all solutions is never claimed by this API.
    """
    reports = []
    try:
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        if (
            not 1 <= len(assignments) <= context.limits.branches
            or not requirements
            or len(requirements) > 16
        ):
            raise ProofFailure("proof_limit", "witness/requirement count limit")
        if (
            mode not in {"all", "exists"}
            or (
                mode == "exists"
                and (
                    type(selected_branch) is not int
                    or not 0 <= selected_branch < len(assignments)
                )
            )
            or (mode == "all" and selected_branch is not None)
        ):
            raise ProofFailure(
                "invalid_input", "explicit valid witness selection required"
            )
        witnesses = []
        for item in assignments:
            item = Witness(item) if isinstance(item, Mapping) else item
            if not isinstance(item, Witness):
                raise ProofFailure("invalid_input", "Witness required")
            if require_parameterized and item.parameter is None:
                raise ProofFailure(
                    "proof_missing",
                    "endpoint witnesses do not prove an entire interval",
                )
            witnesses.append(
                {
                    "assignments": {
                        k: _document(v) for k, v in sorted(item.assignments.items())
                    },
                    "parameter": item.parameter,
                    "interval": item.interval,
                }
            )
        for requirement in requirements:
            _checked(
                requirement,
                {
                    **context.symbols,
                    **{
                        w["parameter"]: sp.Symbol(w["parameter"], real=True)
                        for w in witnesses
                        if w["parameter"] is not None
                    },
                },
            )
        request = {
            "kind": "witness",
            "witnesses": witnesses,
            "requirements": [_document(r) for r in requirements],
            "mode": mode,
            "selected_branch": selected_branch,
            "require_parameterized": require_parameterized,
        }
        env = _Search(context, request)
        roots = []
        indices = range(len(witnesses)) if mode == "all" else [selected_branch]
        for i in indices:
            try:
                child_context, child_request = _witness_problem(env, i)
                result = _run_request(child_context, child_request, budget=env.budget)
                child = env.add(
                    "witness",
                    ("witness", i),
                    certificate={"index": i, "proof": result.proof},
                )
                root = (
                    env.add("exists", ("exists", i), [child], {"selected_branch": i})
                    if mode == "exists"
                    else child
                )
                roots.append(root)
                reports.append({"index": i, "status": "proved"})
            except (ProofFailure, MathParseError) as exc:
                reports.append(
                    {
                        "index": i,
                        "status": "not_proved",
                        "code": getattr(exc, "code", "invalid_input"),
                        "diagnostic": str(exc),
                    }
                )
                if isinstance(exc, ProofFailure) and exc.code == "proof_limit":
                    # Shared budget is exhausted; retain an explicit result for
                    # every remaining branch without resetting it.
                    for remaining in indices:
                        if remaining > i:
                            reports.append(
                                {
                                    "index": remaining,
                                    "status": "not_proved",
                                    "code": "proof_limit",
                                }
                            )
                    break
        if any(r["status"] != "proved" for r in reports):
            first = next(r for r in reports if r["status"] != "proved")
            return ProofResult(
                "not_proved",
                first["code"],
                "one or more submitted witnesses failed",
                branches=tuple(reports),
            )
        return ProofResult("proved", proof=env.payload(roots), branches=tuple(reports))
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        return _failure(exc, tuple(reports))


def _payload_depth(proof):
    depths = {}
    for node in proof["nodes"]:
        depth = 1 + max((depths[c] for c in node["children"]), default=0)
        if node["rule_id"] == "math.witness":
            depth = max(depth, 1 + _payload_depth(node["certificate"]["proof"]))
        depths[node["node_id"]] = depth
    return max((depths[r] for r in proof["roots"]), default=0)


def _replay(proof, context, *, budget=None):
    env = _Environment(context, proof["request"], budget=budget)
    if (
        set(proof)
        != {
            "schema_version",
            "ruleset_hash",
            "context_hash",
            "request",
            "sources",
            "nodes",
            "roots",
        }
        or proof["schema_version"] != RULESET_VERSION
        or proof["ruleset_hash"] != RULESET_HASH
        or proof["context_hash"] != env.context_hash
    ):
        raise ProofFailure("invalid_proof", "proof context or ruleset mismatch")
    if freeze_json(proof["sources"]) != freeze_json(env.documents):
        raise ProofFailure("invalid_proof", "proof source documents changed")
    for i, record in enumerate(proof["nodes"]):
        env.budget.use("nodes")
        if set(record) != {
            "node_id",
            "rule_id",
            "conclusion",
            "children",
            "premises",
            "input_nodes",
            "certificate",
        }:
            raise ProofFailure("invalid_proof", "invalid proof node shape")
        node = ProofNode(
            record["node_id"],
            record["rule_id"],
            freeze(record["conclusion"]),
            tuple(record["children"]),
            tuple(record["premises"]),
            tuple(record["input_nodes"]),
            record["certificate"],
        )
        if node.node_id != f"p{i:04d}":
            raise ProofFailure("invalid_proof", "unstable or duplicate node ID")
        env.check_node(node)
        env.check_depth(node)
        env.nodes.append(node)
        env.by_id[node.node_id] = node
    goals = _roots_for_request(env)
    actual = tuple(env.by_id[k].conclusion for k in proof["roots"])
    if actual != goals or len(proof["roots"]) != len(set(proof["roots"])):
        raise ProofFailure("invalid_proof", "proof roots do not match the request")
    for root, goal in zip(proof["roots"], goals, strict=True):
        if _relation(goal):
            env.guarded(root, goal)
        elif env.by_id[root].rule_id != "math." + goal[0]:
            raise ProofFailure("invalid_proof", "unverified proof root")
    return ProofResult("proved", proof=proof)


def replay_proof(proof: dict | ProofResult, context: ProofContext) -> ProofResult:
    try:
        if isinstance(proof, ProofResult):
            proof = proof.proof
        return _replay(proof, context)
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        if isinstance(exc, ProofFailure) and exc.code in {
            "proof_limit",
            "inconsistent_premises",
        }:
            return _failure(exc)
        return ProofResult("not_proved", "invalid_proof", str(exc))
