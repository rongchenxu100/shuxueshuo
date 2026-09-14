-- Immutable history, explicit mutable columns, and cross-table consistency.
CREATE FUNCTION product_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE allowed text[] := string_to_array(TG_ARGV[0], ',');
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'product history cannot be deleted'; END IF;
  IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed) THEN
    RAISE EXCEPTION 'immutable fields in %', TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION product_once() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE field text;
BEGIN
  FOREACH field IN ARRAY TG_ARGV LOOP
    IF to_jsonb(OLD)->field <> 'null'::jsonb AND to_jsonb(NEW)->field IS DISTINCT FROM to_jsonb(OLD)->field THEN
      RAISE EXCEPTION 'field may only be completed once: %.%', TG_TABLE_NAME, field;
    END IF;
  END LOOP;
  RETURN NEW;
END $$;

CREATE FUNCTION product_relations() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_no integer; expected_problem uuid; expected_build uuid;
BEGIN
  IF TG_TABLE_NAME = 'problem_revisions' AND to_jsonb(NEW)->>'parent_revision_id' IS NOT NULL THEN
    SELECT revision_no INTO parent_no FROM problem_revisions WHERE id = NEW.parent_revision_id;
    IF parent_no IS NULL OR parent_no >= NEW.revision_no THEN RAISE EXCEPTION 'revision parent order'; END IF;
  ELSIF TG_TABLE_NAME = 'page_builds' THEN
    SELECT problem_id INTO expected_problem FROM builds WHERE id = NEW.build_id;
    IF NOT EXISTS (SELECT 1 FROM problem_revisions WHERE id = NEW.revision_id AND problem_id = expected_problem) THEN
      RAISE EXCEPTION 'page revision belongs to another problem';
    END IF;
  ELSIF TG_TABLE_NAME = 'problems' AND to_jsonb(NEW)->>'current_page_build_id' IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM page_builds p JOIN builds b ON b.id = p.build_id
      WHERE p.id = NEW.current_page_build_id AND b.problem_id = NEW.id AND p.revision_id = NEW.current_revision_id) THEN
      RAISE EXCEPTION 'current page revision mismatch';
    END IF;
  ELSIF TG_TABLE_NAME = 'stage_attempts' AND to_jsonb(NEW)->>'execution_id' IS NOT NULL THEN
    SELECT build_id INTO expected_build FROM build_stages WHERE id = NEW.build_stage_id;
    IF NOT EXISTS (SELECT 1 FROM job_executions e JOIN jobs j ON j.id=e.job_id
      WHERE e.id=NEW.execution_id AND j.build_id=expected_build) THEN RAISE EXCEPTION 'attempt execution mismatch'; END IF;
  ELSIF TG_TABLE_NAME = 'artifacts' AND to_jsonb(NEW)->>'producer_attempt_id' IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM stage_attempts a JOIN build_stages s ON s.id=a.build_stage_id
      WHERE a.id=NEW.producer_attempt_id AND s.build_id=NEW.producer_build_id) THEN RAISE EXCEPTION 'artifact producer mismatch'; END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION product_stage_set() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bid uuid; definition jsonb; expected jsonb; actual jsonb;
BEGIN
  bid := CASE WHEN TG_TABLE_NAME = 'builds' THEN NEW.id ELSE (to_jsonb(NEW)->>'build_id')::uuid END;
  SELECT pipeline_snapshot INTO definition FROM builds WHERE id=bid;
  SELECT jsonb_agg(jsonb_build_array(s->>'stage_key', (s->>'ordinal')::integer) ORDER BY (s->>'ordinal')::integer)
    INTO expected FROM jsonb_array_elements(definition->'stages') s;
  SELECT jsonb_agg(jsonb_build_array(stage_key, ordinal) ORDER BY ordinal) INTO actual FROM build_stages WHERE build_id=bid;
  IF expected IS NULL OR expected IS DISTINCT FROM actual THEN RAISE EXCEPTION 'pipeline stage set mismatch'; END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION product_attempt_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'running' AND NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'completed attempt is immutable'; END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER freeze_completed_attempt BEFORE UPDATE ON stage_attempts FOR EACH ROW EXECUTE FUNCTION product_attempt_frozen();
CREATE TRIGGER revision_parent BEFORE INSERT ON problem_revisions FOR EACH ROW EXECUTE FUNCTION product_relations();
CREATE TRIGGER page_relation BEFORE INSERT ON page_builds FOR EACH ROW EXECUTE FUNCTION product_relations();
CREATE TRIGGER current_page_relation BEFORE INSERT OR UPDATE ON problems FOR EACH ROW EXECUTE FUNCTION product_relations();
CREATE TRIGGER attempt_relation BEFORE INSERT ON stage_attempts FOR EACH ROW EXECUTE FUNCTION product_relations();
CREATE TRIGGER artifact_relation BEFORE INSERT ON artifacts FOR EACH ROW EXECUTE FUNCTION product_relations();
CREATE CONSTRAINT TRIGGER build_stage_set AFTER INSERT ON builds DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product_stage_set();
CREATE CONSTRAINT TRIGGER stage_build_set AFTER INSERT OR UPDATE ON build_stages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product_stage_set();
CREATE TRIGGER once_revision BEFORE UPDATE ON builds FOR EACH ROW EXECUTE FUNCTION product_once('resolved_revision_id');
CREATE TRIGGER once_initial_build BEFORE UPDATE ON batch_items FOR EACH ROW EXECUTE FUNCTION product_once('initial_build_id');
CREATE TRIGGER once_match BEFORE UPDATE ON problem_sources FOR EACH ROW EXECUTE FUNCTION product_once('matched_revision_id');
CREATE TRIGGER once_normalized BEFORE UPDATE ON sources FOR EACH ROW EXECUTE FUNCTION product_once('normalized_artifact_id');

DO $$
DECLARE spec record;
BEGIN
  FOR spec IN SELECT * FROM (VALUES
    ('users','display_name,updated_at'), ('workspaces','name,updated_at'), ('workspace_members',''),
    ('batches','name,updated_at'), ('batch_items','initial_build_id'), ('sources','normalized_artifact_id'),
    ('problems','title,visibility,current_revision_id,latest_build_id,current_page_build_id,lock_version,updated_at'),
    ('problem_sources','matched_revision_id'), ('problem_revisions',''),
    ('builds','resolved_revision_id,status,started_at,finished_at,error_code'),
    ('jobs','status,execution_epoch,active_execution_id,lease_expires_at,cancel_requested_at,delivery_count'),
    ('job_executions','status,heartbeat_at,finished_at,failure_code'),
    ('build_stages','status,accepted_attempt_id,summary'),
    ('stage_attempts','status,finished_at,manifest_json,manifest_artifact_id,manifest_sha256,checkpoint_artifact_id'),
    ('artifacts','availability'), ('stage_artifacts',''), ('artifact_dependencies',''), ('model_calls',''),
    ('stage_call_refs',''), ('diagnostics',''), ('page_builds',''), ('page_assets',''), ('review_decisions',''),
    ('idempotency_requests',''), ('event_streams','last_seq,min_retained_seq'), ('events',''),
    ('outbox_messages','status,attempt_count,available_at,locked_until,publisher_token,published_at,last_error')
  ) AS specs(tbl, cols) LOOP
    EXECUTE format('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION product_immutable(%L)', spec.tbl, spec.cols);
  END LOOP;
END $$;
