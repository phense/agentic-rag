-- Add only domain isolation to the existing claim-qualified temporal predicate.
-- Preserve originals, evidence/trust gates, roles and function signature.
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
              AND nd.project_scope=d.project_scope AND nd.domain=d.domain
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at > a.event_at AND newer.event_at <= p_at
        )
    )
))
$$;
