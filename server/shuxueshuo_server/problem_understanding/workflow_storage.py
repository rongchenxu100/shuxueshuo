"""Persistence boundary shared by the CLI and the product worker."""
from pathlib import Path

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

from .workflow_ledger import Ledger, save


class FileWorkflowStorage:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.artifacts = ExtractionArtifactStore(self.directory / 'artifacts')

    def ledger(self, binding, budget):
        return Ledger(self.directory, binding, budget)

    def save(self, name, value):
        save(self.directory / name, value)

    def proposed(self, candidate, parsed, number):
        pass

    def adopt(self, candidate, parsed, number):
        pass

    def guard(self):
        pass
