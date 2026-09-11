"""SQLAlchemy Core models. Alembic owns DDL; no create_all at runtime."""
from uuid import uuid4
from hashlib import sha256

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(naming_convention={
    'pk': 'pk_%(table_name)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'ix': 'ix_%(table_name)s_%(column_0_name)s', 'ck': 'ck_%(table_name)s_%(constraint_name)s',
})


def col(name, typ=sa.Text, nullable=False, default=None):
    return sa.Column(name, typ, nullable=nullable, server_default=default)


def uid(name, nullable=False):
    return col(name, UUID(as_uuid=True), nullable)


def stamp(name, nullable=True):
    return col(name, sa.DateTime(timezone=True), nullable)


def obj(name, nullable=False, default=None):
    return col(name, JSONB, nullable, default)


def num(name, nullable=False, default=None):
    return col(name, sa.BigInteger, nullable, default)


def table(name, *columns, workspace=True, updated=False):
    base = [sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
            col('created_at', sa.DateTime(timezone=True), default=sa.text('now()'))]
    if workspace:
        base += [uid('workspace_id')]
    if updated:
        base += [col('updated_at', sa.DateTime(timezone=True), default=sa.text('now()'))]
    t = sa.Table(name, metadata, *base, *columns)
    if workspace:
        unique(t, 'workspace_id', 'id')
        fk(t, ['workspace_id'], 'workspaces', ['id'])
    return t


def unique(t, *names):
    t.append_constraint(sa.UniqueConstraint(*names, name=short('uq_' + t.name + '_' + '_'.join(names))))


def short(name):
    return name if len(name) <= 60 else name[:49] + '_' + sha256(name.encode()).hexdigest()[:10]


def check(t, name, expr):
    t.append_constraint(sa.CheckConstraint(expr, name=name))


def choices(t, name, values):
    check(t, name, name + ' IN (' + ','.join(repr(x) for x in values.split()) + ')')


def fk(t, local, target, remote, deferred=False):
    name = short('fk_' + t.name + '_' + '_'.join(local))
    t.append_constraint(sa.ForeignKeyConstraint(local, [target + '.' + x for x in remote],
        name=name, ondelete='NO ACTION' if deferred else 'RESTRICT',
        deferrable=deferred, initially='DEFERRED' if deferred else None, use_alter=True))


def ref(t, column, target):
    fk(t, ['workspace_id', column], target, ['workspace_id', 'id'])


users = table('users', col('key'), col('display_name'), workspace=False, updated=True)
unique(users, 'key')
workspaces = table('workspaces', col('slug'), col('name'), workspace=False, updated=True)
unique(workspaces, 'slug')
check(workspaces, 'slug_nonempty', "length(trim(slug)) > 0")
workspace_members = sa.Table('workspace_members', metadata,
    sa.Column('workspace_id', UUID(as_uuid=True), primary_key=True),
    sa.Column('user_id', UUID(as_uuid=True), primary_key=True), col('role'),
    col('created_at', sa.DateTime(timezone=True), default=sa.text('now()')))
fk(workspace_members, ['workspace_id'], 'workspaces', ['id'])
fk(workspace_members, ['user_id'], 'users', ['id'])
choices(workspace_members, 'role', 'owner member')
batches = table('batches', uid('owner_user_id'), col('name', nullable=True), updated=True)
batch_items = table('batch_items', uid('batch_id'), col('position', sa.Integer), uid('problem_id'),
                    uid('source_id'), uid('initial_build_id', True))
unique(batch_items, 'batch_id', 'position')
sources = table('sources', uid('owner_user_id'), uid('original_artifact_id'),
    uid('normalized_artifact_id', True), col('filename'), col('media_type'), obj('metadata', default=sa.text("'{}'::jsonb")))
problems = table('problems', uid('owner_user_id'), uid('primary_source_id'), col('title', nullable=True),
    col('visibility', default='private'), uid('current_revision_id', True), uid('latest_build_id', True),
    uid('current_page_build_id', True), num('lock_version', default='0'), updated=True)
