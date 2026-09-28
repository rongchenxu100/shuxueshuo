"""Bounded retrieval over an already-authorized immutable fact view.

This module does not grant visibility. Runtime verifies producer certificates
and filters Scope, symbol identity, validity and execution order before indexing.
Records keep their original IDs; deduplication chooses an evidence representative
without rewriting its producer or dependency graph.
"""

from collections import defaultdict
from dataclasses import asdict

from .expression_parser import parse_math_relation
from .proof_algebra import ZERO, digest, from_node, names, walk
from .proof_checker import fact_key


class ProofFactIndex:
    def __init__(self, facts, symbols, *, limit=4096):
        self.exact, self.kinds, self.subtrees = (
            defaultdict(set),
            defaultdict(set),
            defaultdict(set),
        )
        self.symbols, self.domain, self.isolated = (
            defaultdict(set),
            defaultdict(set),
            defaultdict(set),
        )
        self.producers, self.dependencies, self.versions = (
            defaultdict(set),
            defaultdict(set),
            defaultdict(set),
        )
        self.facts, self.trees, self.parsed = {}, {}, {}
        self.source_constants = set()
        self.filtered_constants, self.duplicates = 0, 0
        seen = set()
        # Stable evidence representative, independent of input enumeration.
        for fact in sorted(
            facts, key=lambda f: (f.producer_call_id is not None, f.source, f.fact_id)
        ):
            parsed = parse_math_relation(fact.relation, symbols)
            tree = from_node(parsed.ast)
            if not names(tree) and fact.proof_ref is not None:
                self.filtered_constants += 1
                continue
            key = (fact.statement_key, digest(asdict(fact.validity)))
            if key in seen:
                self.duplicates += 1
                continue
            if len(seen) >= limit:
                from .proof_algebra import ProofFailure

                raise ProofFailure(
                    "proof_search_exhausted", "unique authorized fact index limit"
                )
            seen.add(key)
            ref = fact.fact_id
            if not names(tree):
                # Original constant premises still take part in the checker's
                # finite contradiction check. Only verified derived constants
                # may disappear from the retrieval index.
                self.source_constants.add(ref)
            self.facts[ref], self.trees[ref], self.parsed[ref] = fact, tree, parsed
            self.exact[fact_key(tree)].add(ref)
            self.kinds[tree[0]].add(ref)
            for subtree in walk(tree):
                if names(subtree):
                    self.subtrees[subtree].add(ref)
            for name in names(tree):
                self.symbols[dict(fact.symbol_bindings)[name]].add(ref)
            if tree[2] == ZERO and tree[0] != "=":
                self.domain[tree[1]].add(ref)
            if tree[0] == "=":
                for side in tree[1:]:
                    if side[0] == "symbol":
                        self.isolated[side[1]].add(ref)
            self.producers[fact.producer_call_id].add(ref)
            for dependency in fact.dependency_fact_refs:
                self.dependencies[dependency].add(ref)
            for version in fact.validity.state_version_refs:
                self.versions[version].add(ref)
        self.fingerprint = digest(sorted(self.facts))

    def query(self, goal, bindings, *, limit=64):
        exact = self.exact.get(fact_key(goal), set())
        domain, subtree, isolated = set(), set(), set()
        for node in walk(goal):
            if names(node):
                domain.update(self.domain.get(node, ()))
                subtree.update(self.subtrees.get(node, ()))
        goal_names = names(goal)
        for name in goal_names:
            isolated.update(self.isolated.get(name, ()))
        nearby = set()
        expansion_truncated = False
        # Bounded symbol-neighbour expansion admits chained original conditions
        # without enumerating arbitrary subsets of the fact store.
        identities = {dict(bindings)[name] for name in goal_names}
        for _ in range(min(len(bindings), limit)):
            expanded = set().union(
                *(self.symbols.get(identity, set()) for identity in identities)
            )
            nearby.update(expanded)
            if len(nearby) >= limit:
                expansion_truncated = True
                break
            previous = set(identities)
            identities.update(
                dict(self.facts[ref].symbol_bindings)[name]
                for ref in expanded
                for name in names(self.trees[ref])
            )
            if identities == previous:
                break
        pool = self.source_constants | exact | domain | subtree | isolated | nearby

        def ranking(ref):
            tree, fact = self.trees[ref], self.facts[ref]
            rank = (
                -1
                if ref in self.source_constants
                else 0
                if ref in exact
                else 1
                if ref in domain
                else 2
                if ref in isolated
                else 3
                if ref in subtree
                else 4
            )
            return (
                rank,
                len(names(tree) - goal_names),
                len(tuple(walk(tree))),
                fact.statement_key,
                ref,
            )

        ranked = sorted(pool, key=ranking)
        selected = tuple(ranked[:limit])
        return selected, {
            "available": len(self.facts),
            "matched": len(pool),
            "selected": len(selected),
            "truncated": len(ranked) > limit or expansion_truncated,
            "reason": "retrieval_limit"
            if len(ranked) > limit
            else "symbol_expansion_limit"
            if expansion_truncated
            else None,
            "duplicates": self.duplicates,
            "constants": self.filtered_constants,
        }
