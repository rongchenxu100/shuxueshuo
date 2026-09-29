"""Serializable auxiliary proof evidence; never a new teaching operation.

Payload validation checks shape/identity, not mathematical truth. Restoring the
fact index must replay it with ScopedProofFacts and external Runtime authority.
"""

import json
from dataclasses import dataclass

from ..math_kernel.proof_algebra import digest
from ..math_kernel.proof_facts import canonical

CONTRACT = "scoped-proof-commit/v1"
REFERENCE_CONTRACT = "scoped-proof-commit-ref/v1"


@dataclass(frozen=True)
class ProofFactsExecutionEvidence:
    step_id: str
    source_hash: str
    commit_json: str
    is_reference: bool = False

    def __post_init__(self):
        commit = self.commit
        if (
            not self.step_id
            or not self.source_hash
            or commit.get("call_id") != self.step_id
        ):
            raise ValueError("invalid proof commit identity")
        if self.is_reference and (
            set(commit) != {"call_id", "commit_id", "dependencies", "proof_reads"}
            or not isinstance(commit.get("commit_id"), str) or not commit["commit_id"]
        ):
            raise ValueError("invalid proof commit reference")
        if not isinstance(commit.get("dependencies"), list) or not isinstance(
            commit.get("proof_reads"), list
        ):
            raise TypeError("proof dependencies required")

    @classmethod
    def from_commit(cls, step_id, source_hash, commit):
        # The restore-state fact store owns the full record. Teaching/execution
        # need only its identity and dependency edges, never another proof copy.
        return cls(step_id, source_hash, canonical({
            "call_id": commit["call_id"],
            "commit_id": commit["commit_id"],
            "dependencies": list(commit["dependencies"]),
            "proof_reads": list(commit["proof_reads"]),
        }), is_reference=True)

    def verify_reference(self, source_hash, commits):
        if not self.is_reference:
            return
        ref = self.commit
        target = commits.get(self.step_id)
        if self.source_hash != source_hash or target is None or any(
            ref[key] != target.get(key)
            for key in ("call_id", "commit_id", "dependencies", "proof_reads")
        ):
            raise ValueError("proof commit reference does not match restore state")

    @property
    def commit(self):
        return json.loads(self.commit_json)

    @property
    def schema_version(self):
        return REFERENCE_CONTRACT if self.is_reference else CONTRACT

    def to_payload(self):
        body = {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "source_hash": self.source_hash,
            "commit_ref" if self.is_reference else "commit": self.commit,
        }
        return {**body, "evidence_id": digest(body)}

    def authority_payload(self):
        return self.to_payload()

    @classmethod
    def from_payload(cls, payload):
        reference = payload.get("schema_version") == REFERENCE_CONTRACT
        item = cls(
            payload["step_id"], payload["source_hash"],
            canonical(payload["commit_ref" if reference else "commit"]), reference,
        )
        if item.to_payload() != payload:
            raise ValueError("proof evidence shape or identity changed")
        return item


def proof_fact_evidence_schema():
    legacy = {
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

    reference = {
        **legacy,
        "required": ["schema_version", "step_id", "source_hash", "commit_ref", "evidence_id"],
        "properties": {
            **{k: v for k, v in legacy["properties"].items() if k != "commit"},
            "schema_version": {"const": REFERENCE_CONTRACT},
            "commit_ref": {
                "type": "object", "additionalProperties": False,
                "required": ["call_id", "commit_id", "dependencies", "proof_reads"],
                "properties": {
                    "call_id": {"type": "string", "minLength": 1},
                    "commit_id": {"type": "string", "minLength": 1},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "proof_reads": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }
    return {"oneOf": [legacy, reference]}


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
