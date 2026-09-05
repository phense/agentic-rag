CREATE TABLE knowledge_sources (
    source_key text PRIMARY KEY,
    namespace text NOT NULL,
    source_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('user','assistant','unknown')),
    source_at timestamptz,
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active','refuted','removed')),
    reason text,
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE claim_records (
    document_id uuid PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('stated','proposal','hypothetical','inference')),
    review_state text NOT NULL DEFAULT 'unreviewed' CHECK (review_state IN ('unreviewed','confirmed','refuted')),
    reason text,
    content_hash text NOT NULL
);
CREATE TABLE claim_evidence (
    document_id uuid NOT NULL REFERENCES claim_records(document_id) ON DELETE CASCADE,
    source_key text NOT NULL REFERENCES knowledge_sources(source_key),
    span_hash text NOT NULL,
    quote text NOT NULL,
    complete boolean NOT NULL,
    reviewed boolean NOT NULL DEFAULT false,
    PRIMARY KEY(document_id,source_key,span_hash)
);
CREATE INDEX claim_evidence_source ON claim_evidence(source_key);
CREATE INDEX claim_records_content ON claim_records(content_hash,kind);
GRANT SELECT ON knowledge_sources,claim_records,claim_evidence TO rag_reader;
GRANT SELECT,INSERT,UPDATE ON knowledge_sources,claim_records TO rag_writer;
GRANT SELECT,INSERT ON claim_evidence TO rag_writer;
GRANT UPDATE(reviewed) ON claim_evidence TO rag_writer;
GRANT ALL ON knowledge_sources,claim_records,claim_evidence TO rag_admin;

CREATE FUNCTION claim_eligible(p_id uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT NOT EXISTS(SELECT 1 FROM claim_records c WHERE c.document_id=p_id)
OR EXISTS (
    SELECT 1 FROM claim_records c WHERE c.document_id=p_id AND c.review_state<>'refuted'
    AND (c.review_state='confirmed' OR c.kind='stated')
    AND EXISTS(SELECT 1 FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
               WHERE e.document_id=c.document_id AND s.state='active'
               AND ((c.review_state='confirmed' AND e.reviewed) OR (c.kind='stated' AND s.role='user' AND e.complete)))
)
$$;

-- Every existing temporal search/hook/selected graph path calls this predicate.
CREATE OR REPLACE FUNCTION assertion_eligible(p_id uuid, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT p_history OR (claim_eligible(p_id) AND NOT EXISTS (
    SELECT 1 FROM fact_assertions a JOIN documents d ON d.id=a.document_id
    WHERE a.document_id=p_id AND (
        a.disposition <> 'accepted' OR a.event_at IS NULL OR a.event_at > p_at
        OR (a.expires_at IS NOT NULL AND a.expires_at <= p_at)
        OR EXISTS (
            SELECT 1 FROM fact_assertions newer JOIN documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute
              AND nd.project_scope=d.project_scope
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at > a.event_at AND newer.event_at <= p_at
        )
    )
))
$$;
