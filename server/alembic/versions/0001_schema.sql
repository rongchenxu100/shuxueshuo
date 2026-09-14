-- Frozen initial schema; do not regenerate after release.

CREATE TABLE users (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	key TEXT NOT NULL,
	display_name TEXT NOT NULL,
	CONSTRAINT pk_users PRIMARY KEY (id),
	CONSTRAINT uq_users_key UNIQUE (key)
)

;

CREATE TABLE workspaces (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	slug TEXT NOT NULL,
	name TEXT NOT NULL,
	CONSTRAINT pk_workspaces PRIMARY KEY (id),
	CONSTRAINT uq_workspaces_slug UNIQUE (slug),
	CONSTRAINT ck_workspaces_slug_nonempty CHECK (length(trim(slug)) > 0)
)

;

CREATE TABLE workspace_members (
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	role TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_workspace_members PRIMARY KEY (workspace_id, user_id),
	CONSTRAINT ck_workspace_members_role CHECK (role IN ('owner','member'))
)

;
CREATE INDEX ix_workspace_members_user_id ON workspace_members (user_id);
CREATE INDEX ix_workspace_members_workspace_id ON workspace_members (workspace_id);

CREATE TABLE batches (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	owner_user_id UUID NOT NULL,
	name TEXT,
	CONSTRAINT pk_batches PRIMARY KEY (id),
	CONSTRAINT uq_batches_workspace_id_id UNIQUE (workspace_id, id)
)

;
CREATE INDEX ix_batches_workspace_id ON batches (workspace_id);
CREATE INDEX ix_batches_workspace_id_owner_user_id ON batches (workspace_id, owner_user_id);

CREATE TABLE batch_items (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	batch_id UUID NOT NULL,
	position INTEGER NOT NULL,
	problem_id UUID NOT NULL,
	source_id UUID NOT NULL,
	initial_build_id UUID,
	CONSTRAINT pk_batch_items PRIMARY KEY (id),
	CONSTRAINT uq_batch_items_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_batch_items_batch_id_position UNIQUE (batch_id, position),
	CONSTRAINT ck_batch_items_position_range CHECK (position >= 1)
)

;
CREATE INDEX ix_batch_items_workspace_id ON batch_items (workspace_id);
CREATE INDEX ix_batch_items_workspace_id_batch_id ON batch_items (workspace_id, batch_id);
CREATE INDEX ix_batch_items_workspace_id_problem_id ON batch_items (workspace_id, problem_id);
CREATE INDEX ix_batch_items_workspace_id_problem_id_initial_build_id ON batch_items (workspace_id, problem_id, initial_build_id);
CREATE INDEX ix_batch_items_workspace_id_problem_id_source_id ON batch_items (workspace_id, problem_id, source_id);
CREATE INDEX ix_batch_items_workspace_id_source_id ON batch_items (workspace_id, source_id);

CREATE TABLE sources (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	owner_user_id UUID NOT NULL,
	original_artifact_id UUID NOT NULL,
	normalized_artifact_id UUID,
	filename TEXT NOT NULL,
	media_type TEXT NOT NULL,
	metadata JSONB DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT pk_sources PRIMARY KEY (id),
	CONSTRAINT uq_sources_workspace_id_id UNIQUE (workspace_id, id)
)

;
CREATE INDEX ix_sources_workspace_id ON sources (workspace_id);
CREATE INDEX ix_sources_workspace_id_normalized_artifact_id ON sources (workspace_id, normalized_artifact_id);
CREATE INDEX ix_sources_workspace_id_original_artifact_id ON sources (workspace_id, original_artifact_id);
CREATE INDEX ix_sources_workspace_id_owner_user_id ON sources (workspace_id, owner_user_id);

CREATE TABLE problems (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	owner_user_id UUID NOT NULL,
	primary_source_id UUID NOT NULL,
	title TEXT,
	visibility TEXT DEFAULT 'private' NOT NULL,
	current_revision_id UUID,
	latest_build_id UUID,
	current_page_build_id UUID,
	lock_version BIGINT DEFAULT '0' NOT NULL,
	CONSTRAINT pk_problems PRIMARY KEY (id),
	CONSTRAINT uq_problems_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_problems_visibility CHECK (visibility IN ('private','workspace')),
	CONSTRAINT ck_problems_lock_version_range CHECK (lock_version >= 0)
)

;
CREATE INDEX ix_problems_owner ON problems (workspace_id, owner_user_id, updated_at DESC);
CREATE INDEX ix_problems_recent ON problems (workspace_id, updated_at DESC, id);
CREATE INDEX ix_problems_workspace_id ON problems (workspace_id);
CREATE INDEX ix_problems_workspace_id_current_page_build_id ON problems (workspace_id, current_page_build_id);
CREATE INDEX ix_problems_workspace_id_id_current_revision_id ON problems (workspace_id, id, current_revision_id);
CREATE INDEX ix_problems_workspace_id_id_latest_build_id ON problems (workspace_id, id, latest_build_id);
CREATE INDEX ix_problems_workspace_id_id_primary_source_id ON problems (workspace_id, id, primary_source_id);
CREATE INDEX ix_problems_workspace_id_owner_user_id ON problems (workspace_id, owner_user_id);
CREATE INDEX ix_problems_workspace_id_primary_source_id ON problems (workspace_id, primary_source_id);

