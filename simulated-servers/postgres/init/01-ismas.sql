-- Runs once on first Postgres start. n8n uses DB "n8n"; ISMAS data lives in DB "ismas".
CREATE DATABASE ismas;
\connect ismas

SET TIME ZONE 'Asia/Kuala_Lumpur';

CREATE TABLE servers (
    name        TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'up',          -- up | down
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE payloads (
    id          BIGSERIAL PRIMARY KEY,
    server      TEXT NOT NULL,
    type        TEXT NOT NULL,                       -- batch | critical
    sent_at     TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    max_level   TEXT,
    needs_ai    BOOLEAN NOT NULL DEFAULT false,
    body        JSONB NOT NULL
);
CREATE INDEX ON payloads (received_at);

CREATE TABLE events (
    id              BIGSERIAL PRIMARY KEY,
    server          TEXT NOT NULL,
    payload_type    TEXT,
    source          TEXT,
    level           TEXT,
    message         TEXT,
    count           INT NOT NULL DEFAULT 1,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    already_alerted BOOLEAN NOT NULL DEFAULT false,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON events (received_at);
CREATE INDEX ON events (server, received_at);

CREATE TABLE incidents (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    signature        TEXT,
    severity         TEXT,                           -- info | low | medium | high | critical
    title            TEXT,
    root_cause       TEXT,
    affected_servers TEXT[],
    fix_steps        JSONB,
    confidence       NUMERIC(3,2),
    alerted          BOOLEAN NOT NULL DEFAULT false,
    status           TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    ai_raw           JSONB
);
CREATE INDEX ON incidents (signature, created_at);
