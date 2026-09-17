"""Image-only product adapter; never projects a candidate into Solver inputs."""
import json
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from shuxueshuo_server.problem_understanding import notation_contract as contract
from shuxueshuo_server.problem_understanding.workflow import frozen_files, run_workflow
from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
    MultimodalImageInput,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider,
    MultimodalExtractionPrompt,
    MultimodalProviderImage,
    MultimodalProviderRequest,
)

from . import models as m
from .db import digest, transaction
from .errors import Conflict, IntegrityFailure, ProductError
from .repositories import row, scoped
from .services import append_event, now, update
from .understanding import registry


def configuration():
    return {'files': frozen_files(), 'registry': registry(), 'contract': contract.CONTRACT,
        'provider': {'model': 'deepseek-flash', 'timeout': 300, 'max_tokens': 16384, 'image_transport': 'files',
                     'thinking_mode': 'enabled', 'reasoning_effort': 'low'},
        'budget': {'content': 3, 'review': 3, 'semantic': 6, 'network': 12}}


def target_dependencies(source, candidate_id, config=None):
    from .application import deployment_version
    config = config or configuration()
    inputs = {'source_version_id': str(source['id']), 'source_hash': source['source_hash'],
              'candidate_id': str(candidate_id) if candidate_id else None}
    source_dep = {'inputs': inputs, 'resources': {}, 'config': {}, 'upstream': {}}
    extract_dep = {'inputs': inputs, 'resources': {'files': config['files'], 'registry': digest(config['registry'])},
                   'config': config['provider'], 'upstream': {'source': digest(source_dep)}}
    return {'dependencies': {'source': source_dep, 'extraction': extract_dep},
            'config': {'source': {}, 'extraction': config}, 'deployment_version': deployment_version()}


def build_request(service, ctx, source, families):
    images = []
    for index, item in enumerate(source['images']):
        with transaction(service.db) as c:
            artifact = service.artifacts.verified(c, ctx, UUID(item['artifact_id']))
        with service.storage.open(artifact['storage_key']) as stream:
            content = stream.read()
        if sha256(content).hexdigest() != item['sha256']:
            raise IntegrityFailure('source.hash_mismatch')
        ref = ExtractionArtifactRef(artifact_id=str(artifact['id']), kind='understanding_primary',
            sha256=item['sha256'], media_type=item['media_type'], byte_size=len(content))
        images.append(MultimodalProviderImage('primary', f'page-{index + 1}', 'primary', ref,
            content, item['width'], item['height']))
    pack = MultimodalEvidencePack(schema_version='multimodal-evidence-pack/v1', evidence_pack_id=str(source['id']),
        base_context_id=str(source['id']), source_id=str(source['id']), source_revision_hash=source['source_hash'],
        selection_id='whole-images', observation_hash=digest({}), images=tuple(
            MultimodalImageInput(i.role, i.page_id, i.role, i.artifact, i.width, i.height) for i in images),
        printed_text=(), recognized_formulas=(), unresolved_items=(), region_index=())
    payload = {'registered_families': families, 'response_schema': contract.schema(),
               'math_expression_catalog': contract.expression_catalog()}
    return MultimodalProviderRequest(evidence_pack=pack, images=tuple(images),
        prompt=MultimodalExtractionPrompt(contract.SYSTEM, json.dumps(payload, ensure_ascii=False), contract.USER_SUFFIX),
        contract_version=contract.CONTRACT, contract_schema=payload['response_schema'], response_format={'type': 'json_object'})


class ValidationOnlyProvider:
    def prepare_request(self, request):
        return replace(request, timeout=300, max_tokens=16384)

    def complete(self, request):
        raise AssertionError('validate must never call a model')