choices(problems, 'visibility', 'private workspace')
problem_sources = table('problem_sources', uid('problem_id'), uid('source_id'), uid('matched_revision_id', True),
    col('match_method'), uid('match_evidence_artifact_id', True))
unique(problem_sources, 'problem_id', 'source_id')
unique(problem_sources, 'workspace_id', 'problem_id', 'source_id')
choices(problem_sources, 'match_method', 'initial file_hash semantic manual')
problem_revisions = table('problem_revisions', uid('problem_id'), col('revision_no', sa.Integer),
    uid('parent_revision_id', True), col('kind'), obj('domain_json'), obj('verified_json'), col('semantic_hash'),
    col('schema_version'), obj('human_diff', True), uid('created_by_user_id'), uid('origin_build_id', True))
unique(problem_revisions, 'problem_id', 'revision_no')
unique(problem_revisions, 'workspace_id', 'problem_id', 'id')
choices(problem_revisions, 'kind', 'extracted manual')
check(problem_revisions, 'graph_consistent', "domain_json = verified_json->'graph' AND schema_version = domain_json->>'schema_version' AND semantic_hash = verified_json->>'semantic_hash'")
builds = table('builds', uid('problem_id'), uid('parent_build_id', True), uid('source_id'),
    uid('requested_revision_id', True), uid('resolved_revision_id', True), col('pipeline_key'), col('pipeline_version'),
    obj('pipeline_snapshot'), col('from_stage'), obj('target_dependencies'), col('target_fingerprint'),
    col('deployment_version'), obj('effective_config'), col('status'), stamp('started_at'), stamp('finished_at'), col('error_code', nullable=True))
unique(builds, 'workspace_id', 'problem_id', 'id')
choices(builds, 'status', 'initializing queued running succeeded failed interrupted cancelled')
jobs = table('jobs', uid('build_id'), col('status'), num('execution_epoch', default='0'), uid('active_execution_id', True),
    stamp('lease_expires_at'), stamp('cancel_requested_at'), num('delivery_count', default='0'), obj('retry_budget'))
unique(jobs, 'build_id')
sa.Index('ix_jobs_expired_lease', jobs.c.lease_expires_at, jobs.c.id, postgresql_where=sa.text("status = 'running'"))
sa.Index('ix_batch_items_problem', batch_items.c.problem_id, batch_items.c.batch_id)
choices(jobs, 'status', 'queued running succeeded failed interrupted cancelled')
job_executions = table('job_executions', uid('job_id'), num('epoch'), col('worker_id'), col('status'),
    stamp('started_at', False), stamp('heartbeat_at', False), stamp('finished_at'), col('failure_code', nullable=True))
unique(job_executions, 'job_id', 'epoch')
unique(job_executions, 'workspace_id', 'job_id', 'id')
choices(job_executions, 'status', 'running succeeded failed interrupted cancelled')
build_stages = table('build_stages', uid('build_id'), col('stage_key'), col('ordinal', sa.SmallInteger),
    col('status'), uid('accepted_attempt_id', True), col('summary', nullable=True))
unique(build_stages, 'build_id', 'stage_key')
unique(build_stages, 'build_id', 'ordinal')
choices(build_stages, 'status', 'pending running succeeded failed blocked interrupted cancelled')
stage_attempts = table('stage_attempts', uid('build_stage_id'), uid('execution_id', True), col('attempt_no', sa.Integer),
    col('kind'), col('status'), stamp('started_at'), stamp('finished_at'), obj('manifest_json', True),
    uid('manifest_artifact_id', True), col('manifest_sha256', nullable=True), uid('checkpoint_artifact_id', True), uid('reused_from_attempt_id', True))
