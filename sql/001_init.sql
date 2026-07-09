-- 001_init.sql — core schema. Dimension 1024 = Task 2 decision (bge-m3).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE domains (
    name        text PRIMARY KEY,
    description text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    domain      text NOT NULL REFERENCES domains(name),
    dtype       text NOT NULL CHECK (dtype IN
                  ('concept','lesson','signal','source','synthesis','memory','reference','index')),
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    meta        jsonb NOT NULL DEFAULT '{}',
    provenance  jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived','refuted')),
    refuted_reason   text,
    refuted_evidence text,
    refuted_at       timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz,
    -- spec §7: reason/evidence/timestamp are DB-enforced here; the additional
    -- supersedes/contradicts-edge + audit-row requirement is enforced by a
    -- trigger added with the curation task in Plan 2.
    CONSTRAINT refuted_requires_justification CHECK (
        status <> 'refuted'
        OR (refuted_reason IS NOT NULL AND refuted_evidence IS NOT NULL AND refuted_at IS NOT NULL)
    )
);
CREATE INDEX idx_documents_domain ON documents(domain);
CREATE INDEX idx_documents_status ON documents(status);

CREATE TABLE chunks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx         int  NOT NULL,
    content     text NOT NULL,
    embedding   halfvec(1024),
    tsv_en tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    tsv_de tsvector GENERATED ALWAYS AS (to_tsvector('german', content)) STORED,
    UNIQUE (document_id, idx)
);
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_tsv_en ON chunks USING gin (tsv_en);
CREATE INDEX idx_chunks_tsv_de ON chunks USING gin (tsv_de);

CREATE TABLE edges (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    src_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    dst_id     uuid REFERENCES documents(id) ON DELETE SET NULL,
    dst_slug   text NOT NULL,          -- survives even when dst_id is NULL (dangling)
    predicate  text NOT NULL CHECK (predicate IN
                 ('references','extends','depends_on','complements','contrasts_with',
                  'informs','part_of','derived_from','supersedes','contradicts',
                  'duplicate_of')),     -- spec §4 vocabulary, typos rejected
    evidence   text,
    confidence text CHECK (confidence IS NULL OR confidence IN ('high','medium','low')),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to   timestamptz,
    created_by text NOT NULL CHECK (created_by IN ('migration','mining','manual','claude')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (src_id, dst_slug, predicate)
);
CREATE INDEX idx_edges_src ON edges(src_id, predicate);
CREATE INDEX idx_edges_dst ON edges(dst_id, predicate);
CREATE INDEX idx_edges_dangling ON edges(dst_slug) WHERE dst_id IS NULL;

CREATE TABLE pins (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   uuid REFERENCES documents(id),
    body          text NOT NULL,
    scope         text NOT NULL DEFAULT 'global',
    priority      int  NOT NULL DEFAULT 100,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_verified timestamptz
);

CREATE TABLE mining_queue (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind            text NOT NULL DEFAULT 'mine' CHECK (kind IN ('mine','curate','backup','embed')),
    session_id      text,
    transcript_path text,
    payload         jsonb NOT NULL DEFAULT '{}',
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','done','error')),
    attempts        int NOT NULL DEFAULT 0,
    last_uuid       text,
    last_error      text,
    enqueued_at     timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);

CREATE TABLE audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor       text NOT NULL,
    op          text NOT NULL,
    document_id uuid,
    summary     text NOT NULL,
    at          timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;
CREATE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION set_updated_at();
