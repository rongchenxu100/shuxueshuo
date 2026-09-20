-- Frozen schema for independent mathematical candidate storage.

ALTER TABLE problems ADD COLUMN current_source_version_id UUID;

ALTER TABLE problems ADD COLUMN current_candidate_id UUID;

ALTER TABLE problems ADD COLUMN latest_extraction_run_id UUID;

ALTER TABLE problems ADD COLUMN understanding_generation BIGINT NOT NULL DEFAULT 0 CHECK (understanding_generation >= 0);


CREATE TABLE problem_source_versions (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	parent_version_id UUID,
	images JSONB NOT NULL,
	source_hash TEXT NOT NULL,
	created_by_user_id UUID NOT NULL,
	CONSTRAINT pk_problem_source_versions PRIMARY KEY (id),
	CONSTRAINT uq_problem_source_versions_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT uq_problem_source_versions_workspace_id_problem_id_id UNIQUE (workspace_id, problem_id, id)
)

;


CREATE TABLE problem_candidates (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	source_version_id UUID NOT NULL,
	parent_candidate_id UUID,
	kind TEXT NOT NULL,
	candidate_json JSONB NOT NULL,
	candidate_hash TEXT NOT NULL,
	contract_version TEXT NOT NULL,
	validation_json JSONB NOT NULL,
	raw_artifact_id UUID,
	origin_run_id UUID,
	call_number BIGINT,
	created_by_user_id UUID NOT NULL,
	CONSTRAINT pk_problem_candidates PRIMARY KEY (id),
	CONSTRAINT uq_problem_candidates_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_problem_candidates_kind CHECK (kind IN ('model','manual')),
	CONSTRAINT uq_problem_candidates_origin_run_id_call_number UNIQUE (origin_run_id, call_number),
	CONSTRAINT uq_problem_candidates_workspace_id_problem_id_id UNIQUE (workspace_id, problem_id, id),
	CONSTRAINT ck_problem_candidates_call_number_range CHECK (call_number >= 0)
)

;


CREATE TABLE extraction_runs (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	build_id UUID NOT NULL,
	source_version_id UUID NOT NULL,
	base_candidate_id UUID,
	generation BIGINT NOT NULL,
	mode TEXT NOT NULL,
	status TEXT NOT NULL,
	frozen JSONB NOT NULL,
	workflow_binding JSONB,
	result_json JSONB,
	candidate_id UUID,
	finished_at TIMESTAMP WITH TIME ZONE,
	error_code TEXT,
	CONSTRAINT pk_extraction_runs PRIMARY KEY (id),
	CONSTRAINT uq_extraction_runs_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_extraction_runs_mode CHECK (mode IN ('extract','review','validate')),
	CONSTRAINT ck_extraction_runs_status CHECK (status IN ('queued','running','completed','failed','superseded','cancelled')),
	CONSTRAINT uq_extraction_runs_build_id UNIQUE (build_id),
	CONSTRAINT uq_extraction_runs_workspace_id_problem_id_id UNIQUE (workspace_id, problem_id, id),
	CONSTRAINT ck_extraction_runs_generation_range CHECK (generation >= 0)
)

;


CREATE TABLE extraction_call_reservations (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	run_id UUID NOT NULL,
	number BIGINT NOT NULL,
	stage TEXT NOT NULL,
	request_hash TEXT NOT NULL,
	base_revision TEXT,
	status TEXT NOT NULL,
	request_artifact_id UUID NOT NULL,
	receipt_key TEXT NOT NULL,
	response_artifact_id UUID,
	model_call_id UUID,
	details JSONB,
	CONSTRAINT pk_extraction_call_reservations PRIMARY KEY (id),
	CONSTRAINT uq_extraction_call_reservations_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_extraction_call_reservations_stage CHECK (stage IN ('extract','review','repair')),
	CONSTRAINT ck_extraction_call_reservations_status CHECK (status IN ('reserved','completed','failed')),
	CONSTRAINT uq_extraction_call_reservations_run_id_number UNIQUE (run_id, number),
	CONSTRAINT ck_extraction_call_reservations_number_range CHECK (number >= 0),
	CONSTRAINT ck_extraction_call_reservations_request_hash_format CHECK (request_hash ~ '^[0-9a-f]{64}$')
)