unique(stage_attempts, 'build_stage_id', 'attempt_no')
unique(stage_attempts, 'workspace_id', 'build_stage_id', 'id')
choices(stage_attempts, 'kind', 'executed reused')
choices(stage_attempts, 'status', 'running succeeded failed interrupted cancelled')
check(stage_attempts, 'execution_required', "(kind = 'executed' AND execution_id IS NOT NULL AND reused_from_attempt_id IS NULL) OR (kind = 'reused' AND reused_from_attempt_id IS NOT NULL)")
check(stage_attempts, 'success_evidence', "status <> 'succeeded' OR (manifest_json IS NOT NULL AND manifest_artifact_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND checkpoint_artifact_id IS NOT NULL)")
artifacts = table('artifacts', uid('owner_user_id'), uid('producer_build_id', True), uid('producer_attempt_id', True),
    col('artifact_type'), col('storage_key'), col('sha256'), num('size_bytes'), col('content_type'),
    col('schema_version', nullable=True), col('access_class'), col('availability', default='verified'))
unique(artifacts, 'storage_key')
choices(artifacts, 'access_class', 'private page')
choices(artifacts, 'availability', 'verified missing corrupt')
check(artifacts, 'page_types', "access_class <> 'page' OR artifact_type IN ('page_html','page_css','page_js','page_svg','page_image','page_font')")
stage_artifacts = table('stage_artifacts', uid('stage_attempt_id'), uid('artifact_id'), col('role'), col('name'),
    col('position', sa.Integer), uid('reused_from_artifact_id', True))
choices(stage_artifacts, 'role', 'input output raw validation configuration call')
unique(stage_artifacts, 'stage_attempt_id', 'role', 'name', 'position')
artifact_dependencies = table('artifact_dependencies', uid('artifact_id'), uid('depends_on_artifact_id'), col('kind'))
unique(artifact_dependencies, 'artifact_id', 'depends_on_artifact_id', 'kind')
choices(artifact_dependencies, 'kind', 'audit build_input reuse')
check(artifact_dependencies, 'not_self', 'artifact_id <> depends_on_artifact_id')
model_calls = table('model_calls', uid('origin_attempt_id'), col('provider', nullable=True), col('request_model', nullable=True),
    col('response_model', nullable=True), col('provider_version', nullable=True), col('provider_request_id', nullable=True),
    col('call_kind'), stamp('started_at'), num('duration_ms', True), col('status'), obj('usage_json', True),
    num('input_tokens', True), num('output_tokens', True), uid('request_artifact_id', True), uid('response_artifact_id', True), uid('audit_artifact_id'))
choices(model_calls, 'status', 'succeeded failed interrupted')
unique(model_calls, 'audit_artifact_id')
stage_call_refs = table('stage_call_refs', uid('stage_attempt_id'), uid('model_call_id'), col('relation'))
unique(stage_call_refs, 'stage_attempt_id', 'model_call_id')
choices(stage_call_refs, 'relation', 'executed reused')
diagnostics = table('diagnostics', uid('build_id'), uid('stage_attempt_id', True), col('code'), col('severity'),
    col('message'), obj('details', True), uid('evidence_artifact_id', True))
choices(diagnostics, 'severity', 'info warning error')
page_builds = table('page_builds', uid('build_id'), uid('revision_id'), uid('entry_artifact_id'),
    uid('package_manifest_artifact_id'), col('package_sha256'))
unique(page_builds, 'build_id')
unique(page_builds, 'workspace_id', 'id', 'revision_id')
page_assets = table('page_assets', uid('page_build_id'), col('relative_path'), uid('artifact_id'))
unique(page_assets, 'page_build_id', 'relative_path')
review_decisions = table('review_decisions', uid('page_build_id'), uid('revision_id'), uid('reviewer_user_id'),
    col('decision'), col('comment', nullable=True), uid('supersedes_id', True))
