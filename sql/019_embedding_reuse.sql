-- Disposable derived vectors only. Untagged legacy vectors are never imported.
CREATE TABLE embedding_reuse_cache (
    model_key text NOT NULL CHECK (model_key ~ '^[0-9a-f]{64}$'),
    representation text NOT NULL CHECK (representation IN ('raw-v1','context-v1')),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    embedding halfvec(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(model_key,representation,input_hash)
);
CREATE INDEX embedding_reuse_fifo ON embedding_reuse_cache(created_at,model_key,representation,input_hash);
GRANT SELECT ON embedding_reuse_cache TO rag_reader,rag_writer;
GRANT ALL ON embedding_reuse_cache TO rag_admin;

CREATE FUNCTION put_embedding_reuse(p_model text,p_representation text,p_hashes text[],p_vectors text[],p_actor text)
RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog,public AS $$
DECLARE inserted int; excess int; evicted int;
BEGIN
    IF p_model IS NULL OR p_model !~ '^[0-9a-f]{64}$'
       OR p_representation IS NULL OR p_representation NOT IN ('raw-v1','context-v1')
       OR p_actor IS NULL OR length(p_actor) NOT BETWEEN 1 AND 64
       OR p_hashes IS NULL OR p_vectors IS NULL
       OR cardinality(p_hashes) <> cardinality(p_vectors) OR cardinality(p_hashes) > 256
       OR EXISTS (SELECT 1 FROM unnest(p_hashes) AS h WHERE h IS NULL OR h !~ '^[0-9a-f]{64}$')
       OR EXISTS (SELECT 1 FROM unnest(p_vectors) AS v WHERE v IS NULL) THEN
        RAISE EXCEPTION 'invalid embedding reuse batch';
    END IF;
    IF cardinality(p_hashes)=0 THEN RETURN 0; END IF;
    -- Every mutation/eviction uses this one nonblocking transaction lock.
    -- Contention skips persistence; it never waits on another document/batch writer.
    IF NOT pg_try_advisory_xact_lock(5840919371552421::bigint) THEN RETURN 0; END IF;
    INSERT INTO public.embedding_reuse_cache(model_key,representation,input_hash,embedding)
    SELECT p_model,p_representation,h,v::public.halfvec(1024)
    FROM unnest(p_hashes,p_vectors) AS t(h,v) ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS inserted = ROW_COUNT;
    SELECT greatest(count(*)-8192,0)::int INTO excess FROM public.embedding_reuse_cache;
    DELETE FROM public.embedding_reuse_cache WHERE (model_key,representation,input_hash) IN
      (SELECT model_key,representation,input_hash FROM public.embedding_reuse_cache
       ORDER BY created_at,model_key,representation,input_hash LIMIT excess);
    GET DIAGNOSTICS evicted = ROW_COUNT;
    IF inserted+evicted>0 THEN
        INSERT INTO public.audit_log(actor,op,summary)
        VALUES (p_actor,'embedding_reuse',format('derived vectors inserted=%s evicted=%s',inserted,evicted));
    END IF;
    RETURN inserted;
END $$;
REVOKE ALL ON FUNCTION put_embedding_reuse(text,text,text[],text[],text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION put_embedding_reuse(text,text,text[],text[],text) TO rag_writer,rag_admin;