;

ALTER TABLE problem_source_versions ADD CONSTRAINT fk_problem_source_versions_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_source_versions ADD CONSTRAINT fk_problem_source_versions_workspace_id_created_by_user_id FOREIGN KEY(workspace_id, created_by_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_source_versions ADD CONSTRAINT fk_problem_source_versions_workspace_id_problem_i_09ab5ed84b FOREIGN KEY(workspace_id, problem_id, parent_version_id) REFERENCES problem_source_versions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_source_versions ADD CONSTRAINT fk_problem_source_versions_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE INDEX ix_problem_source_versions_workspace_id ON problem_source_versions (workspace_id);

CREATE INDEX ix_problem_source_versions_workspace_id_created_by_user_id ON problem_source_versions (workspace_id, created_by_user_id);

CREATE INDEX ix_problem_source_versions_workspace_id_problem_i_09ab5ed84b ON problem_source_versions (workspace_id, problem_id, parent_version_id);

CREATE INDEX ix_problem_source_versions_workspace_id_problem_id ON problem_source_versions (workspace_id, problem_id);

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id_created_by_user_id FOREIGN KEY(workspace_id, created_by_user_id) REFERENCES workspace_members (workspace_id, user_id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id_problem_id_origin_run_id FOREIGN KEY(workspace_id, problem_id, origin_run_id) REFERENCES extraction_runs (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id_problem_id_par_43e36218a0 FOREIGN KEY(workspace_id, problem_id, parent_candidate_id) REFERENCES problem_candidates (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id_problem_id_sou_42b6c11749 FOREIGN KEY(workspace_id, problem_id, source_version_id) REFERENCES problem_source_versions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problem_candidates ADD CONSTRAINT fk_problem_candidates_workspace_id_raw_artifact_id FOREIGN KEY(workspace_id, raw_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE INDEX ix_candidates_history ON problem_candidates (problem_id, created_at DESC, id);

CREATE INDEX ix_problem_candidates_workspace_id ON problem_candidates (workspace_id);

CREATE INDEX ix_problem_candidates_workspace_id_created_by_user_id ON problem_candidates (workspace_id, created_by_user_id);

CREATE INDEX ix_problem_candidates_workspace_id_problem_id ON problem_candidates (workspace_id, problem_id);

CREATE INDEX ix_problem_candidates_workspace_id_problem_id_origin_run_id ON problem_candidates (workspace_id, problem_id, origin_run_id);

CREATE INDEX ix_problem_candidates_workspace_id_problem_id_par_43e36218a0 ON problem_candidates (workspace_id, problem_id, parent_candidate_id);

CREATE INDEX ix_problem_candidates_workspace_id_problem_id_sou_42b6c11749 ON problem_candidates (workspace_id, problem_id, source_version_id);

CREATE INDEX ix_problem_candidates_workspace_id_raw_artifact_id ON problem_candidates (workspace_id, raw_artifact_id);

ALTER TABLE extraction_runs ADD CONSTRAINT fk_extraction_runs_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_runs ADD CONSTRAINT fk_extraction_runs_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_runs ADD CONSTRAINT fk_extraction_runs_workspace_id_problem_id_base_candidate_id FOREIGN KEY(workspace_id, problem_id, base_candidate_id) REFERENCES problem_candidates (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_runs ADD CONSTRAINT fk_extraction_runs_workspace_id_problem_id_build_id FOREIGN KEY(workspace_id, problem_id, build_id) REFERENCES builds (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_runs ADD CONSTRAINT fk_extraction_runs_workspace_id_problem_id_candidate_id FOREIGN KEY(workspace_id, problem_id, candidate_id) REFERENCES problem_candidates (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_runs ADD CONSTRAINT fk_extraction_runs_workspace_id_problem_id_source_version_id FOREIGN KEY(workspace_id, problem_id, source_version_id) REFERENCES problem_source_versions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE UNIQUE INDEX ix_extraction_one_active ON extraction_runs (problem_id) WHERE status IN ('queued', 'running');

CREATE INDEX ix_extraction_runs_workspace_id ON extraction_runs (workspace_id);

CREATE INDEX ix_extraction_runs_workspace_id_problem_id ON extraction_runs (workspace_id, problem_id);

CREATE INDEX ix_extraction_runs_workspace_id_problem_id_base_candidate_id ON extraction_runs (workspace_id, problem_id, base_candidate_id);

CREATE INDEX ix_extraction_runs_workspace_id_problem_id_build_id ON extraction_runs (workspace_id, problem_id, build_id);

CREATE INDEX ix_extraction_runs_workspace_id_problem_id_candidate_id ON extraction_runs (workspace_id, problem_id, candidate_id);

CREATE INDEX ix_extraction_runs_workspace_id_problem_id_source_version_id ON extraction_runs (workspace_id, problem_id, source_version_id);

ALTER TABLE extraction_call_reservations ADD CONSTRAINT fk_extraction_call_reservations_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_call_reservations ADD CONSTRAINT fk_extraction_call_reservations_workspace_id_model_call_id FOREIGN KEY(workspace_id, model_call_id) REFERENCES model_calls (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_call_reservations ADD CONSTRAINT fk_extraction_call_reservations_workspace_id_requ_17504997a4 FOREIGN KEY(workspace_id, request_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_call_reservations ADD CONSTRAINT fk_extraction_call_reservations_workspace_id_resp_167776964b FOREIGN KEY(workspace_id, response_artifact_id) REFERENCES artifacts (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE extraction_call_reservations ADD CONSTRAINT fk_extraction_call_reservations_workspace_id_run_id FOREIGN KEY(workspace_id, run_id) REFERENCES extraction_runs (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE INDEX ix_extraction_call_reservations_workspace_id ON extraction_call_reservations (workspace_id);

CREATE INDEX ix_extraction_call_reservations_workspace_id_model_call_id ON extraction_call_reservations (workspace_id, model_call_id);

CREATE INDEX ix_extraction_call_reservations_workspace_id_requ_17504997a4 ON extraction_call_reservations (workspace_id, request_artifact_id);

CREATE INDEX ix_extraction_call_reservations_workspace_id_resp_167776964b ON extraction_call_reservations (workspace_id, response_artifact_id);

CREATE INDEX ix_extraction_call_reservations_workspace_id_run_id ON extraction_call_reservations (workspace_id, run_id);

ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_current_candidate_id FOREIGN KEY(workspace_id, id, current_candidate_id) REFERENCES problem_candidates (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_current_source_version_id FOREIGN KEY(workspace_id, id, current_source_version_id) REFERENCES problem_source_versions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_latest_extraction_run_id FOREIGN KEY(workspace_id, id, latest_extraction_run_id) REFERENCES extraction_runs (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE INDEX ix_problems_workspace_id_id_current_candidate_id ON problems (workspace_id, id, current_candidate_id);

CREATE INDEX ix_problems_workspace_id_id_current_source_version_id ON problems (workspace_id, id, current_source_version_id);

CREATE INDEX ix_problems_workspace_id_id_latest_extraction_run_id ON problems (workspace_id, id, latest_extraction_run_id);

DROP TRIGGER immutable_history ON problems;

CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON problem_source_versions FOR EACH ROW EXECUTE FUNCTION product_immutable('');

CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON problem_candidates FOR EACH ROW EXECUTE FUNCTION product_immutable('');

CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON extraction_runs FOR EACH ROW EXECUTE FUNCTION product_immutable('status,workflow_binding,result_json,candidate_id,finished_at,error_code');

CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON extraction_call_reservations FOR EACH ROW EXECUTE FUNCTION product_immutable('status,response_artifact_id,model_call_id,details');

CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON problems FOR EACH ROW EXECUTE FUNCTION product_immutable('title,visibility,current_revision_id,latest_build_id,current_page_build_id,lock_version,updated_at,current_source_version_id,current_candidate_id,latest_extraction_run_id,understanding_generation');

CREATE TRIGGER once_workflow_binding BEFORE UPDATE ON extraction_runs FOR EACH ROW EXECUTE FUNCTION product_once('workflow_binding');

CREATE TRIGGER once_response BEFORE UPDATE ON extraction_call_reservations FOR EACH ROW EXECUTE FUNCTION product_once('response_artifact_id');