unique(review_decisions, 'workspace_id', 'page_build_id', 'id')
choices(review_decisions, 'decision', 'approved rejected revoked')
idempotency_requests = table('idempotency_requests', uid('user_id'), col('operation'), col('request_id'),
    col('request_hash'), col('resource_type', nullable=True), uid('resource_id', True), obj('response_json', True))
unique(idempotency_requests, 'workspace_id', 'user_id', 'operation', 'request_id')
event_streams = table('event_streams', col('stream_kind'), uid('aggregate_id'), num('last_seq', default='0'), num('min_retained_seq', default='1'))
unique(event_streams, 'workspace_id', 'stream_kind', 'aggregate_id')
events = table('events', uid('stream_id'), num('seq'), col('event_type'), col('schema_version'), obj('payload'))
unique(events, 'stream_id', 'seq')
outbox_messages = table('outbox_messages', uid('job_id'), col('message_type'), col('protocol_version'), obj('payload'),
    col('dedupe_key'), col('status', default='pending'), col('attempt_count', sa.Integer, default='0'),
    stamp('available_at', False), stamp('locked_until'), uid('publisher_token', True), stamp('published_at'), col('last_error', nullable=True))
unique(outbox_messages, 'dedupe_key')
choices(outbox_messages, 'status', 'pending publishing published failed')

# All resource references carry workspace identity, including nullable references.
references = {
    'batch_items': {'batch_id': 'batches', 'problem_id': 'problems', 'source_id': 'sources'},
    'sources': {'original_artifact_id': 'artifacts', 'normalized_artifact_id': 'artifacts'},
    'problems': {'primary_source_id': 'sources', 'current_page_build_id': 'page_builds'},
    'problem_sources': {'problem_id': 'problems', 'source_id': 'sources', 'match_evidence_artifact_id': 'artifacts'},
    'problem_revisions': {'problem_id': 'problems'}, 'builds': {'problem_id': 'problems', 'source_id': 'sources'},
    'jobs': {'build_id': 'builds'}, 'job_executions': {'job_id': 'jobs'}, 'build_stages': {'build_id': 'builds'},
    'stage_attempts': {'build_stage_id': 'build_stages', 'execution_id': 'job_executions', 'manifest_artifact_id': 'artifacts', 'checkpoint_artifact_id': 'artifacts', 'reused_from_attempt_id': 'stage_attempts'},
    'artifacts': {'producer_build_id': 'builds', 'producer_attempt_id': 'stage_attempts'},
    'stage_artifacts': {'stage_attempt_id': 'stage_attempts', 'artifact_id': 'artifacts', 'reused_from_artifact_id': 'artifacts'},
    'artifact_dependencies': {'artifact_id': 'artifacts', 'depends_on_artifact_id': 'artifacts'},
    'model_calls': {'origin_attempt_id': 'stage_attempts', 'request_artifact_id': 'artifacts', 'response_artifact_id': 'artifacts', 'audit_artifact_id': 'artifacts'},
    'stage_call_refs': {'stage_attempt_id': 'stage_attempts', 'model_call_id': 'model_calls'},
    'diagnostics': {'build_id': 'builds', 'stage_attempt_id': 'stage_attempts', 'evidence_artifact_id': 'artifacts'},
    'page_builds': {'build_id': 'builds', 'revision_id': 'problem_revisions', 'entry_artifact_id': 'artifacts', 'package_manifest_artifact_id': 'artifacts'},
    'page_assets': {'page_build_id': 'page_builds', 'artifact_id': 'artifacts'},
    'events': {'stream_id': 'event_streams'}, 'outbox_messages': {'job_id': 'jobs'},
}
for name, targets in references.items():
    for column, target in targets.items():
        ref(metadata.tables[name], column, target)
