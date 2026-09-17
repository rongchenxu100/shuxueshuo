"""PostgreSQL reservations and immutable responses for the shared state machine."""
import json
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select

from shuxueshuo_server.problem_understanding.workflow_ledger import WorkflowStop
from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef

from . import models as m
from .db import digest, transaction
from .errors import IntegrityFailure
from .repositories import insert, problem, row, scoped
from .services import append_event, now, update


class CandidateArtifacts:
    """Buffer compilation outputs before the edit's compare-and-swap transaction."""
    def __init__(self, candidate_id):
        self.candidate_id, self.values = candidate_id, {}

    def put_bytes(self, *, kind, content, media_type, suffix):
        hashed = sha256(content).hexdigest()
        aid = uuid5(self.candidate_id, kind + hashed)
        self.values[aid] = (kind, content, media_type, hashed)
        return ExtractionArtifactRef(artifact_id=str(aid), kind=kind, sha256=hashed,
            media_type=media_type, byte_size=len(content))

    def put_json(self, *, kind, payload):
        return self.put_bytes(kind=kind, content=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
            media_type='application/json', suffix='.json')

    def persist(self, service, ctx, c):
        for aid, (kind, content, media_type, hashed) in self.values.items():
            key = f'workspaces/{ctx.workspace_id}/candidates/{self.candidate_id}/{aid}'
            saved = service.storage.put_immutable(key, BytesIO(content), hashed)
            service.artifacts.register({'id': aid, 'workspace_id': ctx.workspace_id, 'owner_user_id': ctx.user_id,
                'artifact_type': kind, 'storage_key': key, 'sha256': hashed, 'size_bytes': saved.size_bytes,
                'content_type': media_type, 'access_class': 'private'}, c)


