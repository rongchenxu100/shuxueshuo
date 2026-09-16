"""Shared deterministic budget for bounded semantic proofs."""


class ProofBudget:
    def __init__(self):
        self.remaining = 4096

    def use(self):
        self.remaining -= 1
        if self.remaining < 0:
            raise ValueError("equivalence.proof_budget")
