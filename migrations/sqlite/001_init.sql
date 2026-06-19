-- NOTE: `PRAGMA journal_mode = WAL;` is intentionally omitted. Turso/Hrana rejects it
-- ("SQL not allowed statement") and libsql's executescript then silently aborts the
-- whole migration batch — leaving zero tables created (discovered by 04-03 live run).
-- Turso manages its own storage/journal mode; local SQLite defaults are fine for tests.
PRAGMA foreign_keys = ON;

-- One row per ingested source artifact.
CREATE TABLE IF NOT EXISTS sources (
    id            TEXT PRIMARY KEY,          -- src_<sha256[:12]> (AD-2)
    content_hash  TEXT NOT NULL UNIQUE,      -- sha256 of normalized text
    type          TEXT NOT NULL CHECK (type IN
                    ('Article','Book','Paper','Newsletter','Podcast','Meeting','Note')),
    title         TEXT,
    author        TEXT,
    url           TEXT,
    publisher     TEXT,
    date_published TEXT,                      -- ISO-8601
    date_saved    TEXT NOT NULL,             -- ISO-8601 UTC
    raw_path      TEXT NOT NULL,             -- vault-relative path
    wiki_path     TEXT,                      -- source page path once created
    credibility   REAL DEFAULT 0.5,          -- 0..1
    tags          TEXT,                       -- JSON array
    status        TEXT NOT NULL DEFAULT 'captured'
                    CHECK (status IN
                    ('captured','summarized','extracted','linked','done','error')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_sources_type   ON sources(type);

-- TextUnits: deterministic chunks of a source (provenance spans live here).
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,            -- chk_<source>_<ordinal>
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    char_start  INTEGER NOT NULL,            -- offset into raw text
    char_end    INTEGER NOT NULL,
    token_count INTEGER,
    text        TEXT NOT NULL,
    UNIQUE (source_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

-- Structured summaries (1:1 with source).
CREATE TABLE IF NOT EXISTS summaries (
    source_id   TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    thesis      TEXT,
    body        TEXT NOT NULL,               -- markdown
    model       TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 0.5,
    created_at  TEXT NOT NULL
);

-- Atomic claims (the idea unit). Subject-predicate-object where possible.
CREATE TABLE IF NOT EXISTS claims (
    id          TEXT PRIMARY KEY,            -- clm_<uuid7>
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_id    TEXT REFERENCES chunks(id),  -- provenance span (AD-6)
    statement   TEXT NOT NULL,
    subject     TEXT,
    predicate   TEXT,
    object      TEXT,
    claim_type  TEXT CHECK (claim_type IN
                    ('fact','opinion','prediction','definition','causal','statistic')),
    confidence  REAL NOT NULL DEFAULT 0.5,
    status      TEXT NOT NULL DEFAULT 'candidate'
                    CHECK (status IN ('candidate','approved','merged','rejected')),
    valid_from  TEXT,
    valid_to    TEXT,                        -- temporal validity
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_source ON claims(source_id);

-- Concepts (evergreen pages, canonical).
CREATE TABLE IF NOT EXISTS concepts (
    id          TEXT PRIMARY KEY,            -- cpt_<slug>
    name        TEXT NOT NULL,
    definition  TEXT,
    domain      TEXT,
    wiki_path   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- AD-5 alias resolution tier 2
CREATE TABLE IF NOT EXISTS concept_aliases (
    alias       TEXT NOT NULL,
    concept_id  TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    PRIMARY KEY (alias, concept_id)
);

-- Many-to-many claims <-> concepts
CREATE TABLE IF NOT EXISTS claim_concepts (
    claim_id    TEXT REFERENCES claims(id) ON DELETE CASCADE,
    concept_id  TEXT REFERENCES concepts(id) ON DELETE CASCADE,
    PRIMARY KEY (claim_id, concept_id)
);

-- Entities (companies/authors/industries/etc.) — generic typed table.
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,            -- ent_<type>_<slug>
    type        TEXT NOT NULL,               -- Company|Author|Industry|...
    name        TEXT NOT NULL,
    properties  TEXT,                         -- JSON (ticker, affiliation, ...)
    wiki_path   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (type, name)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias       TEXT NOT NULL,
    entity_id   TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (alias, entity_id)
);

-- Idempotency + observability for every agent invocation.
CREATE TABLE IF NOT EXISTS agent_runs (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    source_id   TEXT,
    input_hash  TEXT NOT NULL,               -- dedupe identical work
    model       TEXT,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cost_usd    REAL,
    status      TEXT NOT NULL,               -- ok|error
    error       TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (agent, input_hash)
);

-- Vector index bookkeeping (Chroma holds vectors; this maps ids).
CREATE TABLE IF NOT EXISTS embeddings_meta (
    object_id   TEXT PRIMARY KEY,            -- claim/concept/chunk id
    object_kind TEXT NOT NULL,               -- claim|concept|chunk
    collection  TEXT NOT NULL,               -- chroma collection name
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    updated_at  TEXT NOT NULL
);

-- FTS5 for BM25 keyword retrieval (MVP-grade search).
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    statement, content='claims', content_rowid='rowid'
);

-- raw_path is immutable after write (AD-2: raw/ is append-only and content-addressed).
CREATE TRIGGER IF NOT EXISTS sources_raw_immutable
BEFORE UPDATE OF raw_path ON sources
BEGIN
    SELECT RAISE(ABORT, 'raw_path is immutable after write');
END;
