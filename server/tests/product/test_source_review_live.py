"""Real nine-stage acceptance against an explicitly isolated product instance."""
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
import sympy as sp

from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.execution import ExecutionContext
from shuxueshuo_server.product.runner import StageRunner


@pytest.mark.live_llm
def test_heping_real_nine_stage_build(setup, settings, tmp_path, monkeypatch):
    if os.environ.get('RUN_LLM_INTEGRATION') != '1':
        pytest.skip('requires explicit RUN_LLM_INTEGRATION=1')
    assert settings.instance != 'local' and str(settings.root).startswith('/private/tmp/'), 'isolated test instance required'
    # Use the repository OCR interpreter; the test database and work root remain isolated.
    repo = Path(__file__).resolve().parents[3]
    monkeypatch.setenv('REVIEW_OCR_PYTHON', str(repo / 'server/.venv-ocr/bin/python'))
    service, ctx, _ = setup
    app = Application(settings, service, ctx)
    batch = app.create_batch('live-batch')
    content = (repo / 'server/tests/solver/fixtures/source_review/heping-layout-miss/source.png').read_bytes()
    upload = app.upload(UUID(batch['id']), 'live-upload', content, 'heping-layout-miss.png', 'image/png')['item']
    submitted = app.submit(UUID(upload['problem_id']), UUID(upload['source_id']), UUID(upload['id']), 'live-build')
    from shuxueshuo_server.product.transport import deployment
    execution = service.acquire_execution(ctx, UUID(submitted['job_id']), 'source-review-live-test',
        deployment_version=deployment(service), lease_seconds=3600)
    x = ExecutionContext(app, ctx, UUID(submitted['build_id']), execution['id'], execution['epoch'])
    try:
        StageRunner(x).run()
        dto = app.build(x.build['id'])
        assert dto['status'] == 'succeeded' and all(s['status'] == 'succeeded' for s in dto['stages'])
        result = x.read('solver', '执行检查与结果摘要')
        assert result['status'] == 'ok', result['errors']
        def leaves(value):
            if isinstance(value, dict):
                return [leaf for v in value.values() for leaf in leaves(v)]
            if isinstance(value, (list, tuple)):
                return [leaf for v in value for leaf in leaves(v)]
            return [sp.simplify(sp.sympify(value))]
        expected = json.loads((repo / 'server/tests/solver/expected/tj-2026-heping-yimo-25.expected.json').read_text())['expected']
        actual_values = leaves(result['answers'])
        for value in leaves(expected):
            found = next((i for i, other in enumerate(actual_values) if sp.simplify(other - value) == 0), None)
            assert found is not None, result['answers']
            actual_values.pop(found)
        assert not actual_values, result['answers']
        assert b'<html' in x.bytes('page', 'page_html')
        assert dto['pipeline_version'] == 'v3'
        workflow = next(a for a in dto['artifacts'] if a['name'] == 'problem-math-workflow.json')
        binding = next(a for a in dto['artifacts'] if a['name'] == 'binding-result.json')
        review = next(a for a in dto['artifacts'] if a['name'] == 'problem-math-source-review.json')
        from shuxueshuo_server.product.db import transaction
        with transaction(app.db) as c:
            assert service.artifacts.verified(c, ctx, UUID(workflow['id']))['schema_version'] == 'problem-math-workflow/v1'
            assert service.artifacts.verified(c, ctx, UUID(binding['id']))['schema_version'] == 'math-runtime-binding/v1'
            assert service.artifacts.verified(c, ctx, UUID(review['id']))['schema_version'] == 'problem-math-source-review/v1'
        workflow_payload = x.read('extraction', 'problem-math-workflow.json')
        assert workflow_payload.get('status') == 'reviewed_candidate'
        assert workflow_payload.get('source_reviewed') is True
        assert x.read('projection', 'binding-result.json').get('schema_version') == 'math-runtime-binding/v1'
    except Exception:
        if app.build(x.build['id'])['status'] not in {'succeeded', 'failed', 'cancelled'}:
            service.finish_failure(*x.args, 'test.live_acceptance_failed')
        raise
    finally:
        output = Path(os.environ.get('SOURCE_REVIEW_PRODUCT_OUTPUT', str(tmp_path)))
        output.mkdir(parents=True, exist_ok=True)
        (output / 'build-result.json').write_text(json.dumps(app.build(x.build['id']), ensure_ascii=False, indent=2))