CREATE TABLE problem_sources (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	source_id UUID NOT NULL,
	matched_revision_id UUID,
	match_method TEXT NOT NULL,
	match_evidence_artifact_id UUID,
	CONSTRAINT pk_problem_sources PRIMARY KEY (id),
	CONSTRAINT uq_problem_sources_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_problem_sources_problem_id_source_id UNIQUE (problem_id, source_id),
	CONSTRAINT uq_problem_sources_workspace_id_problem_id_source_id UNIQUE (workspace_id, problem_id, source_id),
	CONSTRAINT ck_problem_sources_match_method CHECK (match_method IN ('initial','file_hash','semantic','manual'))
)

;
CREATE INDEX ix_problem_sources_workspace_id ON problem_sources (workspace_id);
CREATE INDEX ix_problem_sources_workspace_id_match_evidence_artifact_id ON problem_sources (workspace_id, match_evidence_artifact_id);
CREATE INDEX ix_problem_sources_workspace_id_problem_id ON problem_sources (workspace_id, problem_id);
CREATE INDEX ix_problem_sources_workspace_id_problem_id_matche_09fc9967cd ON problem_sources (workspace_id, problem_id, matched_revision_id);
CREATE INDEX ix_problem_sources_workspace_id_source_id ON problem_sources (workspace_id, source_id);

