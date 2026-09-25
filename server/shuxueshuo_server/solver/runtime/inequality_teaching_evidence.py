"""Public mathematical projection of successful inequality Method execution.

Certificates remain in the runtime audit. This adapter reads verified ASTs;
it neither searches for a proof nor solves an equality condition.
"""

import hashlib
import json
from dataclasses import dataclass

import sympy as sp

from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.expression_parser import (
    parse_math_expression,
    parse_math_relation,
)
from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    _legacy_tree,
    tree_latex,
)
from shuxueshuo_server.solver.student_display import student_math_display

CONTRACT = "inequality-teaching-evidence/v1"
METHODS = {"apply_two_term_amgm", "close_equality_and_restore"}


def inequality_teaching_evidence_schema():
    return {
        "title": "InequalityTeachingEvidence",
        "type": "object",
        "required": ["schema_version", "step_id", "method_id", "data", "evidence_id"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": CONTRACT},
            "step_id": {"type": "string", "minLength": 1},
            "method_id": {"enum": sorted(METHODS)},
            "data": {"type": "object"},
            "evidence_id": {"type": "string", "minLength": 1},
        },
    }


@dataclass(frozen=True)
class InequalityTeachingEvidence:
    step_id: str
    method_id: str
    data_json: str

    def __post_init__(self):
        if not self.step_id or self.method_id not in METHODS:
            raise ValueError("invalid inequality teaching evidence identity")
        data = json.loads(self.data_json)
        required = {
            "target",
            "conditions",
            "terms",
            "derivation",
            "bound",
            "equality",
            "origins",
        }
        if (
            not required <= data.keys()
            or len(data["terms"]) != 2
            or not data["derivation"]
        ):
            raise ValueError("incomplete inequality teaching evidence")

    @property
    def data(self):
        return json.loads(self.data_json)

    @property
    def evidence_id(self):
        return (
            "inequality:"
            + hashlib.sha256(
                json.dumps(
                    self.to_payload(include_id=False),
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
        )

    def to_payload(self, *, include_id=True):
        value = {
            "schema_version": CONTRACT,
            "step_id": self.step_id,
            "method_id": self.method_id,
            "data": self.data,
        }
        if include_id:
            value["evidence_id"] = self.evidence_id
        return value

    def authority_payload(self):
        return self.to_payload()

    @property
    def schema_version(self):
        return CONTRACT

    @classmethod
    def from_payload(cls, raw):
        if (
            set(raw)
            != {"schema_version", "step_id", "method_id", "data", "evidence_id"}
            or raw["schema_version"] != CONTRACT
        ):
            raise ValueError("invalid inequality teaching evidence payload")
        item = cls(
            raw["step_id"],
            raw["method_id"],
            json.dumps(raw["data"], ensure_ascii=False, sort_keys=True),
        )
        if item.evidence_id != raw["evidence_id"]:
            raise ValueError("inequality teaching evidence hash drift")
        return item


def collect_inequality_evidence(step_id, method_results):
    from .rewrite_teaching_evidence import collect_rewrite_evidence

    result = list(collect_rewrite_evidence(step_id, method_results))
    for method in method_results:
        if method.method_id not in METHODS:
            continue
        fragments = method.trace_fragments
        if len(fragments) != 1:
            raise ValueError("inequality teaching evidence missing")
        fragment = fragments[0]
        target, evidence = fragment["source_target"], fragment["evidence"]
        bound = (
            evidence if method.method_id == "apply_two_term_amgm" else evidence["bound"]
        )
        symbols = {
            name: sp.Symbol(name, real=True) for name in target["scalar_symbols"]
        }

        def scalar(source, symbols=symbols):
            return parse_math_expression(source, symbols).to_sympy(symbols)

        def display(source):
            return student_math_display(scalar(source))

        def relation(parsed):
            left, right = parsed.ast.children
            a = scalar(parsed.source[left.span[0] : left.span[1]])
            b = scalar(parsed.source[right.span[0] : right.span[1]])
            op = {">=": "≥", "<=": "≤", "!=": "≠"}.get(parsed.ast.op, parsed.ast.op)
            return f"{student_math_display(a)} {op} {student_math_display(b)}"

        chain = parse_derivation(bound["steps"], symbols)
        # The verified equality identifies the actual AM-GM pair selected by M11.
        # Do not choose an arbitrary sum/root relation from the submitted chain.
        equality = parse_math_relation(bound["equality"], symbols)
        terms = [
            scalar(equality.source[n.span[0] : n.span[1]])
            for n in equality.ast.children
        ]
        conditions = [
            parse_math_relation(item["math"], symbols)
            for item in target["source_conditions"]
        ]

        def relation_latex(parsed):
            left, right = parsed.ast.children
            return (
                tree_latex(_legacy_tree(left))
                + {">=": r"\geq ", "<=": r"\leq ", "!=": r"\ne "}.get(
                    parsed.ast.op, parsed.ast.op
                )
                + tree_latex(_legacy_tree(right))
            )

        fixed = None
        fixed_value = None
        for condition in conditions:
            if condition.ast.op != "=":
                continue
            a, b = (
                scalar(condition.source[n.span[0] : n.span[1]])
                for n in condition.ast.children
            )
            if (
                a == sum(terms)
                and not b.free_symbols
                or b == sum(terms)
                and not a.free_symbols
            ):
                fixed = condition
                fixed_value = b if a == sum(terms) else a
                break
        if fixed is None or bound.get("direction") == ">=":
            from ..explanation.bound_purpose import verified_bound_effect
            from ..math_kernel.inequality_bound_v2 import math_text
            from ..math_kernel.proof_algebra import freeze

            local_relations = []
            for row, proof in zip(chain, bound["derivation"]["proofs"], strict=True):
                for node in proof["nodes"]:
                    if node["rule_id"] == "math.two_term_amgm":
                        local_relations.append(
                            {
                                "math": relation(
                                    parse_math_relation(
                                        math_text(freeze(node["conclusion"])), symbols
                                    )
                                ),
                                "origins": [row.origin],
                            }
                        )
            term_latex = [tree_latex(_legacy_tree(n)) for n in equality.ast.children]
            # Keep each complete participating term grouped, especially a sum
            # used as a factor. Display projection must not change precedence.
            grouped = [
                r"\left(" + text + r"\right)" if n.op in {"add", "sub"} else text
                for text, n in zip(term_latex, equality.ast.children, strict=True)
            ]
            sum_latex = "+".join(grouped)
            product_latex = r"\cdot ".join(grouped)
            data = {
                "teaching_effect": verified_bound_effect(bound["source_math"], bound["bound"], symbols),
                "source_expression": student_math_display(bound["source_math"]),
                "target_hash": bound["target_hash"],
                "target": student_math_display(target["target_math"]),
                "conditions": [relation(c) for c in conditions],
                "condition_equations_latex": [
                    relation_latex(c) for c in conditions if c.ast.op == "="
                ],
                "terms": [
                    student_math_display(equality.source[slice(*n.span)])
                    for n in equality.ast.children
                ],
                "term_latex": term_latex,
                # Both terms and their domains were proved in this successful M11.
                # Rational cancellation here only projects their constant product.
                "constant_product_latex": (
                    sp.latex(sp.cancel(terms[0] * terms[1]))
                    if sp.cancel(terms[0] * terms[1]).is_Rational
                    else None
                ),
                "template_latex": sum_latex + r"\geq 2\sqrt{" + product_latex + "}",
                "fixed_condition": None,
                "derivation": [relation(r.parsed) for r in chain],
                "bound": display(bound["bound"]),
                "equality": relation(equality),
                "origins": [r.origin for r in chain],
                "direction": bound["direction"],
                "applications": bound["applications"],
                "equalities": [
                    relation(parse_math_relation(v, symbols))
                    for v in bound["equalities"]
                ],
                "local_relations": local_relations,
                "overall_relation": (
                    student_math_display(target["target_math"])
                    + (" ≥ " if bound["direction"] == ">=" else " ≤ ")
                    + display(bound["bound"])
                ),
                "previous_bound": (
                    {
                        k: bound["previous_bound"][k]
                        if k == "direction"
                        else display(bound["previous_bound"][k])
                        for k in ("source_math", "bound", "direction")
                    }
                    if bound["previous_bound"]
                    else None
                ),
            }
            # Semantic stages of this certified local application. The numerical
            # simplifications below project its proved positive terms and domain;
            # the original-target transport was already certified by M11/M01.
            product = sp.cancel(terms[0] * terms[1])
            data["paired_product_latex"] = sp.latex(product)
            rest = sp.cancel(scalar(bound["source_math"]) - sum(terms))
            local_value = 2 * sp.sqrt(product)
            if (
                product.is_Rational
                and product > 0
                and rest.is_Rational
                and sp.simplify(rest + local_value - scalar(bound["bound"])) == 0
            ):
                data["constant_product_roles"] = {
                    "product": sp.latex(product),
                    "product_identity": product_latex + "=" + sp.latex(product),
                    "local_bound": sum_latex + r"\geq " + sp.latex(local_value),
                    "target_substitution": (
                        sp.latex(scalar(target["target_math"]))
                        + r"\geq "
                        + sp.latex(rest)
                        + "+"
                        + sp.latex(local_value)
                    )
                    if rest != 0
                    else None,
                    "origins": [r.origin for r in chain],
                    "basis": "verified_local_amgm_and_target_transport",
                }
            if method.method_id == "close_equality_and_restore":
                data.update(
                    witness={k: display(v) for k, v in evidence["assignments"].items()},
                    witness_derivation=[
                        relation(r.parsed)
                        for r in parse_derivation(evidence["steps"], symbols)
                    ],
                    verified_branches=[
                        {
                            "assignments": {
                                k: display(v) for k, v in b["assignments"].items()
                            },
                            "relations": [
                                relation(r.parsed)
                                for r in parse_derivation(b["steps"], symbols)
                            ],
                            "when": relation_latex(
                                parse_math_relation(b["when"], symbols)
                            )
                            if b.get("when")
                            else None,
                            "equality_derivation": [
                                {
                                    "math": relation_latex(
                                        parse_math_relation(r["math"], symbols)
                                    ),
                                    "source_path": r["source_path"],
                                }
                                for r in b.get("equality_derivation", [])
                            ],
                        }
                        for b in evidence["branches"]
                    ],
                    branches=[
                        {
                            k: v
                            for k, v in b.items()
                            if k not in {"proof", "equality_derivation"}
                        }
                        for b in evidence["branches"]
                    ],
                    claim_scope="submitted_witness",
                    exhaustive=False,
                    equality_derivation=[
                        {
                            "math": relation_latex(
                                parse_math_relation(row["math"], symbols)
                            ),
                            "using": row["using"],
                        }
                        for row in (evidence.get("equality_derivation") or [])
                    ],
                )
                # Associate reductions with the AM-GM application on which they
                # depend, not with the position of a submitted teaching row.
                from ..math_kernel.proof_algebra import commutative_key, from_node

                def key(text, symbols=symbols):
                    return commutative_key(
                        from_node(parse_math_relation(text, symbols).ast)
                    )

                dependencies = {
                    key(eq): {i} for i, eq in enumerate(bound["equalities"])
                }
                reductions = {}
                for row in evidence.get("equality_derivation") or []:
                    used = set().union(
                        *(dependencies.get(key(v), set()) for v in row["using"])
                    )
                    dependencies[key(row["math"])] = used
                    if len(used) == 1:
                        reductions[next(iter(used))] = relation_latex(
                            parse_math_relation(row["math"], symbols)
                        )
                data["equality_applications"] = [
                    {
                        "terms": [
                            tree_latex(
                                _legacy_tree(parse_math_expression(t, symbols).ast)
                            )
                            for t in app["terms"]
                        ],
                        "reduction": reductions.get(i),
                    }
                    for i, app in enumerate(bound["applications"])
                ]
            result.append(
                InequalityTeachingEvidence(
                    step_id,
                    method.method_id,
                    json.dumps(data, ensure_ascii=False, sort_keys=True),
                )
            )
            continue

        def select_role(left, right, *, required=False, chain=chain):
            # Match a normalized >= relation using already parsed scalar identities.
            # This is syntax/role classification, never a new proof or substitution.
            matches = []
            for row in chain:
                parsed = row.parsed
                if parsed.ast.op not in {">=", "<="}:
                    continue
                lhs, rhs = (
                    scalar(parsed.source[n.span[0] : n.span[1]])
                    for n in parsed.ast.children
                )
                if parsed.ast.op == "<=":
                    lhs, rhs = rhs, lhs
                if lhs == left and rhs == right:
                    matches.append(row)
            if not matches:
                if required:
                    raise ValueError("verified AM-GM teaching role missing")
                return None
            return {
                "math": relation(matches[0].parsed),
                "origins": [row.origin for row in matches],
            }

        root = sp.sqrt(terms[0] * terms[1])
        application_roles = {
            "amgm": select_role(sum(terms), 2 * root)
            or {
                "math": f"{student_math_display(sum(terms))} ≥ {student_math_display(2 * root)}",
                "origins": [r.origin for r in chain],
                "basis": "verified_amgm_template",
            },
            "bound": select_role(
                scalar(bound["bound"]), scalar(target["target_math"]), required=True
            ),
        }
        for role, lhs, rhs in (
            ("fixed_sum_substitution", fixed_value, 2 * root),
            ("root_bound", fixed_value / 2, root),
        ):
            selected = select_role(lhs, rhs)
            if selected is not None:
                application_roles[role] = selected
        data = {
            "target": display(target["target_math"]),
            "conditions": [relation(c) for c in conditions],
            "terms": [student_math_display(t) for t in terms],
            "fixed_condition": relation(fixed),
            "derivation": [relation(r.parsed) for r in chain],
            "bound": display(bound["bound"]),
            "equality": relation(parse_math_relation(bound["equality"], symbols)),
            "origins": [r.origin for r in chain],
            "application_roles": application_roles,
            "direction": bound.get("direction", "<="),
            "applications": bound.get(
                "applications",
                [
                    {
                        "terms": [str(t) for t in terms],
                        "equality": bound["equality"],
                    }
                ],
            ),
            "equalities": bound.get("equalities", [bound["equality"]]),
            "local_relations": [application_roles["amgm"]],
            "overall_relation": application_roles["bound"]["math"],
            "previous_bound": None,
        }
        if method.method_id == "close_equality_and_restore":
            rows = parse_derivation(evidence["steps"], symbols)
            data.update(
                witness={
                    name: display(value)
                    for name, value in evidence["assignments"].items()
                },
                witness_derivation=[relation(r.parsed) for r in rows],
                witness_origins=[r.origin for r in rows],
                claim_scope="submitted_witness",
                exhaustive=False,
            )
        result.append(
            InequalityTeachingEvidence(
                step_id,
                method.method_id,
                json.dumps(data, ensure_ascii=False, sort_keys=True),
            )
        )
    return tuple(result)