for t in list(metadata.tables.values()):
    for name in ('owner_user_id', 'created_by_user_id', 'reviewer_user_id', 'user_id'):
        if name in t.c and t is not workspace_members:
            fk(t, ['workspace_id', name], 'workspace_members', ['workspace_id', 'user_id'])
    for c in t.c:
        if c.name in ('sha256', 'semantic_hash', 'target_fingerprint', 'request_hash', 'manifest_sha256', 'package_sha256'):
            check(t, c.name + '_format', f"{c.name} ~ '^[0-9a-f]{{64}}$'")
        if isinstance(c.type, (sa.BigInteger, sa.Integer, sa.SmallInteger)):
            positive = c.name in ('position', 'ordinal', 'revision_no', 'attempt_no', 'epoch', 'seq', 'min_retained_seq')
            check(t, c.name + '_range', f'{c.name} >= {1 if positive else 0}')

for t, column, target in [
    (problems, 'current_revision_id', 'problem_revisions'), (problems, 'latest_build_id', 'builds'),
    (batch_items, 'initial_build_id', 'builds'), (problem_sources, 'matched_revision_id', 'problem_revisions'),
    (problem_revisions, 'parent_revision_id', 'problem_revisions'), (problem_revisions, 'origin_build_id', 'builds'),
    (builds, 'parent_build_id', 'builds'), (builds, 'requested_revision_id', 'problem_revisions'),
    (builds, 'resolved_revision_id', 'problem_revisions')]:
    fk(t, ['workspace_id', 'id' if t is problems else 'problem_id', column], target, ['workspace_id', 'problem_id', 'id'])
fk(problems, ['workspace_id', 'id', 'primary_source_id'], 'problem_sources', ['workspace_id', 'problem_id', 'source_id'], True)
for t in (batch_items, builds):
    fk(t, ['workspace_id', 'problem_id', 'source_id'], 'problem_sources', ['workspace_id', 'problem_id', 'source_id'])
fk(build_stages, ['workspace_id', 'id', 'accepted_attempt_id'], 'stage_attempts', ['workspace_id', 'build_stage_id', 'id'])
fk(jobs, ['workspace_id', 'id', 'active_execution_id'], 'job_executions', ['workspace_id', 'job_id', 'id'])
fk(review_decisions, ['workspace_id', 'page_build_id', 'revision_id'], 'page_builds', ['workspace_id', 'id', 'revision_id'])
fk(review_decisions, ['workspace_id', 'page_build_id', 'supersedes_id'], 'review_decisions', ['workspace_id', 'page_build_id', 'id'])

# FK indexes are explicit; PostgreSQL does not automatically create them.
for t in metadata.tables.values():
    for constraint in t.foreign_key_constraints:
        names = tuple(c.name for c in constraint.columns)
        sa.Index('ix_' + constraint.name[3:], *(t.c[n] for n in names))
sa.Index('ix_problems_recent', problems.c.workspace_id, problems.c.updated_at.desc(), problems.c.id)
sa.Index('ix_problems_owner', problems.c.workspace_id, problems.c.owner_user_id, problems.c.updated_at.desc())
sa.Index('ix_artifacts_file', artifacts.c.workspace_id, artifacts.c.owner_user_id, artifacts.c.sha256)
sa.Index('ix_artifacts_build_type', artifacts.c.workspace_id, artifacts.c.producer_build_id, artifacts.c.artifact_type)
sa.Index('ix_builds_recent', builds.c.workspace_id, builds.c.problem_id, builds.c.created_at.desc())
sa.Index('ix_jobs_active', jobs.c.workspace_id, jobs.c.status, jobs.c.created_at, postgresql_where=jobs.c.status.in_(['queued', 'running']))
sa.Index('ix_outbox_pending', outbox_messages.c.available_at, outbox_messages.c.created_at, postgresql_where=outbox_messages.c.status.in_(['pending', 'publishing']))
sa.Index('ix_diagnostics_code', diagnostics.c.workspace_id, diagnostics.c.code, diagnostics.c.created_at)
sa.Index('ix_calls_provider', model_calls.c.workspace_id, model_calls.c.provider, model_calls.c.created_at)
