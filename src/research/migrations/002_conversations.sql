-- Full conversation lineage:
-- conversation -> message -> run -> round -> provider call (with full request and response),
-- plus every progress event. API keys are never stored.

CREATE TABLE IF NOT EXISTS research.conversations (
    id         uuid PRIMARY KEY,
    title      text NOT NULL DEFAULT '',
    pending    jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research.messages (
    id              uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES research.conversations(id) ON DELETE CASCADE,
    seq             integer NOT NULL,
    role            text NOT NULL CHECK (role IN ('user', 'assistant')),
    content         text NOT NULL,
    instructions    text NOT NULL DEFAULT '',
    kind            text,
    reply_to        uuid REFERENCES research.messages(id),
    run_id          uuid REFERENCES research.runs(id),
    -- what the chat understood: the parsed target, the pending question it answered, the action taken
    context         jsonb NOT NULL DEFAULT '{}',
    payload         jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, seq)
);

ALTER TABLE research.runs
    ADD COLUMN IF NOT EXISTS conversation_id uuid REFERENCES research.conversations(id),
    ADD COLUMN IF NOT EXISTS message_id uuid REFERENCES research.messages(id);

CREATE TABLE IF NOT EXISTS research.provider_calls (
    id           bigserial PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES research.runs(id) ON DELETE CASCADE,
    round_number integer NOT NULL,
    seq          integer NOT NULL,
    provider     text NOT NULL CHECK (provider IN ('search', 'model')),
    purpose      text NOT NULL,
    attempt      integer NOT NULL DEFAULT 1,
    request      jsonb NOT NULL,
    response     jsonb,
    error        text,
    duration_ms  double precision NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);

CREATE TABLE IF NOT EXISTS research.events (
    id              bigserial PRIMARY KEY,
    conversation_id uuid REFERENCES research.conversations(id) ON DELETE CASCADE,
    message_id      uuid REFERENCES research.messages(id) ON DELETE CASCADE,
    run_id          uuid REFERENCES research.runs(id) ON DELETE CASCADE,
    step            text NOT NULL,
    status          text NOT NULL,
    data            jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_run ON research.events (run_id);
CREATE INDEX IF NOT EXISTS events_message ON research.events (message_id);
CREATE INDEX IF NOT EXISTS messages_conversation ON research.messages (conversation_id, seq);
