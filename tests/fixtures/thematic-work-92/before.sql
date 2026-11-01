
      WITH matches AS (
        SELECT d.id document_id,c.id chunk_id,c.idx,
          ts_rank_cd(c.tsv_en,websearch_to_tsquery('english',%(query)s)) +
          ts_rank_cd(c.tsv_de,websearch_to_tsquery('german',%(query)s)) rank
        FROM chunks c JOIN documents d ON d.id=c.document_id
        LEFT JOIN fact_assertions a ON a.document_id=d.id
        WHERE (c.tsv_en @@ websearch_to_tsquery('english',%(query)s)
            OR c.tsv_de @@ websearch_to_tsquery('german',%(query)s))
          AND d.status='active' AND d.project_scope=ANY(%(scopes)s)
          AND (%(domain)s::text IS NULL OR d.domain=%(domain)s)
          AND claim_eligible(d.id)
          AND CASE WHEN %(history)s THEN a.document_id IS NULL OR
            (a.disposition='accepted' AND a.event_at<=statement_timestamp()
             AND (a.expires_at IS NULL OR a.expires_at>statement_timestamp()))
            ELSE assertion_eligible(d.id,statement_timestamp()) END
      ), chosen AS (
        SELECT DISTINCT ON (document_id) document_id,chunk_id,rank FROM matches
        ORDER BY document_id,rank DESC,idx,chunk_id
      ), pool AS (
        SELECT * FROM chosen ORDER BY rank DESC,document_id LIMIT 25
      ), versions AS (
        SELECT d.id document_id,c.id chunk_id,left(d.title,160) title,d.slug,d.domain,
          d.project_scope,d.dtype,d.created_at,a.event_at,a.expires_at,
          COALESCE(cr.kind,'legacy') source_kind,COALESCE(cr.review_state,'unreviewed') review_state,
          d.xmin::text document_version,c.xmin::text chunk_version,
          cr.xmin::text claim_version,a.xmin::text assertion_version,
          (SELECT md5(string_agg(concat_ws(':',e.source_key,e.span_hash,e.xmin::text,s.xmin::text),
            ',' ORDER BY e.source_key,e.span_hash)) FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
            WHERE e.document_id=d.id) sources_version,
          (SELECT md5(string_agg(concat_ws(':',z.source_hash,z.xmin::text),',' ORDER BY z.source_hash))
            FROM assertion_sources z WHERE z.document_id=d.id) assertion_sources_version,
          EXISTS(SELECT 1 FROM fact_assertions newer JOIN documents nd ON nd.id=newer.document_id
            WHERE newer.entity=a.entity AND newer.attribute=a.attribute AND nd.project_scope=d.project_scope
              AND nd.domain=d.domain -- same domain isolation as assertion_eligible (migration020)
              AND newer.disposition='accepted' AND newer.relation='replacement'
              AND newer.event_at>a.event_at AND newer.event_at<=statement_timestamp()) superseded,
          COALESCE((SELECT jsonb_agg(to_jsonb(x)) FROM (
            SELECT s.source_key,e.span_hash,s.xmin::text source_version,e.xmin::text span_version,
              s.role,s.source_at,e.complete,e.reviewed
            FROM claim_evidence e JOIN knowledge_sources s USING(source_key)
            WHERE e.document_id=d.id AND s.state='active'
              AND ((cr.review_state='confirmed' AND e.reviewed) OR (cr.kind='stated' AND s.role='user' AND e.complete))
            ORDER BY s.source_key,e.span_hash LIMIT 8
          ) x),'[]'::jsonb) sources,
          (SELECT count(*)>8 FROM claim_evidence e WHERE e.document_id=d.id) sources_omitted,
          pool.rank
        FROM pool JOIN documents d ON d.id=pool.document_id JOIN chunks c ON c.id=pool.chunk_id
        LEFT JOIN claim_records cr ON cr.document_id=d.id LEFT JOIN fact_assertions a ON a.document_id=d.id
      )
      SELECT (SELECT to_jsonb(t) FROM thematic_summaries t WHERE selection_key=%(key)s) cache,
        COALESCE((SELECT jsonb_agg(to_jsonb(v) ORDER BY rank DESC,document_id) FROM versions v),'[]'::jsonb) candidates
      