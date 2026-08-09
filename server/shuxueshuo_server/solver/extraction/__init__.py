"""Source-grounded problem extraction primitives."""

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.attempt_ledger_store import (
    ExtractionAttemptLedgerStore,
)
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ExtractionProjection,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.f0_adapter import (
    F0ExtractionContextSeed,
    build_f0_extraction_context_seed,
)
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
    compare_solver_projection_semantics,
)
from shuxueshuo_server.solver.extraction.observation_context import (
    ObservationContextTransitionService,
    f2_semantic_config,
)
from shuxueshuo_server.solver.extraction.observation_pipeline import (
    F2ObservationAssemblyResult,
    F2ObservationPipeline,
)
from shuxueshuo_server.solver.extraction.observations import (
    PaddleObservationAdapter,
    PaddleProviderRecord,
    ProblemRegionProposer,
    ProviderManifest,
    SourceObservation,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
    MultimodalEvidencePackBuilder,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DoubaoMultimodalExtractionProvider,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemGraph,
    ProblemPromotionService,
    ProblemRepairPatch,
    ProblemRepairService,
    VerifiedProblem,
    problem_domain_response_format,
    problem_domain_schema,
    problem_repair_response_format,
    problem_repair_schema,
)
from shuxueshuo_server.solver.extraction.problem_domain_context import (
    ProblemDomainContextTransitionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_debug import (
    ProblemDomainDebugWriter,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
    SolverProblemProjection,
)
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    ProblemDomainExtractionAttemptResult,
    ProblemDomainExtractionRunResult,
    ProblemDomainExtractionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidationResult,
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    ProblemExtractionContextError,
    ProblemSourceFingerprint,
    ProblemSourceFingerprintService,
    SourceSelection,
)

__all__ = [
    "ExtractionArtifactStore",
    "ExtractionAttemptLedger",
    "ExtractionAttemptLedgerStore",
    "ExtractionAttemptRecord",
    "ExtractionDependencyManifest",
    "ExtractionProjection",
    "F2ObservationAssemblyResult",
    "F2ObservationPipeline",
    "F0ExtractionContextSeed",
    "GoldCorpus",
    "GoldCorpusAuditReport",
    "GoldCorpusError",
    "ObservationContextTransitionService",
    "MultimodalEvidencePack",
    "MultimodalEvidencePackBuilder",
    "PaddleObservationAdapter",
    "PaddleProviderRecord",
    "ProblemExtractionContext",
    "ProblemExtractionContextBuilder",
    "ProblemExtractionContextError",
    "ProblemDraft",
    "ProblemDomainContextTransitionService",
    "ProblemDomainDebugWriter",
    "ProblemDomainExtractionAttemptResult",
    "ProblemDomainExtractionRunResult",
    "ProblemDomainExtractionService",
    "ProblemDomainProjector",
    "ProblemDomainValidationResult",
    "ProblemDomainValidator",
    "ProblemGraph",
    "ProblemPromotionService",
    "ProblemRepairPatch",
    "ProblemRepairService",
    "ProblemRegionProposer",
    "ProblemSemanticDiffReport",
    "ProblemSourceFingerprint",
    "ProblemSourceFingerprintService",
    "ProviderManifest",
    "DoubaoMultimodalExtractionProvider",
    "SourceObservation",
    "SourceSelection",
    "SolverProblemProjection",
    "VerifiedProblem",
    "audit_gold_corpus",
    "compare_problem_semantics",
    "compare_solver_projection_semantics",
    "f2_semantic_config",
    "build_f0_extraction_context_seed",
    "load_gold_corpus",
    "render_gold_overlays",
    "problem_domain_response_format",
    "problem_domain_schema",
    "problem_repair_response_format",
    "problem_repair_schema",
]
