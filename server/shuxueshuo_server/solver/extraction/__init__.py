"""Source-grounded problem extraction primitives."""

from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpus,
    GoldCorpusAuditReport,
    GoldCorpusError,
    audit_gold_corpus,
    load_gold_corpus,
    render_gold_overlays,
)
from shuxueshuo_server.solver.extraction.semantic_diff import (
    ProblemSemanticDiffReport,
    compare_problem_semantics,
)

__all__ = [
    "GoldCorpus",
    "GoldCorpusAuditReport",
    "GoldCorpusError",
    "ProblemSemanticDiffReport",
    "audit_gold_corpus",
    "compare_problem_semantics",
    "load_gold_corpus",
    "render_gold_overlays",
]
