-- Additive exact identities. Never rewrite original assertion keys or evidence.
CREATE TABLE entity_identities (
    id uuid PRIMARY KEY,
    project_scope text NOT NULL CHECK (project_scope <> 'unknown'),
    domain text NOT NULL REFERENCES domains(name),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 2000),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(project_scope,domain,name)
);
CREATE TABLE assertion_entities (
    document_id uuid PRIMARY KEY REFERENCES fact_assertions(document_id) ON DELETE CASCADE,
    entity_id uuid NOT NULL REFERENCES entity_identities(id),
    indexed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX assertion_entities_identity ON assertion_entities(entity_id);
CREATE TABLE entity_aliases (
    document_id uuid PRIMARY KEY REFERENCES claim_records(document_id) ON DELETE CASCADE,
    request_key text NOT NULL UNIQUE,
    alias_id uuid NOT NULL REFERENCES entity_identities(id),
    target_id uuid NOT NULL REFERENCES entity_identities(id),
    source_key text NOT NULL,
    span_hash text NOT NULL,
    effective_at timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN ('review','accepted','revoked')),
    reason text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    CHECK (alias_id <> target_id),
    FOREIGN KEY(document_id,source_key,span_hash)
        REFERENCES claim_evidence(document_id,source_key,span_hash) ON DELETE CASCADE
);
CREATE INDEX entity_aliases_alias ON entity_aliases(alias_id,state);
CREATE INDEX entity_aliases_target ON entity_aliases(target_id,state);
GRANT SELECT ON entity_identities,assertion_entities,entity_aliases TO rag_reader;
GRANT SELECT,INSERT ON entity_identities,assertion_entities,entity_aliases TO rag_writer;
GRANT UPDATE(entity_id,indexed_at) ON assertion_entities TO rag_writer;
GRANT UPDATE(state,reason,changed_at) ON entity_aliases TO rag_writer;
GRANT ALL ON entity_identities,assertion_entities,entity_aliases TO rag_admin;
