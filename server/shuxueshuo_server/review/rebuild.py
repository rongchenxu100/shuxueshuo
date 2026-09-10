"""Read-only rebuild previews and explicit, optimistic build submission."""
from . import dependencies as deps
from .replay import availability
from .versions import Versions, Conflict


def plan(store, run_id, requested_stage=None, *, snapshot=None):
    versions = Versions(store)
    versions.capture(run_id)
    info = versions.info(run_id)
    doc = store.get(run_id)
    snapshot = snapshot or deps.probe()
    reasons = deps.changes(doc, snapshot)
    revision = versions.revision(info['revision_id'])
    if info['revision_id'] != info['run_revision_id']:
        reasons.append({'stage': 'extraction', 'code': 'build.problem_changed', 'message': '题意修订变化；重新校验、晋升并生成 Context'})
    for stage in doc['stages']:
        if stage['status'] != 'succeeded':
            reasons.append({'stage': stage['id'], 'code': 'build.incomplete', 'message': '阶段尚未成功'})
    if requested_stage is not None and requested_stage not in deps.KEYS: raise ValueError('未知重跑阶段')
    indexes = [deps.KEYS.index(r['stage']) for r in reasons]
    if requested_stage: indexes.append(deps.KEYS.index(requested_stage))
    start = min(indexes) if indexes else len(deps.KEYS)
    options = availability(store, doc)
    # Missing recovery archives widen the plan before the user authorizes it.
    while start > 0 and start < len(deps.KEYS) and not options[deps.KEYS[start]]['available']:
        reasons.append({'stage': deps.KEYS[start - 1], 'code': 'build.recovery_missing', 'message': options[deps.KEYS[start]]['reason']})
        start -= 1
    rerun = list(deps.KEYS[start:])
    manual = bool(revision and revision['kind'] == 'manual')
    model_stages = [s for s in rerun if s in {'extraction', 'solver', 'lesson'} and not (manual and s == 'extraction')]
    body = {'schema_version': 'review-rebuild-plan/v1', 'run_id': run_id, 'subject_id': info['id'],
            'base_revision_id': info['revision_id'], 'requested_stage': requested_stage,
            'target': snapshot, 'reuse_stages': list(deps.KEYS[:start]), 'rerun_stages': rerun,
            'reasons': reasons, 'model_stages': model_stages, 'calls_models': bool(model_stages),
            'available': (doc['status'] in {'succeeded', 'failed', 'interrupted'} or requested_stage == 'source') and bool(rerun),
            'page_validity': 'unknown' if any(r['code'] == 'build.version_unknown' for r in reasons) else 'stale' if reasons or info['latest_run_id'] != run_id else 'current',
            'latest_run_id': info['latest_run_id'], 'page_run_id': info['page_run_id']}
    return {**body, 'fingerprint': deps.digest(body)}


def submit(store, run_id, body):
    preview = plan(store, run_id, body.get('requested_stage'))
    if body.get('base_revision_id') != preview['base_revision_id'] or body.get('fingerprint') != preview['fingerprint']:
        raise Conflict('题意、配置或输入已变化，请刷新影响范围后再重建')
    if not preview['available']: raise Conflict('没有可提交的重建计划，请等待运行结束或选择重跑阶段')
    child = store.rerun(run_id, None if preview['rerun_stages'][0] == 'source' else preview['rerun_stages'][0], enqueue=False)
    try:
        current = deps.probe()
        if current != preview['target']: raise Conflict('准备期间依赖变化，请刷新重建计划')
        with store.edit(child['id']) as doc:
            doc['rebuild_plan'] = preview
        Versions(store).enqueue(child['id'], base_revision_id=preview['base_revision_id'], target=preview['target'])
    except Exception as exc:
        store.finish(child['id'], error=str(exc))
        raise
    return store.get(child['id'])


class BuildGuard:
    def __init__(self, store, run_id):
        self.store, self.run_id = store, run_id
        doc = store.get(run_id)
        self.target = doc.get('target_dependencies') or deps.probe()
        with store.edit(run_id) as doc: doc['target_dependencies'] = self.target
        self.check()
        # All retained stages must prove their versions and input integrity.
        before = deps.KEYS[:deps.KEYS.index(doc.get('from_stage', 'source'))]
        invalid = [r for r in deps.changes(doc, self.target) if r['stage'] in before]
        if invalid: self.fail(invalid)
        for ref in doc['artifacts']:
            if ref['stage'] in before: store.read(run_id, ref['id'])

    def fail(self, reasons):
        self.store.add(self.run_id, 'page', 'validation', '构建依赖变化证据', {'target': self.target, 'reasons': reasons})
        raise ValueError('build.source_changed: 构建依赖已变化，请刷新影响范围后重新构建')

    def check(self):
        current = deps.probe()
        if current['stages'] != self.target['stages']:
            self.fail([{'stage': s, 'expected': self.target['stages'][s], 'observed': current['stages'][s]}
                       for s in deps.KEYS if current['stages'][s] != self.target['stages'][s]])

    def complete(self, stage):
        self.check()
        value = deps.manifest(self.store.get(self.run_id), stage, self.target)
        self.store.add(self.run_id, stage, 'validation', '阶段依赖 manifest/v1', value)
        with self.store.edit(self.run_id) as doc:
            next(s for s in doc['stages'] if s['id'] == stage)['manifest'] = value
