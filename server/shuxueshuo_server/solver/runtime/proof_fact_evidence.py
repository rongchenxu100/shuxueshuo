"""Serializable auxiliary proof evidence; never a new teaching operation.

Payload validation checks shape/identity, not mathematical truth. Restoring the
fact index must replay it with ScopedProofFacts and external Runtime authority.
"""

import json
from dataclasses import dataclass

from ..math_kernel.proof_algebra import digest
from ..math_kernel.proof_facts import canonical

CONTRACT = "scoped-proof-commit/v1"


@dataclass(frozen=True)
class ProofFactsExecutionEvidence:
    step_id: str
    source_hash: str
    commit_json: str

    def __post_init__(self):
        commit = self.commit
        if (
            not self.step_id
            or not self.source_hash
            or commit.get("call_id") != self.step_id
        ):
            raise ValueError("invalid proof commit identity")
        if not isinstance(commit.get("dependencies"), list) or not isinstance(
            commit.get("proof_reads"), list
        ):
            raise TypeError("proof dependencies required")

    @property
    def commit(self):
        return json.loads(self.commit_json)

    @property
    def schema_version(self):
        return CONTRACT

    def to_payload(self):
        body = {
            "schema_version": CONTRACT,
            "step_id": self.step_id,
            "source_hash": self.source_hash,
            "commit": self.commit,
        }
        return {**body, "evidence_id": digest(body)}

    def authority_payload(self):
        return self.to_payload()

    @classmethod
    def from_payload(cls, payload):
        item = cls(
            payload["step_id"], payload["source_hash"], canonical(payload["commit"])
        )
        if item.to_payload() != payload:
            raise ValueError("proof evidence shape or identity changed")
        return item


def proof_fact_evidence_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "step_id",
            "source_hash",
            "commit",
            "evidence_id",
        ],
        "properties": {
            "schema_version": {"const": CONTRACT},
            "step_id": {"type": "string", "minLength": 1},
            "source_hash": {"type": "string", "minLength": 1},
            "evidence_id": {"type": "string", "minLength": 1},
            "commit": {"type": "object"},
        },
    }


def include_proof_dependencies(graph, root_scope):
    """Keep auxiliary producers in checkpoint and explanation execution closure."""
    merged = {k: tuple(v) for k, v in graph.items()}

    def visit(scope):
        for step in (*scope.scope_steps, *(s for g in scope.goals for s in g.steps)):
            for evidence in step.evidence:
                if isinstance(evidence, ProofFactsExecutionEvidence):
                    deps = evidence.commit["dependencies"]
                    if (
                        evidence.step_id != step.step_id
                        or step.step_id not in merged
                        or any(p not in merged or p == step.step_id for p in deps)
                    ):
                        raise ValueError("invalid auxiliary proof dependency")
                    merged[step.step_id] = tuple(
                        sorted(set(merged[step.step_id]) | set(deps))
                    )
        for child in scope.children:
            visit(child)

    visit(root_scope)
    visiting, visited = set(), set()

    def check(key):
        if key in visiting:
            raise ValueError("cyclic auxiliary proof dependency")
        if key in visited:
            return
        visiting.add(key)
        for dependency in merged[key]:
            if dependency not in merged:
                raise ValueError("missing proof dependency")
            check(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in merged:
        check(key)
    return merged
