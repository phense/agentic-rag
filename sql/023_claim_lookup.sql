-- Original022 installations may predate stable human uploader profiles.
-- Retain their session rows; NULL profiles require a fresh explicit login.
ALTER TABLE public.service_sessions ADD COLUMN IF NOT EXISTS uploader_id uuid;

-- Keep the evidence/trust predicate under the caller's existing SELECT and RLS
-- permissions. A SQL OR/EXISTS expression can make PostgreSQL repeatedly scan
-- all source policies for each candidate. Keyed invoker lookups avoid that
-- fanout without bypassing RLS, changing grants, or relaxing eligibility.
CREATE OR REPLACE FUNCTION public.claim_eligible(p_id uuid) RETURNS boolean
LANGUAGE plpgsql STABLE COST 100 AS $$
DECLARE
    claim_kind text;
    claim_review text;
    evidence record;
    source_state text;
    source_role text;
BEGIN
    SELECT c.kind,c.review_state INTO claim_kind,claim_review
      FROM public.claim_records c WHERE c.document_id=p_id;
    IF NOT FOUND THEN RETURN true; END IF;
    IF claim_review='refuted' OR (claim_review<>'confirmed' AND claim_kind<>'stated') THEN
        RETURN false;
    END IF;
    FOR evidence IN
        SELECT e.source_key,e.complete,e.reviewed FROM public.claim_evidence e
          WHERE e.document_id=p_id
    LOOP
        IF (claim_review='confirmed' AND evidence.reviewed)
           OR (claim_kind='stated' AND evidence.complete) THEN
            SELECT s.state,s.role INTO source_state,source_role
              FROM public.knowledge_sources s WHERE s.source_key=evidence.source_key;
            IF FOUND AND source_state='active' AND (
                (claim_review='confirmed' AND evidence.reviewed)
                OR (claim_kind='stated' AND source_role='user' AND evidence.complete)
            ) THEN RETURN true; END IF;
        END IF;
    END LOOP;
    RETURN false;
END $$;
