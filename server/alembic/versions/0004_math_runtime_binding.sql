-- Frozen runtime admission schema; independent of source review.

ALTER TABLE problems ADD COLUMN latest_runtime_binding_run_id UUID;


CREATE TABLE runtime_binding_runs (
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	problem_id UUID NOT NULL,
	build_id UUID NOT NULL,
	candidate_id UUID NOT NULL,
	source_version_id UUID NOT NULL,
	review_run_id UUID,
	snapshot JSONB NOT NULL,
	frozen JSONB NOT NULL,
	status TEXT NOT NULL,
	result_json JSONB,
	finished_at TIMESTAMP WITH TIME ZONE,
	error_code TEXT,
	CONSTRAINT pk_runtime_binding_runs PRIMARY KEY (id),
	CONSTRAINT uq_runtime_binding_runs_workspace_id_id UNIQUE (workspace_id, id),
	CONSTRAINT ck_runtime_binding_runs_status CHECK (status IN ('queued','running','completed','failed','superseded','cancelled')),
	CONSTRAINT uq_runtime_binding_runs_build_id UNIQUE (build_id),
	CONSTRAINT uq_runtime_binding_runs_workspace_id_problem_id_id UNIQUE (workspace_id, problem_id, id)
)

;

ALTER TABLE runtime_binding_runs ADD CONSTRAINT fk_runtime_binding_runs_workspace_id FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE runtime_binding_runs ADD CONSTRAINT fk_runtime_binding_runs_workspace_id_problem_id FOREIGN KEY(workspace_id, problem_id) REFERENCES problems (workspace_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE runtime_binding_runs ADD CONSTRAINT fk_runtime_binding_runs_workspace_id_problem_id_build_id FOREIGN KEY(workspace_id, problem_id, build_id) REFERENCES builds (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE runtime_binding_runs ADD CONSTRAINT fk_runtime_binding_runs_workspace_id_problem_id_candidate_id FOREIGN KEY(workspace_id, problem_id, candidate_id) REFERENCES problem_candidates (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE runtime_binding_runs ADD CONSTRAINT fk_runtime_binding_runs_workspace_id_problem_id_r_d98da34ac3 FOREIGN KEY(workspace_id, problem_id, review_run_id) REFERENCES extraction_runs (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

ALTER TABLE runtime_binding_runs ADD CONSTRAINT fk_runtime_binding_runs_workspace_id_problem_id_s_a9cb1f7e7d FOREIGN KEY(workspace_id, problem_id, source_version_id) REFERENCES problem_source_versions (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE INDEX ix_binding_history ON runtime_binding_runs (problem_id, created_at DESC, id);

CREATE UNIQUE INDEX ix_binding_one_active ON runtime_binding_runs (problem_id) WHERE status IN ('queued', 'running');

CREATE INDEX ix_runtime_binding_runs_workspace_id ON runtime_binding_runs (workspace_id);

CREATE INDEX ix_runtime_binding_runs_workspace_id_problem_id ON runtime_binding_runs (workspace_id, problem_id);

CREATE INDEX ix_runtime_binding_runs_workspace_id_problem_id_build_id ON runtime_binding_runs (workspace_id, problem_id, build_id);

CREATE INDEX ix_runtime_binding_runs_workspace_id_problem_id_candidate_id ON runtime_binding_runs (workspace_id, problem_id, candidate_id);

CREATE INDEX ix_runtime_binding_runs_workspace_id_problem_id_r_d98da34ac3 ON runtime_binding_runs (workspace_id, problem_id, review_run_id);

CREATE INDEX ix_runtime_binding_runs_workspace_id_problem_id_s_a9cb1f7e7d ON runtime_binding_runs (workspace_id, problem_id, source_version_id);

ALTER TABLE problems ADD CONSTRAINT fk_problems_workspace_id_id_latest_runtime_binding_run_id FOREIGN KEY(workspace_id, id, latest_runtime_binding_run_id) REFERENCES runtime_binding_runs (workspace_id, problem_id, id) ON DELETE RESTRICT NOT DEFERRABLE;

CREATE INDEX ix_problems_workspace_id_id_latest_runtime_binding_run_id ON problems (workspace_id, id, latest_runtime_binding_run_id);

CREATE FUNCTION guard_runtime_binding_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'binding history is immutable'; END IF;
  IF (to_jsonb(NEW) - ARRAY['status','result_json','finished_at','error_code']) IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['status','result_json','finished_at','error_code']) THEN
    RAISE EXCEPTION 'binding inputs are immutable';
  END IF;
  IF OLD.status IN ('completed','failed','superseded','cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'completed binding run is immutable';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER immutable_runtime_binding_run BEFORE UPDATE OR DELETE ON runtime_binding_runs
FOR EACH ROW EXECUTE FUNCTION guard_runtime_binding_run();

DROP TRIGGER immutable_history ON problems;
CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON problems FOR EACH ROW
EXECUTE FUNCTION product_immutable('title,visibility,current_revision_id,latest_build_id,current_page_build_id,lock_version,updated_at,current_source_version_id,current_candidate_id,latest_extraction_run_id,understanding_generation,latest_runtime_binding_run_id');
