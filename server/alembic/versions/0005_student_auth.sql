CREATE TABLE student_phone_identities (
    phone text PRIMARY KEY CHECK (phone ~ '^1[3-9][0-9]{9}$'),
    user_id uuid NOT NULL UNIQUE REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE student_login_sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);
CREATE INDEX ix_student_login_user ON student_login_sessions(user_id);
CREATE TABLE student_sms_challenges (
    id uuid PRIMARY KEY,
    phone text NOT NULL,
    code_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    consumed_at timestamptz
);
CREATE INDEX ix_student_sms_phone ON student_sms_challenges(phone, created_at DESC);
CREATE TABLE student_auth_limits (
    key text PRIMARY KEY,
    count integer NOT NULL CHECK (count > 0),
    expires_at timestamptz NOT NULL
);

-- The app still cannot INSERT users/workspaces/members directly. This function
-- creates only phone-linked student identities and never grants workspace roles.
CREATE FUNCTION register_student_phone(p_phone text, p_id uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE result uuid;
BEGIN
    IF p_phone !~ '^1[3-9][0-9]{9}$' THEN RAISE EXCEPTION 'invalid phone'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('student-phone:' || p_phone, 0));
    SELECT user_id INTO result FROM public.student_phone_identities WHERE phone = p_phone;
    IF result IS NULL THEN
        INSERT INTO public.users(id, key, display_name)
            VALUES (p_id, 'student:' || p_id::text, '同学');
        INSERT INTO public.student_phone_identities(phone, user_id) VALUES (p_phone, p_id);
        result := p_id;
    END IF;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION register_student_phone(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION register_student_phone(text, uuid) TO product_app;
