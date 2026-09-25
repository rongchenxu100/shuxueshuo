"""Source-preserving public M01 presentation, without proof certificates."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

CONTRACT = "expression-rewrite-teaching-evidence/v1"


@dataclass(frozen=True)
class RewriteTeachingEvidence:
    step_id: str
    data_json: str

    def __post_init__(self):
        if not self.step_id or self.data.get("kind") != "verified_expression_rewrite":
            raise ValueError("invalid rewrite teaching evidence")
        if not all(self.data.get(k) for k in ("source", "result", "transitions")):
            raise ValueError("incomplete rewrite teaching evidence")

    @property
    def data(self):
        return json.loads(self.data_json)

    @property
    def schema_version(self):
        return CONTRACT

    @property
    def evidence_id(self):
        return (
            "rewrite:"
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
            raise ValueError("invalid rewrite evidence payload")
        item = cls(raw["step_id"], json.dumps(raw["data"], sort_keys=True))
        if raw["evidence_id"] != item.evidence_id:
            raise ValueError("rewrite evidence hash mismatch")
        return item


def rewrite_teaching_evidence_schema():
    return {
        "title": "RewriteTeachingEvidence",
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


def collect_rewrite_evidence(step_id, method_results):
    result = []
    for method in method_results:
        if method.method_id != "organize_expressions":
            continue
        traces = [
            t
            for t in method.trace_fragments
            if t.get("kind") == "verified_expression_rewrite"
        ]
        if len(traces) != 1:
            raise ValueError("verified rewrite teaching trace missing")
        trace = deepcopy(
            {
                k: traces[0][k]
                for k in (
                    "kind",
                    "source",
                    "result",
                    "transitions",
                    "conditionCards",
                    "teachingEffect",
                )
            }
        )
        for card in trace["conditionCards"]:
            card.pop("source", None)
            card.pop("boundIndex", None)
        result.append(
            RewriteTeachingEvidence(step_id, json.dumps(trace, sort_keys=True))
        )
    return tuple(result)