def run_product(x, provider=None):
    """Two stages, with the same durable workflow used by command-line batches."""
    from .understanding_storage import DatabaseWorkflowStorage
    with transaction(x.service.db) as c:
        run = dict(row(c, m.extraction_runs, build_id=x.build['id']))
        source = dict(scoped(c, m.problem_source_versions, x.ctx, run['source_version_id']))
        candidate = row(c, m.problem_candidates, id=run['base_candidate_id']) if run['base_candidate_id'] else None
    if run['frozen'] != configuration():
        raise Conflict('understanding.environment_changed')
    # Completed stage restoration remains available after process recovery.
    with transaction(x.service.db) as c:
        stage = row(c, m.build_stages, build_id=x.build['id'], stage_key='source')
        accepted = row(c, m.stage_attempts, id=stage['accepted_attempt_id']) if stage['accepted_attempt_id'] else None
    if accepted:
        x.restore(stage, accepted)
    else:
        x.begin('source')
        x.add('source-version.json', jsonable_encoder(source))
        x.complete('完整有序题图已绑定')
    with transaction(x.service.db) as c:
        stage = row(c, m.build_stages, build_id=x.build['id'], stage_key='extraction')
        accepted = row(c, m.stage_attempts, id=stage['accepted_attempt_id']) if stage['accepted_attempt_id'] else None
    if accepted:
        x.restore(stage, accepted)
        x.stage_key, x.attempt = 'extraction', accepted
    else:
        x.begin('extraction')
    store = DatabaseWorkflowStorage(x, run)
    store.guard()
    with transaction(x.service.db) as c:
        update(c, m.extraction_runs, run['id'], status='running')
    if accepted:
        result = x.read('extraction', 'workflow-result.json')
        return finish_product(x, run, store, result)
    request = build_request(x.service, x.ctx, source, run['frozen']['registry'])
    if provider is None:
        if run['mode'] == 'validate':
            provider = ValidationOnlyProvider()
        else:
            if not x.config.deepseek_api_key:
                raise ProductError('configuration.extraction_key_missing')
            provider = DeepSeekMultimodalExtractionProvider(api_key=x.config.deepseek_api_key,
                base_url='https://api.deepseek.com', model='deepseek-flash', request_timeout=300, max_output_tokens=16384,
                file_cache_dir=x.app.settings.root / 'deepseek-files-cache')
    result = run_workflow(request, provider, x.work, run['frozen']['registry'], problem_id=str(run['problem_id']),
        storage=store, initial_candidate=candidate['candidate_json'] if candidate else None,
        mode=run['mode'], source_hash=source['source_hash'])
    store.guard()
    x.add('workflow-result.json', result, schema='problem-math-workflow/v1')
    x.complete('题意已保存：' + result['status'])
    return finish_product(x, run, store, result)


def finish_product(x, run, store, result):
    """Finish processing, not approval or page generation; replayable from the checkpoint.

    A normal stop succeeds as a task even when the candidate needs confirmation.
    Consumers must use the understanding summary for candidate readiness.
    """
    with transaction(x.service.db) as c:
        store.guard(c)
        normal_stops = {'workflow.budget_exhausted', 'workflow.no_progress', 'workflow.oscillation'}
        failed = result['status'].startswith(('workflow.', 'review.')) and result['status'] not in normal_stops
        status = 'failed' if failed else 'completed'
        update(c, m.extraction_runs, run['id'], status=status, result_json=result, finished_at=now(c),
            error_code=result['status'] if failed else None)
        for table, identity in ((m.builds, x.build['id']), (m.jobs, row(c, m.jobs, build_id=x.build['id'])['id']),
                                (m.job_executions, x.args[2])):
            values = {'status': 'failed' if failed else 'succeeded'}
            if table is not m.jobs:
                values['finished_at'] = now(c)
            else:
                values['lease_expires_at'] = None
            if table is m.builds:
                values['error_code'] = result['status'] if failed else None
            update(c, table, identity, **values)
        append_event(c, x.ctx.workspace_id, 'build', x.build['id'], 'understanding.finished',
            {'run_id': str(run['id']), 'outcome': result['status'], 'source_reviewed': result['source_reviewed']})
        update(c, m.problems, run['problem_id'], updated_at=now(c))
        append_event(c, x.ctx.workspace_id, 'problem', run['problem_id'], 'understanding.finished',
            {'run_id': str(run['id']), 'outcome': result['status']})
    return result
