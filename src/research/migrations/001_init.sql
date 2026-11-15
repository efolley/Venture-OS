-- Research agent storage. Every round is written in 1 transaction, so a crashed run
-- keeps all earlier rounds. Round 0 holds the understanding step and carried-over evidence.
CREATE SCHEMA IF NOT EXISTS research;

CREATE TABLE IF NOT EXISTS research.runs (
    id            uuid PRIMARY KEY,
    parent_run_id uuid REFERENCES research.runs(id),
    company       text NOT NULL,
    website       text NOT NULL DEFAULT '',
    instructions  text NOT NULL DEFAULT '',
    gaps          text[] NOT NULL DEFAULT '{}',
    status        text NOT NULL CHECK (status IN ('running', 'clarify', 'complete', 'partial', 'failed')),
    limits        jsonb NOT NULL,
    usage         jsonb NOT NULL DEFAULT '{}',
    candidates    jsonb NOT NULL DEFAULT '[]',
    notes         jsonb NOT NULL DEFAULT '[]',
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research.rounds (
    run_id      uuid NOT NULL REFERENCES research.runs(id) ON DELETE CASCADE,
    number      integer NOT NULL CHECK (number >= 0),
    gap         text NOT NULL,
    query       text NOT NULL DEFAULT '',
    site        text NOT NULL DEFAULT '',
    model_calls integer NOT NULL DEFAULT 0,
    dropped     jsonb NOT NULL DEFAULT '[]',
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, number)
);

CREATE TABLE IF NOT EXISTS research.sources (
    run_id           uuid NOT NULL REFERENCES research.runs(id) ON DELETE CASCADE,
    url              text NOT NULL,
    round_number     integer NOT NULL,
    source_id        text,
    title            text NOT NULL DEFAULT '',
    domain           text NOT NULL DEFAULT '',
    kind             text NOT NULL DEFAULT 'other',
    text             text NOT NULL DEFAULT '',
    published_at     text,
    retrieved_at     timestamptz,
    rejection_reason text,
    PRIMARY KEY (run_id, url),
    UNIQUE (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS research.evidence_items (
    run_id       uuid NOT NULL REFERENCES research.runs(id) ON DELETE CASCADE,
    item_id      text NOT NULL,
    round_number integer NOT NULL,
    source_id    text NOT NULL,
    item         jsonb NOT NULL,
    tags         text[] NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
CREATE INDEX IF NOT EXISTS evidence_items_tags ON research.evidence_items USING gin (tags);

CREATE TABLE IF NOT EXISTS research.coverage_snapshots (
    run_id       uuid NOT NULL REFERENCES research.runs(id) ON DELETE CASCADE,
    round_number integer NOT NULL,
    coverage     jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, round_number)
);

CREATE TABLE IF NOT EXISTS research.packs (
    run_id         uuid PRIMARY KEY REFERENCES research.runs(id) ON DELETE CASCADE,
    schema_version integer NOT NULL,
    status         text NOT NULL,
    pack           jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
