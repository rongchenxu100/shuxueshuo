CREATE TABLE tutor_daily_usage (
    day date PRIMARY KEY,
    calls bigint NOT NULL DEFAULT 0 CHECK (calls >= 0)
);
CREATE TABLE tutor_user_daily_usage (
    user_id uuid NOT NULL REFERENCES users(id),
    day date NOT NULL,
    calls bigint NOT NULL DEFAULT 0 CHECK (calls >= 0),
    PRIMARY KEY (user_id, day)
);
CREATE TABLE tutor_session_usage (
    session_id text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    calls bigint NOT NULL DEFAULT 0 CHECK (calls >= 0),
    retry_at double precision NOT NULL DEFAULT 0 CHECK (retry_at >= 0)
);
