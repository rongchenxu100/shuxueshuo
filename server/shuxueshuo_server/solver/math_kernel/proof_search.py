"""Versioned, deterministic search scheduling; no mathematical rule semantics.

A strategy can only propose a candidate. Engines check candidates before success;
replay uses the independent RuleRegistry and never invokes this scheduler.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from .proof_algebra import ProofFailure, digest
from .proof_types import _Budget


@dataclass(frozen=True)
class CandidateDescriptor:
    key: str = "root"
    subgoal_count: int = 0
    dependency_count: int = 0
    data: tuple = ()


@dataclass(frozen=True)
class ProofStrategy:
    strategy_id: str
    phase: int
    cost: int
    supported_goal_kinds: tuple[str, ...]
    required_rules: tuple[str, ...]
    match: Callable
    propose: Callable

    def __post_init__(self):
        if not self.strategy_id or self.phase not in range(5) or self.cost < 0:
            raise ValueError("invalid strategy declaration")


@dataclass(frozen=True)
class StrategyPackage:
    package_id: str
    ruleset_hash: str
    strategies: tuple[ProofStrategy, ...]
    engine_factory: Callable
    compact_context: Callable = lambda context, proof: (context, proof)

    @property
    def identity(self):
        return self.package_id, self.ruleset_hash


@dataclass(frozen=True)
class StrategyRegistry:
    packages: tuple[StrategyPackage, ...]

    def __post_init__(self):
        if len({p.identity for p in self.packages}) != len(self.packages):
            raise ValueError("duplicate strategy package")
        for package in self.packages:
            if len({s.strategy_id for s in package.strategies}) != len(
                package.strategies
            ):
                raise ValueError("duplicate strategy ID")

    def with_package(self, package):
        return StrategyRegistry((*self.packages, package))

    def resolve(self, identity, rules):
        package = next((p for p in self.packages if p.identity == identity), None)
        if package is None:
            raise ProofFailure("invalid_input", "search package not registered")
        checker = rules.resolve(*identity)
        for strategy in package.strategies:
            if not set(strategy.required_rules) <= set(checker.rule_ids):
                raise ProofFailure(
                    "invalid_input", "strategy requires rules outside its package"
                )
        return package


@dataclass(frozen=True)
class SearchPolicy:
    version: str
    package_identity: tuple[str, str]
    allowed_rules: tuple[str, ...]
    disabled_strategies: tuple[str, ...] = ()
    candidate_limit: int = 512
    branch_attempts: int = 96
    branch_reductions: int = 48
    branch_nodes: int = 192
    arithmetic_operations: int = 65536
    branch_arithmetic_operations: int = 8192
    trace_limit: int = 256
    retrieval_limit: int = 64
    fact_limit: int = 4096

    def __post_init__(self):
        if not self.version or any(
            type(getattr(self, k)) is not int or getattr(self, k) <= 0
            for k in (
                "candidate_limit",
                "branch_attempts",
                "branch_reductions",
                "branch_nodes",
                "arithmetic_operations",
                "branch_arithmetic_operations",
                "trace_limit",
                "retrieval_limit",
                "fact_limit",
            )
        ):
            raise ValueError("positive policy limits required")

    @property
    def fingerprint(self):
        return digest(asdict(self))


class BranchBudgetExhausted(ProofFailure):
    def __init__(self, message, owner):
        super().__init__("strategy_budget_exhausted", message)
        self.owner = owner


class SearchBudget(_Budget):
    """Nested branch leases over a single nonrefundable global ledger."""

    def __init__(self, limits, policy, parent=None, request_quota=None):
        super().__init__(limits)
        self.policy = policy
        self.parent = parent
        if parent is not None:
            self.counts = parent.counts
            self.gcd_cache = parent.gcd_cache
            self.equation_divisors = parent.equation_divisors
            self.proof_nodes = parent.proof_nodes
            self.proven_goals = parent.proven_goals
        self.leases = []
        self.candidates = 0
        self.trace = []
        self.trace_dropped = 0
        self.cache_hits = 0
        self.request_start = dict(self.counts)
        self.request_quota = request_quota or {}
        self.request_owner = object()

    def use(self, field, amount=1):
        try:
            if field == "arithmetic_operations":
                self.counts[field] = self.counts.get(field, 0) + amount
                if self.counts[field] > self.policy.arithmetic_operations:
                    raise ProofFailure(
                        "proof_search_exhausted",
                        "arithmetic operation budget exhausted",
                    )
            elif self.parent is not None:
                self.parent.use(field, amount)
            else:
                super().use(field, amount)
        except ProofFailure as exc:
            if exc.code == "proof_limit":
                raise ProofFailure("proof_search_exhausted", str(exc)) from exc
            raise
        for resource, cap in self.request_quota.items():
            if (
                resource == field
                and self.counts.get(field, 0) - self.request_start.get(field, 0) > cap
            ):
                raise BranchBudgetExhausted(
                    f"context {field} quota exhausted", self.request_owner
                )
        for owner, start, caps in self.leases:
            if (
                field in caps
                and self.counts.get(field, 0) - start.get(field, 0) > caps[field]
            ):
                raise BranchBudgetExhausted(f"candidate {field} quota exhausted", owner)

    @contextmanager
    def branch(self):
        caps = {
            "attempts": self.policy.branch_attempts,
            "reductions": self.policy.branch_reductions,
            "nodes": self.policy.branch_nodes,
            "arithmetic_operations": self.policy.branch_arithmetic_operations,
        }
        owner = object()
        self.leases.append((owner, dict(self.counts), caps))
        try:
            yield owner
        finally:
            self.leases.pop()

    def event(self, event):
        if len(self.trace) < self.policy.trace_limit:
            self.trace.append(event)
        else:
            self.trace_dropped += 1

    def report(self):
        return {
            "policy": asdict(self.policy),
            "effective_limits": asdict(self.limits),
            "policy_hash": self.policy.fingerprint,
            "counts": dict(self.counts),
            "candidates": self.candidates,
            "cache_hits": self.cache_hits,
            "trace": self.trace,
            "trace_dropped": self.trace_dropped,
        }


class SearchScheduler:
    def __init__(self, package, policy, budget):
        self.package, self.policy, self.budget = package, policy, budget

    def prove(self, engine, goal):
        queue = []
        for strategy in self.package.strategies:
            if (
                strategy.strategy_id in self.policy.disabled_strategies
                or goal[0] not in strategy.supported_goal_kinds
                or not set(strategy.required_rules) <= set(self.policy.allowed_rules)
            ):
                continue
            # Match is trusted bounded structural inspection, never algebra.
            for candidate in strategy.match(goal, engine):
                queue.append(
                    (
                        strategy.phase,
                        strategy.cost,
                        candidate.subgoal_count,
                        candidate.dependency_count,
                        strategy.strategy_id,
                        candidate.key,
                        strategy,
                        candidate,
                    )
                )
                if len(queue) > self.policy.candidate_limit:
                    raise BranchBudgetExhausted(
                        "request candidate queue limit", self.budget.request_owner
                    )
        local_exhausted = False
        for *_, strategy, candidate in sorted(queue, key=lambda item: item[:6]):
            self.budget.candidates += 1
            if self.budget.candidates > self.policy.candidate_limit:
                raise BranchBudgetExhausted(
                    "request candidate budget exhausted", self.budget.request_owner
                )
            saved = engine.checkpoint()
            before = dict(self.budget.counts)
            status, root = "not_applicable", None
            try:
                with self.budget.branch() as lease:
                    self.budget.use("attempts")
                    root = strategy.propose(engine, goal, candidate)
                    if root is not None:
                        engine.check_candidate(root, goal)
                        status = "proved"
            except ProofFailure as exc:
                status = exc.code
                if exc.code == "strategy_budget_exhausted":
                    # An exhausted ancestor must unwind to its own candidate;
                    # descendants cannot spend the remaining global budget
                    # repeatedly trying siblings under an already-expired lease.
                    if (
                        isinstance(exc, BranchBudgetExhausted)
                        and exc.owner is not lease
                    ):
                        raise
                    local_exhausted = True
                elif exc.code == "proof_limit":
                    # Input validation ran before scheduling. Intermediate
                    # expressions may exceed the arithmetic capability profile;
                    # this candidate is unavailable, not a reason to enlarge it.
                    status = "candidate_structure_limit"
                elif exc.code not in {"proof_missing", "strategy_not_applicable"}:
                    raise
            finally:
                self.budget.event(
                    {
                        "goal": goal,
                        "strategy": strategy.strategy_id,
                        "phase": strategy.phase,
                        "candidate": candidate.key,
                        "status": status,
                        "cost": {
                            k: v - before.get(k, 0)
                            for k, v in self.budget.counts.items()
                        },
                        "premises": engine.dependencies(root)
                        if status == "proved"
                        else [],
                        "subgoals": list(engine.requested_since(saved)),
                    }
                )
                if status != "proved":
                    engine.rollback(saved)
            if status == "proved":
                return root
        raise ProofFailure(
            "strategy_budget_exhausted" if local_exhausted else "proof_missing",
            "bounded strategies exhausted; relation not established",
        )


@dataclass
class SearchRun:
    result: object
    diagnostics: dict = field(default_factory=dict)
    context: object = None


def default_search_configuration():
    from .proof_checker import DEFAULT_RULE_REGISTRY
    from .real_proof_strategies import real_strategy_package

    rules = DEFAULT_RULE_REGISTRY
    package = real_strategy_package()
    checker = rules.resolve(*package.identity)
    return (
        StrategyRegistry((package,)),
        rules,
        SearchPolicy("layered-search/v3", package.identity, checker.rule_ids),
    )


def run_scheduled_request(
    context,
    request,
    *,
    budget=None,
    policy=None,
    strategies=None,
    rules=None,
    manifest_hash="local-context/v1",
    request_quota=None,
    seed_provider=None,
):
    """Bounded production search; independent replay remains the only checker."""
    from .proof_types import ProofResult

    defaults = default_search_configuration()
    strategies, rules, policy = (
        strategies or defaults[0],
        rules or defaults[1],
        policy or defaults[2],
    )
    ledger = SearchBudget(
        budget.limits if budget is not None else context.limits,
        policy,
        budget,
        request_quota,
    )
    engine = None
    try:
        package = strategies.resolve(policy.package_identity, rules)
        if not set(policy.allowed_rules) <= set(
            rules.resolve(*package.identity).rule_ids
        ):
            raise ProofFailure("invalid_input", "policy contains foreign rules")
        engine = package.engine_factory(
            context, request, budget=ledger, policy=policy, manifest_hash=manifest_hash
        )
        engine.scheduler = SearchScheduler(package, policy, ledger)
        engine.seed_provider = seed_provider
        proof = engine.run()
        # Independent final replay, separate from search work, bounded by the
        # same effective profile. A candidate cannot certify itself.
        checked = rules.replay(proof, context, budget=_Budget(ledger.limits))
        if checked.status != "proved":
            raise ProofFailure(
                checked.code or "invalid_proof",
                checked.diagnostic or "checker rejected candidate",
            )
        result = ProofResult("proved", proof=proof)
    except ProofFailure as exc:
        result = ProofResult("failed", code=exc.code, diagnostic=str(exc))
    return SearchRun(
        result,
        {
            "fact_reads": sorted(getattr(engine, "used_seed_reads", ())) if result.status == "proved" else [],
            **ledger.report(),
            "manifest_hash": manifest_hash,
            "context_hash": getattr(engine, "context_hash", None),
            "source": request.get("candidate", {}),
        },
    )