class DatabaseWorkflowStorage:
    def __init__(self, context, run):
        self.x, self.run = context, run
        self.service, self.ctx = context.service, context.ctx
        self.db = self.service.db
        self.artifacts = self

    def ledger(self, binding, budget):
        return DatabaseLedger(self, binding, budget)

    def guard(self, connection=None):
        if connection is None:
            self.x.guard()
            with transaction(self.db) as c:
                return self.guard(c)
        c = connection
        p = problem(c, self.ctx, self.run['problem_id'], write=True, lock=True)
        run = scoped(c, m.extraction_runs, self.ctx, self.run['id'], lock=True)
        if (p['latest_extraction_run_id'] != run['id'] or p['understanding_generation'] != run['generation']
                or p['current_source_version_id'] != run['source_version_id']
                or run['status'] not in ('queued', 'running')):
            raise WorkflowStop('workflow.superseded')
        self.service._guard(c, *self.x.args)
        return run

    def put(self, name, content, media_type='application/json', *, identity=None, attempt_id=None):
        """Stable artifact identities permit recovery after file write / DB commit gaps."""
        hashed = sha256(content).hexdigest()
        aid = identity or uuid5(NAMESPACE_URL, f'{self.ctx.workspace_id}/{self.run["id"]}/{name}/{hashed}')
        key = f'workspaces/{self.ctx.workspace_id}/builds/{self.run["build_id"]}/{aid}'
        saved = self.service.storage.put_immutable(key, BytesIO(content), hashed)
        with transaction(self.db) as c:
            prior = row(c, m.artifacts, id=aid)
            if prior:
                if prior['sha256'] != hashed or prior['producer_build_id'] != self.run['build_id']:
                    raise IntegrityFailure('understanding.artifact_conflict')
                return dict(self.service.artifacts.verified(c, self.ctx, aid))
            value = self.service.artifacts.register({'id': aid, 'workspace_id': self.ctx.workspace_id,
                'owner_user_id': self.ctx.user_id, 'producer_build_id': self.run['build_id'],
                'producer_attempt_id': attempt_id or self.x.attempt['id'], 'artifact_type': name,
                'storage_key': key, 'sha256': hashed, 'size_bytes': saved.size_bytes, 'content_type': media_type, 'access_class': 'private'}, c)
            append_event(c, self.ctx.workspace_id, 'build', self.run['build_id'], 'artifact.registered',
                {'stage_key': 'extraction', 'artifact_id': str(aid), 'name': name, 'role': 'raw' if 'response' in name else 'validation'})
            return dict(value)

    def put_bytes(self, *, kind, content, media_type, suffix):
        artifact = self.put(kind, content, media_type)
        return ExtractionArtifactRef(artifact_id=str(artifact['id']), kind=kind, sha256=artifact['sha256'],
            media_type=media_type, byte_size=len(content))

    def put_json(self, *, kind, payload):
        return self.put_bytes(kind=kind, content=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
            media_type='application/json', suffix='.json')

    def save(self, name, value):
        artifact = self.put(name, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
        if name == 'workflow-result.json':
            with transaction(self.db) as c:
                # Even a fenced response can be audited, but never becomes current.
                problem(c, self.ctx, self.run['problem_id'], write=True, lock=True)
                run = scoped(c, m.extraction_runs, self.ctx, self.run['id'], lock=True)
                if run['status'] in ('queued', 'running'):
                    update(c, m.extraction_runs, run['id'], result_json=value)
                for diagnostic in value.get('diagnostics', []):
                    did = uuid5(artifact['id'], digest(diagnostic))
                    if not row(c, m.diagnostics, id=did):
                        insert(c, m.diagnostics, id=did, workspace_id=self.ctx.workspace_id, build_id=run['build_id'],
                            stage_attempt_id=artifact['producer_attempt_id'], code=diagnostic.get('code', 'understanding.blocked'),
                            severity='warning' if diagnostic.get('action') == 'needs_confirmation' else 'error',
                            message=diagnostic.get('message', diagnostic.get('code', '题意待确认')),
                            details=diagnostic, evidence_artifact_id=artifact['id'])

    def proposed(self, candidate, parsed, number):
        with transaction(self.db) as c:
            # A late response remains in the call audit, not in candidate history.
            run = self.guard(c)
            prior = row(c, m.problem_candidates, origin_run_id=run['id'], call_number=number)
            if prior:
                if prior['candidate_hash'] != digest(candidate):
                    raise IntegrityFailure('candidate.replay_conflict')
                return prior
            call = row(c, m.extraction_call_reservations, run_id=run['id'], number=number)
            return insert(c, m.problem_candidates, workspace_id=self.ctx.workspace_id, problem_id=run['problem_id'],
                source_version_id=run['source_version_id'], parent_candidate_id=run['candidate_id'] or run['base_candidate_id'],
                kind='model', candidate_json=candidate, candidate_hash=digest(candidate), contract_version='problem-math-notation/v1',
                validation_json=parsed, raw_artifact_id=call['response_artifact_id'], origin_run_id=run['id'], call_number=number,
                created_by_user_id=self.ctx.user_id)

    def adopt(self, candidate, parsed, number):
        with transaction(self.db) as c:
            run = self.guard(c)
            value = row(c, m.problem_candidates, origin_run_id=run['id'], call_number=number)
            previous = row(c, m.problem_candidates, id=run['candidate_id']) if run['candidate_id'] else None
            # Replaying completed calls must not move the current pointer backwards.
            if previous and previous['origin_run_id'] == run['id'] and previous['call_number'] >= number:
                return
            update(c, m.extraction_runs, run['id'], candidate_id=value['id'])
            update(c, m.problems, run['problem_id'], current_candidate_id=value['id'], updated_at=now(c))
            append_event(c, self.ctx.workspace_id, 'problem', run['problem_id'], 'understanding.candidate_adopted',
                {'run_id': str(run['id']), 'candidate_id': str(value['id'])})


class DatabaseLedger:
    def __init__(self, storage, binding, budget):
        self.store, self.binding, self.budget = storage, binding, budget
        self.position = 0

    def __enter__(self):
        s = self.store
        with transaction(s.db) as c:
            run = s.guard(c)
            identity = {'binding': self.binding, 'budget': asdict(self.budget)}
            if run['workflow_binding'] is not None and run['workflow_binding'] != identity:
                raise WorkflowStop('workflow.stale_binding')
            if run['workflow_binding'] is None:
                update(c, m.extraction_runs, run['id'], workflow_binding=identity)
        return self

    def __exit__(self, *_):
        pass

    def entries(self, c):
        return list(c.execute(select(m.extraction_call_reservations).where(
            m.extraction_call_reservations.c.run_id == self.store.run['id']).order_by(m.extraction_call_reservations.c.number)).mappings())

    def counts(self):
        with transaction(self.store.db) as c:
            entries = self.entries(c)
        return {'semantic_calls': len(entries), 'content_calls': sum(e['stage'] != 'review' for e in entries),
            'review_calls': sum(e['stage'] == 'review' for e in entries),
            'network_attempts': sum((e['details'] or {}).get('network_attempts', 0) for e in entries),
            'network_reserved': sum((e['details'] or {}).get('network_attempts', 2) for e in entries),
            'file_api_calls': sum((e['details'] or {}).get('file_api_calls', 0) for e in entries)}

    def complete(self, stage, request, base_revision, provider):
        s = self.store
        s.guard()
        prepared = provider.prepare_request(request)
        wire = s.x.redact(prepared.redacted_payload())
        key = {'stage': stage, 'request_hash': digest(wire), 'base_revision': base_revision}
        self.position += 1
        with transaction(s.db) as c:
            s.guard(c)
            entries = self.entries(c)
            entry = next((e for e in entries if e['number'] == self.position), None)
            recovered = entry is not None
            if entry:
                if any(entry[k] != v for k, v in key.items()):
                    raise WorkflowStop('workflow.stale_response')
            else:
                group = 'review' if stage == 'review' else 'content'
                used = sum((e['stage'] == 'review') == (group == 'review') for e in entries)
                if (len(entries) >= self.budget.semantic or used >= getattr(self.budget, group)
                        or sum((e['details'] or {}).get('network_attempts', 2) for e in entries) + 2 > self.budget.network):
                    raise WorkflowStop('workflow.budget_exhausted')
                request_artifact = s.put(f'{self.position:02d}-{stage}-request', json.dumps(wire, ensure_ascii=False).encode())
                response_id = uuid4()
                entry = insert(c, m.extraction_call_reservations, workspace_id=s.ctx.workspace_id, run_id=s.run['id'],
                    number=self.position, **key, status='reserved', request_artifact_id=request_artifact['id'],
                    receipt_key=f'workspaces/{s.ctx.workspace_id}/builds/{s.run["build_id"]}/{response_id}')
        entry = dict(entry)
        if entry['status'] == 'failed':
            raise WorkflowStop((entry['details'] or {}).get('error_code', 'workflow.provider_failed'))
        if recovered:
            receipt = self.read_receipt(entry)
            if receipt is None:
                raise WorkflowStop('workflow.outcome_unknown')
            return self.finish(entry, receipt)
        started = perf_counter()
        try:
            response = provider.complete(replace(prepared, transport_audit_directory=str(
                s.x.work / 'transport' / str(entry['id']))))
            attempts = [a.to_payload() if hasattr(a, 'to_payload') else a for a in response.provider_attempts]
            if not 1 <= len(attempts) <= 2:
                raise WorkflowStop('workflow.provider_network_budget')
            saved = s.x.redact({'text': response.text, 'finish_reason': response.finish_reason,
                'metadata': response.metadata_payload(), 'raw_payload': dict(response.raw_payload),
                'network_attempts': len(attempts), 'elapsed_seconds': round(perf_counter() - started, 3)})
        except Exception as exc:  # noqa: BLE001 - provider failures become durable sanitized audit records
            attempts = getattr(provider, 'last_provider_attempts', ())
            saved = {'error_code': 'workflow.provider_failed', 'error_type': type(exc).__name__,
                'network_attempts': min(2, len(attempts)) if attempts else 0 if getattr(provider, 'last_completion_started', None) is False else 2,
                'elapsed_seconds': round(perf_counter() - started, 3), 'metadata': {},
                'file_api_calls': sum(e['api_calls'] for e in getattr(provider, 'last_file_operations', ())) }
        receipt = {**key, 'number': self.position, 'run_id': str(s.run['id']), 'response': saved, 'response_hash': digest(saved)}
        # Receipt is durable independently of the database commit and execution lease.
        s.service.storage.put_immutable(entry['receipt_key'], BytesIO(json.dumps(receipt, ensure_ascii=False).encode()))
        # Keep resolved Files API requests alongside the logical pre-send request.
        directory = s.x.work / 'transport' / str(entry['id'])
        for path in sorted(directory.rglob('*.json')):
            payload = s.x.redact(json.loads(path.read_text()))
            s.put(f'{self.position:02d}-{stage}-transport/{path.relative_to(directory).as_posix()}',
                  json.dumps(payload, ensure_ascii=False).encode())
        return self.finish(entry, receipt)

    def read_receipt(self, entry):
        try:
            with self.store.service.storage.open(entry['receipt_key']) as stream:
                receipt = json.load(stream)
        except FileNotFoundError:
            return None
        for key in ('stage', 'request_hash', 'base_revision', 'number'):
            if receipt.get(key) != entry[key]:
                raise WorkflowStop('workflow.response_hash_mismatch')
        if receipt.get('run_id') != str(self.store.run['id']):
            raise WorkflowStop('workflow.response_hash_mismatch')
        if receipt.get('response_hash') != digest(receipt.get('response')):
            raise WorkflowStop('workflow.response_hash_mismatch')
        return receipt

    def finish(self, entry, receipt):
        s = self.store
        saved = receipt['response']
        with transaction(s.db) as c:
            # Recording a late response does not grant permission to adopt it.
            current = scoped(c, m.extraction_call_reservations, s.ctx, entry['id'], lock=True)
            if current['status'] != 'reserved':
                art = s.service.artifacts.verified(c, s.ctx, current['response_artifact_id'])
                with s.service.storage.open(art['storage_key']) as stream:
                    if json.load(stream) != receipt:
                        raise WorkflowStop('workflow.response_hash_mismatch')
            else:
                request_artifact = scoped(c, m.artifacts, s.ctx, entry['request_artifact_id'])
                attempt_id = request_artifact['producer_attempt_id']
                response_artifact = s.put(f'{entry["number"]:02d}-{entry["stage"]}-response',
                    json.dumps(receipt, ensure_ascii=False).encode(), identity=UUID(entry['receipt_key'].split('/')[-1]), attempt_id=attempt_id)
                metadata = saved.get('metadata', {})
                usage = metadata.get('usage') or {}
                failed = 'error_code' in saved
                call = insert(c, m.model_calls, workspace_id=s.ctx.workspace_id, origin_attempt_id=attempt_id,
                    call_kind=entry['stage'], status='failed' if failed else 'succeeded',
                    provider=metadata.get('provider'), request_model=metadata.get('request_model'), response_model=metadata.get('response_model'),
                    audit_artifact_id=response_artifact['id'], request_artifact_id=entry['request_artifact_id'], response_artifact_id=response_artifact['id'],
                    duration_ms=int(saved['elapsed_seconds'] * 1000), usage_json=usage,
                    input_tokens=usage.get('prompt_tokens', usage.get('input_tokens')),
                    output_tokens=usage.get('completion_tokens', usage.get('output_tokens')))
                insert(c, m.stage_call_refs, workspace_id=s.ctx.workspace_id, stage_attempt_id=attempt_id,
                    model_call_id=call['id'], relation='executed')
                details = {k: saved[k] for k in ('elapsed_seconds', 'network_attempts', 'finish_reason', 'error_code', 'error_type') if k in saved}
                details.update(usage=usage, file_api_calls=metadata.get('file_api_calls', saved.get('file_api_calls', 0)))
                update(c, m.extraction_call_reservations, entry['id'], status='failed' if failed else 'completed',
                    response_artifact_id=response_artifact['id'], model_call_id=call['id'], details=details)
                append_event(c, s.ctx.workspace_id, 'build', s.run['build_id'], 'understanding.call_completed',
                    {'run_id': str(s.run['id']), 'number': entry['number'], 'stage': entry['stage']})
        if 'error_code' in saved:
            raise WorkflowStop(saved['error_code'])
        return saved
