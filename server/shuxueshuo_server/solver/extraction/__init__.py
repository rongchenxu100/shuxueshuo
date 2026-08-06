"""Source-grounded problem extraction primitives."""

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ExtractionCandidateRecord,
    ExtractionStatePatch,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
    ProblemExtractionContextTransitionService,
)
from shuxueshuo_server.solver.extraction.f0_adapter import (
    F0ExtractionContextSeed,
    build_f0_extraction_context_seed,
)
from shuxueshuo_server.solver.extraction.f3_attempt import (
    F3ExtractionAttemptResult,
    F3ExtractionAttemptService,
)
from shuxueshuo_server.solver.extraction.f3_debug import F3AttemptDebugWriter
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
from shuxueshuo_server.solver.extraction.multimodal_candidates import (
    F3ContractValidationReport,
    ProblemExtractionCandidatePatch,
    parse_candidate_patch,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
    MultimodalEvidencePackBuilder,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DoubaoMultimodalExtractionProvider,
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
    "ExtractionAttemptRecord",
    "ExtractionCandidateRecord",
    "ExtractionDependencyManifest",
    "ExtractionStatePatch",
    "F2ObservationAssemblyResult",
    "F2ObservationPipeline",
    "F3AttemptDebugWriter",
    "F3ContractValidationReport",
    "F3ExtractionAttemptResult",
    "F3ExtractionAttemptService",
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
    "ProblemExtractionContextTransitionService",
    "ProblemExtractionCandidatePatch",
    "ProblemRegionProposer",
    "ProblemSemanticDiffReport",
    "ProblemSourceFingerprint",
    "ProblemSourceFingerprintService",
    "ProviderManifest",
    "DoubaoMultimodalExtractionProvider",
    "SourceObservation",
    "SourceSelection",
    "audit_gold_corpus",
    "compare_problem_semantics",
    "f2_semantic_config",
    "build_f0_extraction_context_seed",
    "load_gold_corpus",
    "parse_candidate_patch",
    "render_gold_overlays",
]
