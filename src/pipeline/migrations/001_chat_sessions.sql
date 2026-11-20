-- Chat sessions that a person can reopen: 1 row per chat, 1 row per transcript message.
-- Result cards keep their JSON in payload, so a chat reopens fully. API keys are never stored.

CREATE SCHEMA IF NOT EXISTS ventureos;

CREATE TABLE IF NOT EXISTS ventureos.sessions (
    id            uuid PRIMARY KEY,
    title         text NOT NULL DEFAULT '',
    -- the open question the next message answers (pick a website, or research the gaps)
    pending       jsonb,
    active_job_id text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ventureos.messages (
    id         uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES ventureos.sessions(id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    role       text NOT NULL CHECK (role IN ('user', 'assistant')),
    kind       text NOT NULL CHECK (kind IN ('text', 'clarify', 'step', 'pack', 'strategy', 'pm', 'error')),
    text       text NOT NULL DEFAULT '',
    run_id     uuid,
    payload    jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, seq)
);

CREATE INDEX IF NOT EXISTS sessions_updated ON ventureos.sessions (updated_at DESC);
