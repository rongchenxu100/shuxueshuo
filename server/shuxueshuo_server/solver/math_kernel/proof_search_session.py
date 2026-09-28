"""Internal proof session: retrieve small contexts, search, then verify.

Runtime supplies an authenticated view; this service cannot publish facts or
change the caller's target/version binding. Failed attempts share one ledger.
"""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, replace

from .expression_parser import parse_math_relation
from .proof_algebra import ProofFailure, digest, from_node
from .proof_checker import _document
from .proof_fact_index import ProofFactIndex
from .proof_search import default_search_configuration, run_scheduled_request
from .proof_types import ProofContext, ProofLimits, _Budget


class ProofSearchSession:
    def __init__(self, *, policy=None, strategies=None, rules=None, limits=None):
        defaults = default_search_configuration()
        self.strategies, self.rules, self.policy = (
            strategies or defaults[0],
            rules or defaults[1],
            policy or defaults[2],
        )
        self.limits = limits or ProofLimits()
        self.budget = _Budget(self.limits)
        self.successes = OrderedDict()
        self.runs = []

    def prove(
        self,
        relation,
        *,
        facts,
        symbols,
        bindings,
        scope_id,
        manifest_hash,
        authority_hash,
    ):
        parsed = parse_math_relation(relation, symbols)
        request = {"kind": "relation", "candidate": _document(parsed)}
        index = ProofFactIndex(facts, symbols, limit=self.policy.fact_limit)
        ids, retrieval = index.query(
            from_node(parsed.ast), bindings, limit=self.policy.retrieval_limit
        )
        key = digest(
            (
                request,
                manifest_hash,
                authority_hash,
                tuple(sorted(bindings)),
                scope_id,
                index.fingerprint,
                self.policy.fingerprint,
                asdict(self.limits),
            )
        )
        if key in self.successes:
            cached = deepcopy(self.successes[key])
            # Revalidate caller-owned copies and the exact saved context.
            checked = self.rules.replay(
                cached.result.proof, cached.context, budget=_Budget(self.limits)
            )
            if checked.status != "proved":
                raise ProofFailure("invalid_proof", "cached certificate failed replay")
            cached.diagnostics = {**cached.diagnostics, "session_cache_hit": True}
            return cached
        # Deterministic bounded widening, never all premise combinations.
        sizes = sorted(
            {
                min(n, len(ids), self.limits.premises)
                for n in (4, 8, self.limits.premises)
            }
        )
        attempts = []
        for i, size in enumerate(sizes):
            selected = ids[:size]
            context = ProofContext(
                symbols,
                {
                    ref: replace(index.parsed[ref], source_path=f"fact:{ref}")
                    for ref in selected
                },
                self.limits,
                scope_id,
            )
            run = run_scheduled_request(
                context,
                request,
                budget=self.budget,
                policy=self.policy,
                strategies=self.strategies,
                rules=self.rules,
                manifest_hash=manifest_hash,
                request_quota={
                    resource: max(
                        1,
                        (
                            getattr(self.limits, resource)
                            - self.budget.counts.get(resource, 0)
                        )
                        // (len(sizes) - i),
                    )
                    for resource in ("attempts", "reductions", "nodes")
                }
                if i < len(sizes) - 1
                else None,
            )
            attempts.append(run.diagnostics)
            if run.result.status == "proved":
                # Provider-specific compaction rechecks every node in the exact
                # minimal local context; no hash-only certificate rewriting.
                package = self.strategies.resolve(
                    self.policy.package_identity, self.rules
                )
                context, proof = package.compact_context(context, run.result.proof)
                run.result = replace(run.result, proof=proof)
                run.context = context
                run.diagnostics = {
                    **run.diagnostics,
                    "retrieval": retrieval,
                    "attempts": attempts,
                    "actual_fact_ids": sorted(context.premises),
                    "session_cache_hit": False,
                }
                self.successes[key] = deepcopy(run)
                if len(self.successes) > 64:
                    self.successes.popitem(last=False)
                self.runs.append(run.diagnostics)
                return run
            if run.result.code not in {"proof_missing", "strategy_budget_exhausted"}:
                break
        run.context = context
        run.diagnostics = {
            **run.diagnostics,
            "retrieval": retrieval,
            "attempts": attempts,
        }
        self.runs.append(run.diagnostics)
        return run
