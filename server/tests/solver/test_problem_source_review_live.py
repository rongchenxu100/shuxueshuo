"""Paid image extraction of the actual layout-miss regression, explicitly opted in."""
import json
import os
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.multimodal_provider import create_vision_provider
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_debug import ProblemDomainDebugWriter
from shuxueshuo_server.solver.extraction.problem_domain_service import ProblemDomainExtractionService
from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
from shuxueshuo_server.solver.extraction.semantic_diff import compare_solver_projection_semantics
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from test_problem_source_review import recorded_input


@pytest.mark.live_llm
@pytest.mark.parametrize('sample', [1, 2, 3])
def test_heping_layout_miss_real_multimodal_extraction(tmp_path, sample):
    if os.environ.get('RUN_LLM_INTEGRATION') != '1':
        pytest.skip('requires explicit RUN_LLM_INTEGRATION=1')
    config = SolverRuntimeConfig.from_sources()
    assert config.deepseek_api_key, 'live extraction requires configured DeepSeek credentials'
    output = Path(os.environ.get('SOURCE_REVIEW_LIVE_OUTPUT', str(tmp_path))) / f'sample-{sample}'
    initial, context, store, _ = recorded_input(output)
    provider = create_vision_provider(config)
    result = ProblemDomainExtractionService(input_artifact_reader=store, output_artifact_store=store, provider=provider).run(
        context, attempt_ledger=ExtractionAttemptLedger.for_context(context), ancestor_contexts=(initial,))
    ProblemDomainDebugWriter().write(result, output / 'debug')
    assert result.accepted, [a.to_payload() for a in result.attempts]
    assert result.verified_problem.graph.family_id == 'QuadraticEqualLengthRayPathMinimumSolver'
    repo = Path(__file__).resolve().parents[3]
    gold = json.loads((repo / 'internal/problem-domain-fixtures/tj-2026-heping-yimo-25.json').read_text())
    expected = ProblemDomainValidator().validate(ProblemDraft.create(gold)).projection
    diff = compare_solver_projection_semantics(expected.canonical_input, result.solver_projection.canonical_input)
    assert diff.ok, diff.to_payload()
    assert any(a.source_review and a.source_review['status'] == 'confirmed' for a in result.attempts)
