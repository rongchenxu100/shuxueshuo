"""Deterministic local proof checker and legacy certificate replay (no search).

Premises are explicitly supplied by the caller. A successful conditional proof
never asserts feasibility, complete solution enumeration, or execution authority.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from fractions import Fraction as Q
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
    commutative_key,
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
)
from .proof_rule_registry import RulePackage, RuleRegistry
from .proof_types import (
    ProofContext,
    ProofNode,
    ProofResult,
    _Budget,
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
    "two_term_amgm",
    "fixed_sum_product_bound",
    "relation_transport",
    "amgm_squared_bound",
    "local_two_term_amgm",
    "equality_bound_transport",
    "two_term_product_bound",
)


RULESET_VERSION = "bounded-real-proof/v1"


RULESET_HASH = digest(
    {
        "version": RULESET_VERSION,
        "rules": RULES,
        "rule_revisions": {"two_term_amgm": 2, "transitive": 2, "polynomial": 2},
    }
)


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


def fact_key(relation):
    """Structural fact identity; never cancel expressions or domains."""
    op, left, right = relation
    if op in {"<", "<="}:
        op, left, right = REVERSE[op], right, left
    if op in {"=", "!="} and repr(left) > repr(right):
        left, right = right, left
    return op, left, right


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


def _cancel_additive(node):
    """Propose cancellation of identical signed addends, without expansion."""
    positive, negative = [], []

    def collect(item, sign=1):
        if item[0] in {"add", "sub"}:
            collect(item[1], sign)
            collect(item[2], -sign if item[0] == "sub" else sign)
        elif item[0] == "neg":
            collect(item[1], -sign)
        else:
            (positive if sign == 1 else negative).append(item)

    collect(node)
    changed = False
    for item in positive[:]:
        if item in negative:
            positive.remove(item)
            negative.remove(item)
            changed = True
    if not changed:
        return node
    result = ZERO
    for item in positive:
        result = item if result == ZERO else expr("add", result, item)
    for item in negative:
        result = expr("sub", result, item)
    return result


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
            or len(context.premises) > 256
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
        # Keep every source ID for old certificates and diagnostic provenance;
        # capacity counts distinct, structurally normalized facts only.
        self.fact_sources = {}
        for key, relation in self.premises.items():
            self.fact_sources.setdefault(fact_key(relation), []).append(key)
        if len(self.fact_sources) > context.limits.premises:
            raise ProofFailure("proof_limit", "context size limit")
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
        self.node_keys, self.interned_nodes = {}, {}
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
        key = self.node_key(node)
        if key in self.interned_nodes:
            return self.interned_nodes[key]
        self.charge_node(node, key)
        self.nodes.append(node)
        self.by_id[node.node_id] = node
        return node.node_id

    def node_key(self, node):
        return digest((RULESET_HASH, self.context_hash, node.rule_id,
                       node.conclusion, node.certificate,
                       [self.node_keys[c] for c in node.children]))

    def charge_node(self, node, key):
        if key not in self.budget.proof_nodes:
            self.budget.use("nodes")
            self.budget.proof_nodes.add(key)
        self.node_keys[node.node_id] = key
        self.interned_nodes.setdefault(key, node.node_id)

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
        elif rule in {
            "two_term_amgm",
            "fixed_sum_product_bound",
            "two_term_product_bound",
        }:
            required = self.amgm_requirements(rule, g, cert)
            if children != list(dict.fromkeys(required)):
                raise ProofFailure("invalid_proof", "AM-GM premises missing")
        elif rule == "local_two_term_amgm":
            if set(cert) != {"u", "v", "rest", "scale"} or g[0] != ">=":
                raise ProofFailure("invalid_proof", "invalid local AM-GM certificate")
            u, v, rest, scale = (freeze(cert[k]) for k in ("u", "v", "rest", "scale"))
            required = self.local_amgm_requirements(g, u, v, rest, scale)
            if children != list(dict.fromkeys(required)):
                raise ProofFailure(
                    "invalid_proof", "local AM-GM guards or transport missing"
                )
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
                a.difference(("=", first[1], target[1]))
                or a.difference(("=", first[2], second[1]))
                or a.difference(("=", second[2], target[2]))
                or (target[0] == ">" and first[0] == second[0] == ">=")
            ):
                raise ProofFailure("invalid_proof", "invalid order transitivity")
        elif rule == "equality_bound_transport":
            if len(children) != 2 or cert or not _ordered(g):
                raise ProofFailure(
                    "invalid_proof", "equality bound transport requires two premises"
                )
            equality, bound = children
            target, ordered = _ordered(g), _ordered(bound)
            if (
                equality[0] != "="
                or not ordered
                or target[0] != ordered[0]
                or a.difference(("=", target[2], ordered[2]))
            ):
                raise ProofFailure(
                    "invalid_proof", "bound transport direction or endpoint changed"
                )
            if not any(
                not a.difference(("=", target[1], left))
                and not a.difference(("=", ordered[1], right))
                for left, right in (equality[1:], equality[1:][::-1])
            ):
                raise ProofFailure("invalid_proof", "bound transport equality changed")
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
        elif rule == "relation_transport":
            if len(children) != 2 or set(cert) != {"ratio"}:
                raise ProofFailure(
                    "invalid_proof", "signed relation and equality required"
                )
            premise, equality = children
            ratio = Q(cert["ratio"])
            expected = ("=", _diff(g), expr("mul", number(ratio), _diff(premise)))
            possible = {s * (1 if ratio > 0 else -1) for s in SIGNS[premise[0]]}
            if not ratio or equality != expected or not possible <= SIGNS[g[0]]:
                raise ProofFailure("invalid_proof", "invalid relation transport")
        elif rule == "amgm_squared_bound":
            premise = self.premises.get(cert.get("amgm_premise"))
            if set(cert) != {"amgm_premise"} or premise is None:
                raise ProofFailure("invalid_proof", "AM-GM source required")
            required = self.amgm_requirements("two_term_amgm", premise, {})
            u, v = premise[1][1:]
            rhs = expr("div", expr("pow", expr("add", u, v), number(2)), number(4))
            if (
                g[0] != "<="
                or a.difference(("=", g[1], expr("mul", u, v)))
                or a.difference(("=", g[2], rhs))
                or children != list(dict.fromkeys([premise, *required]))
            ):
                raise ProofFailure("invalid_proof", "invalid squared AM-GM bound")
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

    def amgm_requirements(self, rule, g, cert):
        """Two positive terms; fixed-sum corollary keeps the target separate."""
        a = self.arithmetic
        if rule == "two_term_product_bound":
            if cert or g[0] != "<=" or g[1][0] != "mul":
                raise ProofFailure(
                    "invalid_proof", "two-term product template mismatch"
                )
            u, v = g[1][1:]
            total = expr("add", u, v)
            expected = expr("div", expr("pow", total, number(2)), number(4))
            if a.difference(("=", g[2], expected)):
                raise ProofFailure("invalid_proof", "product mean-square mismatch")
            return (
                (">", u, ZERO),
                (">", v, ZERO),
                (">=", total, expr("mul", number(2), ("sqrt", expr("mul", u, v)))),
            )
        if rule == "two_term_amgm":
            if cert or g[0] != ">=" or g[1][0] != "add":
                raise ProofFailure("invalid_proof", "AM-GM template mismatch")
            u, v = g[1][1:]
            expected = ("mul", number(2), ("sqrt", ("mul", u, v)))
            if a.difference(("=", commutative_key(g[2]), commutative_key(expected))):
                raise ProofFailure("invalid_proof", "AM-GM right side mismatch")
            return ((">", u, ZERO), (">", v, ZERO))
        if set(cert) != {"sum_premise"} or g[0] != "<=":
            raise ProofFailure("invalid_proof", "product-bound certificate mismatch")
        premise = self.premises[cert["sum_premise"]]
        if premise[0] != "=":
            raise ProofFailure("invalid_proof", "sum equality required")
        total, value = premise[1:]
        if total[0] != "add":
            total, value = value, total
        if total[0] != "add" or a.literal_rational(value) is None:
            raise ProofFailure("invalid_proof", "two-term fixed rational sum required")
        u, v = total[1:]
        expected = ("div", ("pow", value, number(2)), number(4))
        if a.difference(("=", g[1], ("mul", u, v))) or a.difference(
            ("=", g[2], expected)
        ):
            raise ProofFailure("invalid_proof", "target or bound does not match AM-GM")
        return (
            premise,
            (">", u, ZERO),
            (">", v, ZERO),
            (">", value, ZERO),
            (">=", total, ("mul", number(2), ("sqrt", ("mul", u, v)))),
        )

    def local_amgm_requirements(self, g, u, v, rest, scale):
        total = expr("add", u, v)
        lower = expr("mul", number(2), ("sqrt", expr("mul", u, v)))
        reduced = expr("sub", expr("div", g[2], scale), rest)
        numerator, denominator = self.arithmetic.rational(reduced)
        roots = self.arithmetic.roots([reduced])
        normal = expr(
            "div",
            self.arithmetic.expression(numerator, roots),
            self.arithmetic.expression(denominator, roots),
        )
        return (
            (">", scale, ZERO),
            (">=", total, lower),
            ("=", g[1], expr("mul", scale, expr("add", rest, total))),
            ("=", reduced, normal),
            (">=", normal, ZERO),
            (
                "=",
                expr("pow", reduced, number(2)),
                expr("mul", number(4), expr("mul", u, v)),
            ),
        )

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
        # Legacy witness children belong to the same v1 rule package. A
        # registered extension cannot replace this nested mathematical contract.
        result = _replay_legacy(bundle, child_context, budget=self.witness_replay_budget)
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


def _payload_depth(proof):
    depths = {}
    for node in proof["nodes"]:
        depth = 1 + max((depths[c] for c in node["children"]), default=0)
        if node["rule_id"] == "math.witness":
            depth = max(depth, 1 + _payload_depth(node["certificate"]["proof"]))
        depths[node["node_id"]] = depth
    return max((depths[r] for r in proof["roots"]), default=0)


def _replay_legacy(proof, context, *, budget=None):
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
    if len(proof["nodes"]) > env.budget.limits.nodes:
        raise ProofFailure("proof_limit", "certificate node count limit")
    for i, record in enumerate(proof["nodes"]):
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
        env.charge_node(node, env.node_key(node))
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


LEGACY_RULE_PACKAGE = RulePackage(
    RULESET_VERSION, RULESET_HASH, tuple("math." + rule for rule in RULES), _replay_legacy
)
DEFAULT_RULE_REGISTRY = RuleRegistry((LEGACY_RULE_PACKAGE,))


def _replay(proof, context, *, budget=None, registry=None):
    if not isinstance(context, ProofContext):
        raise ProofFailure("invalid_input", "ProofContext required")
    selected = DEFAULT_RULE_REGISTRY if registry is None else registry
    if not isinstance(selected, RuleRegistry):
        raise ProofFailure("invalid_input", "RuleRegistry required")
    return selected.replay(proof, context, budget=budget)


def replay_proof(proof: dict | ProofResult, context: ProofContext, *, registry=None) -> ProofResult:
    try:
        if isinstance(proof, ProofResult):
            proof = proof.proof
        return _replay(proof, context, registry=registry)
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


