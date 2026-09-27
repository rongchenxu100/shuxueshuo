"""Public M07 teaching evidence without proof certificates."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

import sympy as sp

CONTRACT = "substitution-teaching-evidence/v1"


@dataclass(frozen=True)
class SubstitutionTeachingEvidence:
    step_id: str
    data_json: str

    def __post_init__(self):
        if not self.step_id or self.data.get("kind") != "verified_substitution":
            raise ValueError("invalid substitution teaching evidence")
        if not all(
            self.data.get(k) for k in ("source", "result", "relations", "definitions")
        ):
            raise ValueError("incomplete substitution teaching evidence")

    @property
    def data(self):
        return json.loads(self.data_json)

    @property
    def schema_version(self):
        return CONTRACT

    @property
    def evidence_id(self):
        return (
            "substitution:"
            + hashlib.sha256(
                json.dumps(self.to_payload(False), sort_keys=True).encode()
            ).hexdigest()
        )

    def to_payload(self, include_id=True):
        data = {"schema_version": CONTRACT, "step_id": self.step_id, "data": self.data}
        if include_id:
            data["evidence_id"] = self.evidence_id
        return data

    def authority_payload(self):
        return self.to_payload()

    @classmethod
    def from_payload(cls, raw):
        if (
            set(raw) != {"schema_version", "step_id", "data", "evidence_id"}
            or raw["schema_version"] != CONTRACT
        ):
            raise ValueError("invalid substitution evidence payload")
        item = cls(raw["step_id"], json.dumps(raw["data"], sort_keys=True))
        if raw["evidence_id"] != item.evidence_id:
            raise ValueError("substitution evidence hash mismatch")
        return item


def substitution_teaching_evidence_schema():
    return {
        "title": "SubstitutionTeachingEvidence",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "step_id", "data", "evidence_id"],
        "properties": {
            "schema_version": {"const": CONTRACT},
            "step_id": {"type": "string", "minLength": 1},
            "data": {"type": "object"},
            "evidence_id": {"type": "string", "minLength": 1},
        },
    }


def collect_substitution_evidence(step_id, method_results):
    from ..math_kernel.expression_parser import (
        parse_math_expression,
        parse_math_relation,
    )
    from ..math_kernel.expression_rewrite import _legacy_tree, tree_latex
    from ..math_kernel.substitution import replay_substitution

    result = []
    for method in method_results:
        if method.method_id != "substitute_expressions":
            continue
        trace = method.trace_fragments[0]
        target, evidence = trace["source_target"], trace["evidence"]
        context = replay_substitution(target, evidence)

        def expression(text, context=context):
            return tree_latex(
                _legacy_tree(parse_math_expression(text, context.symbols).ast)
            )

        def relation(text, context=context):
            parsed = parse_math_relation(text, context.symbols)
            a, b = parsed.ast.children
            op = {">=": r"\geq ", "<=": r"\leq ", "!=": r"\ne "}.get(
                parsed.ast.op, parsed.ast.op
            )
            return tree_latex(_legacy_tree(a)) + op + tree_latex(_legacy_tree(b))

        new_names = set(evidence["definitions"])
        transformed_conditions = project_new_conditions(
            evidence["relations"], context.symbols, new_names
        )
        original_tree = parse_math_expression(
            target["target_math"], context.symbols
        ).ast

        def nodes(node):
            yield node
            for child in node.children:
                yield from nodes(child)

        mappings = []
        for new, source in evidence["definitions"].items():
            value = parse_math_expression(source, context.symbols).to_sympy(
                context.symbols
            )
            match = next(
                (
                    node
                    for node in nodes(original_tree)
                    if node.op == "div"
                    and parse_math_expression(
                        target["target_math"][
                            node.children[1].span[0] : node.children[1].span[1]
                        ],
                        context.symbols,
                    ).to_sympy(context.symbols)
                    == value
                ),
                None,
            )
            if match is not None:
                mappings.append(
                    {
                        "kind": "denominator",
                        "numerator": expression(
                            target["target_math"][
                                match.children[0].span[0] : match.children[0].span[1]
                            ]
                        ),
                        "denominator": expression(source),
                        "variable": new,
                        "assignment": relation(f"{new}=({source})"),
                    }
                )
            else:
                mappings.append(
                    {
                        "kind": "expression",
                        "source": expression(source),
                        "variable": new,
                        "assignment": relation(f"{new}=({source})"),
                    }
                )

        data = {
            "kind": "verified_substitution",
            "source": expression(target["target_math"]),
            "result": expression(evidence["expression"]),
            "definitions": [
                relation(f"{n}=({v})") for n, v in evidence["definitions"].items()
            ],
            "conditions": [relation(c["math"]) for c in target["source_conditions"]],
            "condition_equations": [
                relation(c["math"])
                for c in target["source_conditions"]
                if parse_math_relation(c["math"], context.symbols).ast.op == "="
            ],
            "transformed_equations": [
                relation(r)
                for r in transformed_conditions
                if parse_math_relation(r, context.symbols).ast.op == "="
            ],
            "relations": [relation(r) for r in evidence["relations"]],
            "restoration_branches": [
                [relation(f"{n}=({v})") for n, v in b.items()]
                for b in evidence["restoration_branches"]
            ],
            "origins": deepcopy(evidence["origins"]),
            "transformed_conditions": [relation(r) for r in transformed_conditions],
            "mappings": mappings,
        }
        result.append(
            SubstitutionTeachingEvidence(step_id, json.dumps(data, sort_keys=True))
        )
    return tuple(result)


def project_new_conditions(relations, symbols, new_names):
    """Deduplicate verified equations algebraically, retaining their domains.

    A later strict sign may replace its weaker nonnegative/nonzero spelling.
    Full submitted rows and certificates remain in the execution evidence.
    """
    from ..math_kernel.expression_parser import parse_math_relation
    from ..math_kernel.proof_algebra import from_node, names

    result, equations, signs = [], set(), {}
    new_names = set(new_names)
    for text in relations:
        parsed = parse_math_relation(text, symbols)
        if not names(from_node(parsed.ast)) <= new_names:
            continue
        from ..math_kernel.expression_parser import parse_math_expression

        left, right = (
            parse_math_expression(parsed.source[slice(*node.span)], symbols).to_sympy(
                symbols
            )
            for node in parsed.ast.children
        )
        delta = sp.cancel(left - right)
        if parsed.ast.op == "=":
            numerator = sp.fraction(delta)[0]
            if numerator == 0:
                continue
            try:
                key = str(
                    sp.Poly(numerator, *[symbols[n] for n in sorted(new_names)])
                    .monic()
                    .as_expr()
                )
            except sp.PolynomialError:
                key = str(delta)
            if key in equations:
                continue
            equations.add(key)
        elif right == 0 and parsed.ast.op in {">", ">=", "!="}:
            key = str(delta)
            previous = signs.setdefault(key, {})
            if ">" in previous or parsed.ast.op in previous:
                continue
            if parsed.ast.op == ">":
                for index in previous.values():
                    result[index] = None
                previous.clear()
            previous[parsed.ast.op] = len(result)
        result.append(text)
    return [text for text in result if text is not None]
