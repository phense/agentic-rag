-- RAG-068-A1: correct supersession whose ONLY authority was generated context.
-- Ordinary refutation/withdrawal/expiry still never revives an older value.
-- Redefine only the invoker predicate. Preserve every assertion, edge, source,
-- lifecycle decision, function signature, owner and existing grant.
CREATE OR REPLACE FUNCTION public.rag_assertion_eligible_base(p_id uuid, p_at timestamptz DEFAULT now(), p_history boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE AS $$
SELECT (p_history AND NOT EXISTS (SELECT 1 FROM synthesis_patterns sp WHERE sp.document_id=p_id))
OR (claim_eligible(p_id) AND NOT EXISTS (
    SELECT 1 FROM fact_assertions a JOIN documents d ON d.id=a.document_id
    WHERE a.document_id=p_id AND (
        a.disposition <> 'accepted' OR a.event_at IS NULL OR a.event_at > p_at
        OR (a.expires_at IS NOT NULL AND a.expires_at <= p_at)
        OR EXISTS (
            SELECT 1 FROM fact_assertions newer JOIN documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute
              AND nd.project_scope=d.project_scope AND nd.domain=d.domain
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND (claim_eligible(newer.document_id) OR NOT EXISTS (
                  SELECT 1 FROM claim_evidence ce
                  JOIN knowledge_sources ks USING (source_key)
                  WHERE ce.document_id=newer.document_id
                  HAVING bool_and(COALESCE(ks.state='removed'
                    AND starts_with(ks.reason,'native_generated_origin:'), false))
              ))
              AND newer.event_at > a.event_at AND newer.event_at <= p_at
        )
    )
))
$$;
