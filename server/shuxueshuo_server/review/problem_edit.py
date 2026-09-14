"""Human domain revisions use full validation/promotion, never a repair patch."""
import json
import subprocess
import sys

from .dependencies import KEYS
from .replay import read_json, find, save_archive
from .store import REPO
from .versions import Versions, Conflict


def editable(store, run_id):
    versions = Versions(store)
    versions.capture(run_id)
    info = versions.info(run_id)
    revision = versions.revision(info['revision_id'])
    if revision is None: raise ValueError('尚无通过验证的题意；请先完成题意抽取')
    return {'base_revision_id': revision['id'], 'domain': revision['domain'],
            'schema': json.loads((REPO / 'internal/schemas/problem-domain.schema.json').read_text())}


def diff(before, after, path='$'):
    if before == after: return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [item for key in sorted(before.keys() | after.keys())
                for item in diff(before.get(key), after.get(key), path + '.' + key)]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [item for i, (a, b) in enumerate(zip(before, after)) for item in diff(a, b, f'{path}[{i}]')]
    return [{'path': path, 'before': before, 'after': after}]


def validate(domain, base):
    from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft, ProblemPromotionService
    from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
    draft = ProblemDraft.create(domain, parent_revision_id=base['verified']['revision_id'])
    result = ProblemDomainValidator().validate(draft, expected_problem_id=base['domain']['problem_id'])
    verified = ProblemPromotionService().promote(result.draft) if result.ok else None
    return result, verified


def preview(store, run_id, body, *, save=False):
    versions = Versions(store)
    current = editable(store, run_id)
    if body.get('base_revision_id') != current['base_revision_id']: raise Conflict('基础修订已过期，请刷新题意')
    base = versions.revision(current['base_revision_id'])
    try:
        process = subprocess.run([sys.executable, '-m', 'shuxueshuo_server.review.problem_edit'],
            input=json.dumps({'domain': body.get('domain'), 'base': base}), text=True,
            capture_output=True, cwd=REPO / 'server', timeout=60)
        if process.returncode: raise ValueError('题意校验进程失败，请检查当前合同或代码')
        checked = json.loads(process.stdout)
        if checked.get('error'): raise ValueError(checked['error'])
    except ValueError as exc:
        return {'ok': False, 'diagnostics': [{'code': getattr(exc, 'code', 'problem.invalid'), 'path': getattr(exc, 'path', '$'), 'message': str(exc)}], 'diff': []}
    normalized = checked['domain']
    differences = diff(base['domain'], normalized)
    response = {'ok': checked['ok'], 'diagnostics': checked['validation'], 'diff': differences,
                'domain': normalized, 'base_revision_id': base['id'],
                'affected_stages': list(KEYS[2:]) if checked['semantic_hash'] != base['semantic_hash'] else []}
    if save and checked['ok']:
        revision = versions.save(run_id, base['id'], {'kind': 'manual', 'source_run_id': base['source_run_id'],
            'domain': normalized, 'semantic_hash': checked['semantic_hash'], 'verified': checked['verified'],
            'draft': checked['draft'], 'validation': checked['validation'], 'diff': differences})
        response['base_revision_id'] = revision['id']
    return response


def load_contexts(store, run_id):
    from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
    initial = ProblemExtractionContext.from_payload(read_json(store, run_id, 'source', 'Source / selection / initial Context'))
    observation = ProblemExtractionContext.from_payload(read_json(store, run_id, 'observation', 'Observation Context'), ancestor_contexts=(initial,))
    ancestors = [initial, observation]
    if find(store.get(run_id), 'extraction', 'Extraction Context ancestry'):
        for raw in read_json(store, run_id, 'extraction', 'Extraction Context ancestry'):
            if raw['manifest']['context_id'] not in {c.manifest.context_id for c in ancestors}:
                ancestors.append(ProblemExtractionContext.from_payload(raw, ancestor_contexts=tuple(ancestors)))
    final = ProblemExtractionContext.from_payload(read_json(store, run_id, 'extraction', 'Extraction Context'), ancestor_contexts=tuple(ancestors))
    return final, tuple(ancestors)


def install(store, run_id, revision, context, ancestors, artifact_store):
    from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
    from shuxueshuo_server.solver.extraction.problem_domain_context import ProblemDomainContextTransitionService
    from shuxueshuo_server.solver.extraction.problem_solver_bundle import VerifiedSolverProblemBundleLoader
    from shuxueshuo_server.solver.extraction.context import SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND
    # Revalidate against this build's code. The domain's parent comes from the
    # saved revision, without adding any provider call or retry permission.
    versions = Versions(store)
    base = versions.revision(revision['parent_id'])
    result, verified = validate(revision['domain'], base)
    store.add(run_id, 'extraction', 'validation', '人工修订完整校验', result.report.to_payload())
    if not verified: raise ValueError('problem.revalidation_failed: 人工题意未通过当前合同')
    def put(kind, value): return artifact_store.put_json(kind=kind, payload=value)
    final = ProblemDomainContextTransitionService().accepted(context,
        verified_problem=verified, solver_projection=result.projection,
        verified_artifact=put('verified_problem', verified.to_payload()),
        solver_problem_projection_artifact=put(SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND, result.projection.to_payload()),
        validation_artifact=put('problem_validation_report', result.report.to_payload()),
        attempt_ledger=ExtractionAttemptLedger.for_context(context), ancestor_contexts=ancestors,
        producer='review_human_revision')
    VerifiedSolverProblemBundleLoader().load(final, artifact_store, ancestor_contexts=(*ancestors, context))
    store.add(run_id, 'extraction', 'input', '人工修订及差异', revision)
    store.add(run_id, 'extraction', 'output', 'Extraction Context ancestry', [a.to_payload() for a in (*ancestors, context)])
    store.add(run_id, 'extraction', 'output', 'Extraction Context', final.to_payload())
    store.add(run_id, 'extraction', 'output', 'VerifiedProblem', verified.to_payload())
    save_archive(store, run_id, 'extraction')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        result, verified = validate(request['domain'], request['base'])
        print(json.dumps({'ok': result.ok, 'domain': result.draft.graph.wire_payload(),
            'semantic_hash': result.draft.semantic_hash, 'draft': result.draft.to_payload(),
            'validation': result.report.to_payload(), 'verified': verified.to_payload() if verified else None}))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}))