CREATE TABLE problem_revisions (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	revision_no INTEGER NOT NULL,
	parent_revision_id UUID,
	kind TEXT NOT NULL,
	domain_json JSONB NOT NULL,
	verified_json JSONB NOT NULL,
	semantic_hash TEXT NOT NULL,
	schema_version TEXT NOT NULL,
	human_diff JSONB,
	created_by_user_id UUID NOT NULL,
	origin_build_id UUID,
	CONSTRAINT pk_problem_revisions PRIMARY KEY (id),
	CONSTRAINT uq_problem_revisions_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_problem_revisions_problem_id_revision_no UNIQUE (problem_id, revision_no),
	CONSTRAINT uq_problem_revisions_workspace_id_problem_id_id UNIQUE (workspace_id, problem_id, id),
	CONSTRAINT ck_problem_revisions_kind CHECK (kind IN ('extracted','manual')),
	CONSTRAINT ck_problem_revisions_graph_consistent CHECK (domain_json = verified_json->'graph' AND schema_version = domain_json->>'schema_version' AND semantic_hash = verified_json->>'semantic_hash'),
	CONSTRAINT ck_problem_revisions_revision_no_range CHECK (revision_no >= 1),
	CONSTRAINT ck_problem_revisions_semantic_hash_format CHECK (semantic_hash ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_problem_revisions_workspace_id ON problem_revisions (workspace_id);
CREATE INDEX ix_problem_revisions_workspace_id_created_by_user_id ON problem_revisions (workspace_id, created_by_user_id);
CREATE INDEX ix_problem_revisions_workspace_id_problem_id ON problem_revisions (workspace_id, problem_id);
CREATE INDEX ix_problem_revisions_workspace_id_problem_id_origin_build_id ON problem_revisions (workspace_id, problem_id, origin_build_id);
CREATE INDEX ix_problem_revisions_workspace_id_problem_id_pare_b18865bbdb ON problem_revisions (workspace_id, problem_id, parent_revision_id);

CREATE TABLE builds (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	parent_build_id UUID,
	source_id UUID NOT NULL,
	requested_revision_id UUID,
	resolved_revision_id UUID,
	pipeline_key TEXT NOT NULL,
	pipeline_version TEXT NOT NULL,
	pipeline_snapshot JSONB NOT NULL,
	from_stage TEXT NOT NULL,
	target_dependencies JSONB NOT NULL,
	target_fingerprint TEXT NOT NULL,
	deployment_version TEXT NOT NULL,
	effective_config JSONB NOT NULL,
	status TEXT NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	error_code TEXT,
	CONSTRAINT pk_builds PRIMARY KEY (id),
	CONSTRAINT uq_builds_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_builds_workspace_id_problem_id_id UNIQUE (workspace_id, problem_id, id),
	CONSTRAINT ck_builds_status CHECK (status IN ('initializing','queued','running','succeeded','failed','interrupted','cancelled')),
	CONSTRAINT ck_builds_target_fingerprint_format CHECK (target_fingerprint ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_builds_recent ON builds (workspace_id, problem_id, created_at DESC);
CREATE INDEX ix_builds_workspace_id ON builds (workspace_id);
CREATE INDEX ix_builds_workspace_id_problem_id ON builds (workspace_id, problem_id);
CREATE INDEX ix_builds_workspace_id_problem_id_parent_build_id ON builds (workspace_id, problem_id, parent_build_id);
CREATE INDEX ix_builds_workspace_id_problem_id_requested_revision_id ON builds (workspace_id, problem_id, requested_revision_id);
CREATE INDEX ix_builds_workspace_id_problem_id_resolved_revision_id ON builds (workspace_id, problem_id, resolved_revision_id);
CREATE INDEX ix_builds_workspace_id_problem_id_source_id ON builds (workspace_id, problem_id, source_id);
CREATE INDEX ix_builds_workspace_id_source_id ON builds (workspace_id, source_id);

CREATE TABLE jobs (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	build_id UUID NOT NULL,
	status TEXT NOT NULL,
	execution_epoch BIGINT DEFAULT '0' NOT NULL,
	active_execution_id UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	cancel_requested_at TIMESTAMP WITH TIME ZONE,
	delivery_count BIGINT DEFAULT '0' NOT NULL,
	retry_budget JSONB NOT NULL,
	CONSTRAINT pk_jobs PRIMARY KEY (id),
	CONSTRAINT uq_jobs_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_jobs_build_id UNIQUE (build_id),
	CONSTRAINT ck_jobs_status CHECK (status IN ('queued','running','succeeded','failed','interrupted','cancelled')),
	CONSTRAINT ck_jobs_execution_epoch_range CHECK (execution_epoch >= 0),
	CONSTRAINT ck_jobs_delivery_count_range CHECK (delivery_count >= 0)
)

;
CREATE INDEX ix_jobs_active ON jobs (workspace_id, status, created_at) WHERE status IN ('queued', 'running');
CREATE INDEX ix_jobs_workspace_id ON jobs (workspace_id);
CREATE INDEX ix_jobs_workspace_id_build_id ON jobs (workspace_id, build_id);
CREATE INDEX ix_jobs_workspace_id_id_active_execution_id ON jobs (workspace_id, id, active_execution_id);

CREATE TABLE job_executions (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	job_id UUID NOT NULL,
	epoch BIGINT NOT NULL,
	worker_id TEXT NOT NULL,
	status TEXT NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	failure_code TEXT,
	CONSTRAINT pk_job_executions PRIMARY KEY (id),
	CONSTRAINT uq_job_executions_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_job_executions_job_id_epoch UNIQUE (job_id, epoch),
	CONSTRAINT uq_job_executions_workspace_id_job_id_id UNIQUE (workspace_id, job_id, id),
	CONSTRAINT ck_job_executions_status CHECK (status IN ('running','succeeded','failed','interrupted','cancelled')),
	CONSTRAINT ck_job_executions_epoch_range CHECK (epoch >= 1)
)

;
CREATE INDEX ix_job_executions_workspace_id ON job_executions (workspace_id);
CREATE INDEX ix_job_executions_workspace_id_job_id ON job_executions (workspace_id, job_id);

CREATE TABLE build_stages (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	build_id UUID NOT NULL,
	stage_key TEXT NOT NULL,
	ordinal SMALLINT NOT NULL,
	status TEXT NOT NULL,
	accepted_attempt_id UUID,
	summary TEXT,
	CONSTRAINT pk_build_stages PRIMARY KEY (id),
	CONSTRAINT uq_build_stages_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_build_stages_build_id_stage_key UNIQUE (build_id, stage_key),
	CONSTRAINT uq_build_stages_build_id_ordinal UNIQUE (build_id, ordinal),
	CONSTRAINT ck_build_stages_status CHECK (status IN ('pending','running','succeeded','failed','blocked','interrupted','cancelled')),
	CONSTRAINT ck_build_stages_ordinal_range CHECK (ordinal >= 1)
)

;
CREATE INDEX ix_build_stages_workspace_id ON build_stages (workspace_id);
CREATE INDEX ix_build_stages_workspace_id_build_id ON build_stages (workspace_id, build_id);
CREATE INDEX ix_build_stages_workspace_id_id_accepted_attempt_id ON build_stages (workspace_id, id, accepted_attempt_id);

CREATE TABLE stage_attempts (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	build_stage_id UUID NOT NULL,
	execution_id UUID,
	attempt_no INTEGER NOT NULL,
	kind TEXT NOT NULL,
	status TEXT NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	manifest_json JSONB,
	manifest_artifact_id UUID,
	manifest_sha256 TEXT,
	checkpoint_artifact_id UUID,
	reused_from_attempt_id UUID,
	CONSTRAINT pk_stage_attempts PRIMARY KEY (id),
	CONSTRAINT uq_stage_attempts_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_stage_attempts_build_stage_id_attempt_no UNIQUE (build_stage_id, attempt_no),
	CONSTRAINT uq_stage_attempts_workspace_id_build_stage_id_id UNIQUE (workspace_id, build_stage_id, id),
	CONSTRAINT ck_stage_attempts_kind CHECK (kind IN ('executed','reused')),
	CONSTRAINT ck_stage_attempts_status CHECK (status IN ('running','succeeded','failed','interrupted','cancelled')),
	CONSTRAINT ck_stage_attempts_execution_required CHECK ((kind = 'executed' AND execution_id IS NOT NULL AND reused_from_attempt_id IS NULL) OR (kind = 'reused' AND reused_from_attempt_id IS NOT NULL)),
	CONSTRAINT ck_stage_attempts_success_evidence CHECK (status <> 'succeeded' OR (manifest_json IS NOT NULL AND manifest_artifact_id IS NOT NULL AND manifest_sha256 IS NOT NULL AND checkpoint_artifact_id IS NOT NULL)),
	CONSTRAINT ck_stage_attempts_attempt_no_range CHECK (attempt_no >= 1),
	CONSTRAINT ck_stage_attempts_manifest_sha256_format CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_stage_attempts_workspace_id ON stage_attempts (workspace_id);
CREATE INDEX ix_stage_attempts_workspace_id_build_stage_id ON stage_attempts (workspace_id, build_stage_id);
CREATE INDEX ix_stage_attempts_workspace_id_checkpoint_artifact_id ON stage_attempts (workspace_id, checkpoint_artifact_id);
CREATE INDEX ix_stage_attempts_workspace_id_execution_id ON stage_attempts (workspace_id, execution_id);
CREATE INDEX ix_stage_attempts_workspace_id_manifest_artifact_id ON stage_attempts (workspace_id, manifest_artifact_id);
CREATE INDEX ix_stage_attempts_workspace_id_reused_from_attempt_id ON stage_attempts (workspace_id, reused_from_attempt_id);

CREATE TABLE artifacts (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	owner_user_id UUID NOT NULL,
	producer_build_id UUID,
	producer_attempt_id UUID,
	artifact_type TEXT NOT NULL,
	storage_key TEXT NOT NULL,
	sha256 TEXT NOT NULL,
	size_bytes BIGINT NOT NULL,
	content_type TEXT NOT NULL,
	schema_version TEXT,
	access_class TEXT NOT NULL,
	availability TEXT DEFAULT 'verified' NOT NULL,
	CONSTRAINT pk_artifacts PRIMARY KEY (id),
	CONSTRAINT uq_artifacts_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_artifacts_storage_key UNIQUE (storage_key),
	CONSTRAINT ck_artifacts_access_class CHECK (access_class IN ('private','page')),
	CONSTRAINT ck_artifacts_availability CHECK (availability IN ('verified','missing','corrupt')),
	CONSTRAINT ck_artifacts_page_types CHECK (access_class <> 'page' OR artifact_type IN ('page_html','page_css','page_js','page_svg','page_image','page_font')),
	CONSTRAINT ck_artifacts_sha256_format CHECK (sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_artifacts_size_bytes_range CHECK (size_bytes >= 0)
)

;
CREATE INDEX ix_artifacts_build_type ON artifacts (workspace_id, producer_build_id, artifact_type);
CREATE INDEX ix_artifacts_file ON artifacts (workspace_id, owner_user_id, sha256);
CREATE INDEX ix_artifacts_workspace_id ON artifacts (workspace_id);
CREATE INDEX ix_artifacts_workspace_id_owner_user_id ON artifacts (workspace_id, owner_user_id);
CREATE INDEX ix_artifacts_workspace_id_producer_attempt_id ON artifacts (workspace_id, producer_attempt_id);
CREATE INDEX ix_artifacts_workspace_id_producer_build_id ON artifacts (workspace_id, producer_build_id);

CREATE TABLE stage_artifacts (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	stage_attempt_id UUID NOT NULL,
	artifact_id UUID NOT NULL,
	role TEXT NOT NULL,
	name TEXT NOT NULL,
	position INTEGER NOT NULL,
	reused_from_artifact_id UUID,
	CONSTRAINT pk_stage_artifacts PRIMARY KEY (id),
	CONSTRAINT uq_stage_artifacts_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_stage_artifacts_role CHECK (role IN ('input','output','raw','validation','configuration','call')),
	CONSTRAINT uq_stage_artifacts_stage_attempt_id_role_name_position UNIQUE (stage_attempt_id, role, name, position),
	CONSTRAINT ck_stage_artifacts_position_range CHECK (position >= 1)
)

;
CREATE INDEX ix_stage_artifacts_workspace_id ON stage_artifacts (workspace_id);
CREATE INDEX ix_stage_artifacts_workspace_id_artifact_id ON stage_artifacts (workspace_id, artifact_id);
CREATE INDEX ix_stage_artifacts_workspace_id_reused_from_artifact_id ON stage_artifacts (workspace_id, reused_from_artifact_id);
CREATE INDEX ix_stage_artifacts_workspace_id_stage_attempt_id ON stage_artifacts (workspace_id, stage_attempt_id);

CREATE TABLE artifact_dependencies (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	artifact_id UUID NOT NULL,
	depends_on_artifact_id UUID NOT NULL,
	kind TEXT NOT NULL,
	CONSTRAINT pk_artifact_dependencies PRIMARY KEY (id),
	CONSTRAINT uq_artifact_dependencies_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_artifact_dependencies_artifact_id_depends_on_a_9f95f55f42 UNIQUE (artifact_id, depends_on_artifact_id, kind),
	CONSTRAINT ck_artifact_dependencies_kind CHECK (kind IN ('audit','build_input','reuse')),
	CONSTRAINT ck_artifact_dependencies_not_self CHECK (artifact_id <> depends_on_artifact_id)
)

;
CREATE INDEX ix_artifact_dependencies_workspace_id ON artifact_dependencies (workspace_id);
CREATE INDEX ix_artifact_dependencies_workspace_id_artifact_id ON artifact_dependencies (workspace_id, artifact_id);
CREATE INDEX ix_artifact_dependencies_workspace_id_depends_on_artifact_id ON artifact_dependencies (workspace_id, depends_on_artifact_id);

CREATE TABLE model_calls (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	origin_attempt_id UUID NOT NULL,
	provider TEXT,
	request_model TEXT,
	response_model TEXT,
	provider_version TEXT,
	provider_request_id TEXT,
	call_kind TEXT NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	duration_ms BIGINT,
	status TEXT NOT NULL,
	usage_json JSONB,
	input_tokens BIGINT,
	output_tokens BIGINT,
	request_artifact_id UUID,
	response_artifact_id UUID,
	audit_artifact_id UUID NOT NULL,
	CONSTRAINT pk_model_calls PRIMARY KEY (id),
	CONSTRAINT uq_model_calls_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_model_calls_status CHECK (status IN ('succeeded','failed','interrupted')),
	CONSTRAINT uq_model_calls_audit_artifact_id UNIQUE (audit_artifact_id),
	CONSTRAINT ck_model_calls_duration_ms_range CHECK (duration_ms >= 0),
	CONSTRAINT ck_model_calls_input_tokens_range CHECK (input_tokens >= 0),
	CONSTRAINT ck_model_calls_output_tokens_range CHECK (output_tokens >= 0)
)

;
CREATE INDEX ix_calls_provider ON model_calls (workspace_id, provider, created_at);
CREATE INDEX ix_model_calls_workspace_id ON model_calls (workspace_id);
CREATE INDEX ix_model_calls_workspace_id_audit_artifact_id ON model_calls (workspace_id, audit_artifact_id);
CREATE INDEX ix_model_calls_workspace_id_origin_attempt_id ON model_calls (workspace_id, origin_attempt_id);
CREATE INDEX ix_model_calls_workspace_id_request_artifact_id ON model_calls (workspace_id, request_artifact_id);
CREATE INDEX ix_model_calls_workspace_id_response_artifact_id ON model_calls (workspace_id, response_artifact_id);

CREATE TABLE stage_call_refs (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	stage_attempt_id UUID NOT NULL,
	model_call_id UUID NOT NULL,
	relation TEXT NOT NULL,
	CONSTRAINT pk_stage_call_refs PRIMARY KEY (id),
	CONSTRAINT uq_stage_call_refs_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_stage_call_refs_stage_attempt_id_model_call_id UNIQUE (stage_attempt_id, model_call_id),
	CONSTRAINT ck_stage_call_refs_relation CHECK (relation IN ('executed','reused'))
)

;
CREATE INDEX ix_stage_call_refs_workspace_id ON stage_call_refs (workspace_id);
CREATE INDEX ix_stage_call_refs_workspace_id_model_call_id ON stage_call_refs (workspace_id, model_call_id);
CREATE INDEX ix_stage_call_refs_workspace_id_stage_attempt_id ON stage_call_refs (workspace_id, stage_attempt_id);

CREATE TABLE diagnostics (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	build_id UUID NOT NULL,
	stage_attempt_id UUID,
	code TEXT NOT NULL,
	severity TEXT NOT NULL,
	message TEXT NOT NULL,
	details JSONB,
	evidence_artifact_id UUID,
	CONSTRAINT pk_diagnostics PRIMARY KEY (id),
	CONSTRAINT uq_diagnostics_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_diagnostics_severity CHECK (severity IN ('info','warning','error'))
)

;
CREATE INDEX ix_diagnostics_code ON diagnostics (workspace_id, code, created_at);
CREATE INDEX ix_diagnostics_workspace_id ON diagnostics (workspace_id);
CREATE INDEX ix_diagnostics_workspace_id_build_id ON diagnostics (workspace_id, build_id);
CREATE INDEX ix_diagnostics_workspace_id_evidence_artifact_id ON diagnostics (workspace_id, evidence_artifact_id);
CREATE INDEX ix_diagnostics_workspace_id_stage_attempt_id ON diagnostics (workspace_id, stage_attempt_id);

CREATE TABLE page_builds (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	build_id UUID NOT NULL,
	revision_id UUID NOT NULL,
	entry_artifact_id UUID NOT NULL,
	package_manifest_artifact_id UUID NOT NULL,
	package_sha256 TEXT NOT NULL,
	CONSTRAINT pk_page_builds PRIMARY KEY (id),
	CONSTRAINT uq_page_builds_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_page_builds_build_id UNIQUE (build_id),
	CONSTRAINT uq_page_builds_workspace_id_id_revision_id UNIQUE (workspace_id, id, revision_id),
	CONSTRAINT ck_page_builds_package_sha256_format CHECK (package_sha256 ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_page_builds_workspace_id ON page_builds (workspace_id);
CREATE INDEX ix_page_builds_workspace_id_build_id ON page_builds (workspace_id, build_id);
CREATE INDEX ix_page_builds_workspace_id_entry_artifact_id ON page_builds (workspace_id, entry_artifact_id);
CREATE INDEX ix_page_builds_workspace_id_package_manifest_artifact_id ON page_builds (workspace_id, package_manifest_artifact_id);
CREATE INDEX ix_page_builds_workspace_id_revision_id ON page_builds (workspace_id, revision_id);

CREATE TABLE page_assets (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	page_build_id UUID NOT NULL,
	relative_path TEXT NOT NULL,
	artifact_id UUID NOT NULL,
	CONSTRAINT pk_page_assets PRIMARY KEY (id),
	CONSTRAINT uq_page_assets_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_page_assets_page_build_id_relative_path UNIQUE (page_build_id, relative_path)
)

;
CREATE INDEX ix_page_assets_workspace_id ON page_assets (workspace_id);
CREATE INDEX ix_page_assets_workspace_id_artifact_id ON page_assets (workspace_id, artifact_id);
CREATE INDEX ix_page_assets_workspace_id_page_build_id ON page_assets (workspace_id, page_build_id);

CREATE TABLE review_decisions (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	page_build_id UUID NOT NULL,
	revision_id UUID NOT NULL,
	reviewer_user_id UUID NOT NULL,
	decision TEXT NOT NULL,
	comment TEXT,
	supersedes_id UUID,
	CONSTRAINT pk_review_decisions PRIMARY KEY (id),
	CONSTRAINT uq_review_decisions_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_review_decisions_workspace_id_page_build_id_id UNIQUE (workspace_id, page_build_id, id),
	CONSTRAINT ck_review_decisions_decision CHECK (decision IN ('approved','rejected','revoked'))
)

;
CREATE INDEX ix_review_decisions_workspace_id ON review_decisions (workspace_id);
CREATE INDEX ix_review_decisions_workspace_id_page_build_id_revision_id ON review_decisions (workspace_id, page_build_id, revision_id);
CREATE INDEX ix_review_decisions_workspace_id_page_build_id_supersedes_id ON review_decisions (workspace_id, page_build_id, supersedes_id);
CREATE INDEX ix_review_decisions_workspace_id_reviewer_user_id ON review_decisions (workspace_id, reviewer_user_id);

CREATE TABLE idempotency_requests (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	user_id UUID NOT NULL,
	operation TEXT NOT NULL,
	request_id TEXT NOT NULL,
	request_hash TEXT NOT NULL,
	resource_type TEXT,
	resource_id UUID,
	response_json JSONB,
	CONSTRAINT pk_idempotency_requests PRIMARY KEY (id),
	CONSTRAINT uq_idempotency_requests_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_idempotency_requests_workspace_id_user_id_oper_253120afe3 UNIQUE (workspace_id, user_id, operation, request_id),
	CONSTRAINT ck_idempotency_requests_request_hash_format CHECK (request_hash ~ '^[0-9a-f]{64}$')
)

;
CREATE INDEX ix_idempotency_requests_workspace_id ON idempotency_requests (workspace_id);
CREATE INDEX ix_idempotency_requests_workspace_id_user_id ON idempotency_requests (workspace_id, user_id);

CREATE TABLE event_streams (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	stream_kind TEXT NOT NULL,
	aggregate_id UUID NOT NULL,
	last_seq BIGINT DEFAULT '0' NOT NULL,
	min_retained_seq BIGINT DEFAULT '1' NOT NULL,
	CONSTRAINT pk_event_streams PRIMARY KEY (id),
	CONSTRAINT uq_event_streams_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_event_streams_workspace_id_stream_kind_aggregate_id UNIQUE (workspace_id, stream_kind, aggregate_id),
	CONSTRAINT ck_event_streams_last_seq_range CHECK (last_seq >= 0),
	CONSTRAINT ck_event_streams_min_retained_seq_range CHECK (min_retained_seq >= 1)
)

;
CREATE INDEX ix_event_streams_workspace_id ON event_streams (workspace_id);

CREATE TABLE events (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	stream_id UUID NOT NULL,
	seq BIGINT NOT NULL,
	event_type TEXT NOT NULL,
	schema_version TEXT NOT NULL,
	payload JSONB NOT NULL,
	CONSTRAINT pk_events PRIMARY KEY (id),
	CONSTRAINT uq_events_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_events_stream_id_seq UNIQUE (stream_id, seq),
	CONSTRAINT ck_events_seq_range CHECK (seq >= 1)
)

;
CREATE INDEX ix_events_workspace_id ON events (workspace_id);
CREATE INDEX ix_events_workspace_id_stream_id ON events (workspace_id, stream_id);

CREATE TABLE outbox_messages (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	job_id UUID NOT NULL,
	message_type TEXT NOT NULL,
	protocol_version TEXT NOT NULL,
	payload JSONB NOT NULL,
	dedupe_key TEXT NOT NULL,
	status TEXT DEFAULT 'pending' NOT NULL,
	attempt_count INTEGER DEFAULT '0' NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE NOT NULL,
	locked_until TIMESTAMP WITH TIME ZONE,
	publisher_token UUID,
	published_at TIMESTAMP WITH TIME ZONE,
	last_error TEXT,
	CONSTRAINT pk_outbox_messages PRIMARY KEY (id),
	CONSTRAINT uq_outbox_messages_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_outbox_messages_dedupe_key UNIQUE (dedupe_key),
	CONSTRAINT ck_outbox_messages_status CHECK (status IN ('pending','publishing','published','failed')),
	CONSTRAINT ck_outbox_messages_attempt_count_range CHECK (attempt_count >= 0)
)

;
CREATE INDEX ix_outbox_messages_workspace_id ON outbox_messages (workspace_id);
CREATE INDEX ix_outbox_messages_workspace_id_job_id ON outbox_messages (workspace_id, job_id);
CREATE INDEX ix_outbox_pending ON outbox_messages (available_at, created_at) WHERE status IN ('pending', 'publishing');
ALTER TABLE workspace_members ADD CONSTRAINT fk_workspace_members_user_id FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE workspace_members ADD CONSTRAINT fk_workspace_members_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batches ADD CONSTRAINT fk_batches_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batches ADD CONSTRAINT fk_batches_workspace_id_owner_user_id FOREIGN KEY(workspace_id, owner_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batch_items ADD CONSTRAINT fk_batch_items_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batch_items ADD CONSTRAINT fk_batch_items_workspace_id_batch_id FOREIGN KEY(workspace_id, batch_id) REFERENCES batches (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batch_items ADD CONSTRAINT fk_batch_items_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batch_items ADD CONSTRAINT fk_batch_items_workspace_id_problem_id_initial_build_id FOREIGN KEY(workspace_id, problem_id, initial_build_id) REFERENCES builds (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batch_items ADD CONSTRAINT fk_batch_items_workspace_id_problem_id_source_id FOREIGN KEY(workspace_id, problem_id, source_id) REFERENCES problem_sources (workspace_id, problem_id, source_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE batch_items ADD CONSTRAINT fk_batch_items_workspace_id_source_id FOREIGN KEY(workspace_id, source_id) REFERENCES sources (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE sources ADD CONSTRAINT fk_sources_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE sources ADD CONSTRAINT fk_sources_workspace_id_normalized_artifact_id FOREIGN KEY(workspace_id, normalized_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE sources ADD CONSTRAINT fk_sources_workspace_id_original_artifact_id FOREIGN KEY(workspace_id, original_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE sources ADD CONSTRAINT fk_sources_workspace_id_owner_user_id FOREIGN KEY(workspace_id, owner_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_current_page_build_id FOREIGN KEY(workspace_id, current_page_build_id) REFERENCES page_builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_current_revision_id FOREIGN KEY(workspace_id, id, current_revision_id) REFERENCES problem_revisions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_latest_build_id FOREIGN KEY(workspace_id, id, latest_build_id) REFERENCES builds (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_primary_source_id FOREIGN KEY(workspace_id, id, primary_source_id) REFERENCES problem_sources (workspace_id, problem_id, source_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_owner_user_id FOREIGN KEY(workspace_id, owner_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_primary_source_id FOREIGN KEY(workspace_id, primary_source_id) REFERENCES sources (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_sources ADD CONSTRAINT fk_problem_sources_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_sources ADD CONSTRAINT fk_problem_sources_workspace_id_match_evidence_artifact_id FOREIGN KEY(workspace_id, match_evidence_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_sources ADD CONSTRAINT fk_problem_sources_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_sources ADD CONSTRAINT fk_problem_sources_workspace_id_problem_id_matche_09fc9967cd FOREIGN KEY(workspace_id, problem_id, matched_revision_id) REFERENCES problem_revisions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_sources ADD CONSTRAINT fk_problem_sources_workspace_id_source_id FOREIGN KEY(workspace_id, source_id) REFERENCES sources (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_revisions ADD CONSTRAINT fk_problem_revisions_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_revisions ADD CONSTRAINT fk_problem_revisions_workspace_id_created_by_user_id FOREIGN KEY(workspace_id, created_by_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_revisions ADD CONSTRAINT fk_problem_revisions_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_revisions ADD CONSTRAINT fk_problem_revisions_workspace_id_problem_id_origin_build_id FOREIGN KEY(workspace_id, problem_id, origin_build_id) REFERENCES builds (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE problem_revisions ADD CONSTRAINT fk_problem_revisions_workspace_id_problem_id_pare_b18865bbdb FOREIGN KEY(workspace_id, problem_id, parent_revision_id) REFERENCES problem_revisions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id_problem_id_parent_build_id FOREIGN KEY(workspace_id, problem_id, parent_build_id) REFERENCES builds (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id_problem_id_requested_revision_id FOREIGN KEY(workspace_id, problem_id, requested_revision_id) REFERENCES problem_revisions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id_problem_id_resolved_revision_id FOREIGN KEY(workspace_id, problem_id, resolved_revision_id) REFERENCES problem_revisions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id_problem_id_source_id FOREIGN KEY(workspace_id, problem_id, source_id) REFERENCES problem_sources (workspace_id, problem_id, source_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE builds ADD CONSTRAINT fk_builds_workspace_id_source_id FOREIGN KEY(workspace_id, source_id) REFERENCES sources (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE jobs ADD CONSTRAINT fk_jobs_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE jobs ADD CONSTRAINT fk_jobs_workspace_id_build_id FOREIGN KEY(workspace_id, build_id) REFERENCES builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE jobs ADD CONSTRAINT fk_jobs_workspace_id_id_active_execution_id FOREIGN KEY(workspace_id, id, active_execution_id) REFERENCES job_executions (workspace_id, job_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE job_executions ADD CONSTRAINT fk_job_executions_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE job_executions ADD CONSTRAINT fk_job_executions_workspace_id_job_id FOREIGN KEY(workspace_id, job_id) REFERENCES jobs (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE build_stages ADD CONSTRAINT fk_build_stages_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE build_stages ADD CONSTRAINT fk_build_stages_workspace_id_build_id FOREIGN KEY(workspace_id, build_id) REFERENCES builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE build_stages ADD CONSTRAINT fk_build_stages_workspace_id_id_accepted_attempt_id FOREIGN KEY(workspace_id, id, accepted_attempt_id) REFERENCES stage_attempts (workspace_id, build_stage_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_attempts ADD CONSTRAINT fk_stage_attempts_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_attempts ADD CONSTRAINT fk_stage_attempts_workspace_id_build_stage_id FOREIGN KEY(workspace_id, build_stage_id) REFERENCES build_stages (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_attempts ADD CONSTRAINT fk_stage_attempts_workspace_id_checkpoint_artifact_id FOREIGN KEY(workspace_id, checkpoint_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_attempts ADD CONSTRAINT fk_stage_attempts_workspace_id_execution_id FOREIGN KEY(workspace_id, execution_id) REFERENCES job_executions (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_attempts ADD CONSTRAINT fk_stage_attempts_workspace_id_manifest_artifact_id FOREIGN KEY(workspace_id, manifest_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_attempts ADD CONSTRAINT fk_stage_attempts_workspace_id_reused_from_attempt_id FOREIGN KEY(workspace_id, reused_from_attempt_id) REFERENCES stage_attempts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifacts ADD CONSTRAINT fk_artifacts_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifacts ADD CONSTRAINT fk_artifacts_workspace_id_owner_user_id FOREIGN KEY(workspace_id, owner_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifacts ADD CONSTRAINT fk_artifacts_workspace_id_producer_attempt_id FOREIGN KEY(workspace_id, producer_attempt_id) REFERENCES stage_attempts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifacts ADD CONSTRAINT fk_artifacts_workspace_id_producer_build_id FOREIGN KEY(workspace_id, producer_build_id) REFERENCES builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_artifacts ADD CONSTRAINT fk_stage_artifacts_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_artifacts ADD CONSTRAINT fk_stage_artifacts_workspace_id_artifact_id FOREIGN KEY(workspace_id, artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_artifacts ADD CONSTRAINT fk_stage_artifacts_workspace_id_reused_from_artifact_id FOREIGN KEY(workspace_id, reused_from_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_artifacts ADD CONSTRAINT fk_stage_artifacts_workspace_id_stage_attempt_id FOREIGN KEY(workspace_id, stage_attempt_id) REFERENCES stage_attempts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifact_dependencies ADD CONSTRAINT fk_artifact_dependencies_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifact_dependencies ADD CONSTRAINT fk_artifact_dependencies_workspace_id_artifact_id FOREIGN KEY(workspace_id, artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE artifact_dependencies ADD CONSTRAINT fk_artifact_dependencies_workspace_id_depends_on_artifact_id FOREIGN KEY(workspace_id, depends_on_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE model_calls ADD CONSTRAINT fk_model_calls_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE model_calls ADD CONSTRAINT fk_model_calls_workspace_id_audit_artifact_id FOREIGN KEY(workspace_id, audit_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE model_calls ADD CONSTRAINT fk_model_calls_workspace_id_origin_attempt_id FOREIGN KEY(workspace_id, origin_attempt_id) REFERENCES stage_attempts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE model_calls ADD CONSTRAINT fk_model_calls_workspace_id_request_artifact_id FOREIGN KEY(workspace_id, request_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE model_calls ADD CONSTRAINT fk_model_calls_workspace_id_response_artifact_id FOREIGN KEY(workspace_id, response_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_call_refs ADD CONSTRAINT fk_stage_call_refs_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_call_refs ADD CONSTRAINT fk_stage_call_refs_workspace_id_model_call_id FOREIGN KEY(workspace_id, model_call_id) REFERENCES model_calls (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE stage_call_refs ADD CONSTRAINT fk_stage_call_refs_workspace_id_stage_attempt_id FOREIGN KEY(workspace_id, stage_attempt_id) REFERENCES stage_attempts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE diagnostics ADD CONSTRAINT fk_diagnostics_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE diagnostics ADD CONSTRAINT fk_diagnostics_workspace_id_build_id FOREIGN KEY(workspace_id, build_id) REFERENCES builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE diagnostics ADD CONSTRAINT fk_diagnostics_workspace_id_evidence_artifact_id FOREIGN KEY(workspace_id, evidence_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE diagnostics ADD CONSTRAINT fk_diagnostics_workspace_id_stage_attempt_id FOREIGN KEY(workspace_id, stage_attempt_id) REFERENCES stage_attempts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_builds ADD CONSTRAINT fk_page_builds_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_builds ADD CONSTRAINT fk_page_builds_workspace_id_build_id FOREIGN KEY(workspace_id, build_id) REFERENCES builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_builds ADD CONSTRAINT fk_page_builds_workspace_id_entry_artifact_id FOREIGN KEY(workspace_id, entry_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_builds ADD CONSTRAINT fk_page_builds_workspace_id_package_manifest_artifact_id FOREIGN KEY(workspace_id, package_manifest_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_builds ADD CONSTRAINT fk_page_builds_workspace_id_revision_id FOREIGN KEY(workspace_id, revision_id) REFERENCES problem_revisions (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_assets ADD CONSTRAINT fk_page_assets_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_assets ADD CONSTRAINT fk_page_assets_workspace_id_artifact_id FOREIGN KEY(workspace_id, artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE page_assets ADD CONSTRAINT fk_page_assets_workspace_id_page_build_id FOREIGN KEY(workspace_id, page_build_id) REFERENCES page_builds (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE review_decisions ADD CONSTRAINT fk_review_decisions_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE review_decisions ADD CONSTRAINT fk_review_decisions_workspace_id_page_build_id_revision_id FOREIGN KEY(workspace_id, page_build_id, revision_id) REFERENCES page_builds (workspace_id, id, revision_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE review_decisions ADD CONSTRAINT fk_review_decisions_workspace_id_page_build_id_supersedes_id FOREIGN KEY(workspace_id, page_build_id, supersedes_id) REFERENCES review_decisions (workspace_id, page_build_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE review_decisions ADD CONSTRAINT fk_review_decisions_workspace_id_reviewer_user_id FOREIGN KEY(workspace_id, reviewer_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE idempotency_requests ADD CONSTRAINT fk_idempotency_requests_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE idempotency_requests ADD CONSTRAINT fk_idempotency_requests_workspace_id_user_id FOREIGN KEY(workspace_id, user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE event_streams ADD CONSTRAINT fk_event_streams_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE events ADD CONSTRAINT fk_events_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE events ADD CONSTRAINT fk_events_workspace_id_stream_id FOREIGN KEY(workspace_id, stream_id) REFERENCES event_streams (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE outbox_messages ADD CONSTRAINT fk_outbox_messages_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;
ALTER TABLE outbox_messages ADD CONSTRAINT fk_outbox_messages_workspace_id_job_id FOREIGN KEY(workspace_id, job_id) REFERENCES jobs (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;
