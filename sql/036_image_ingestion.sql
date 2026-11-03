-- RAG-070: retained image originals and versioned local derivations.
-- Additive only: empty tables, grants and policies. No existing row, policy,
-- function, grant or vector is changed; upgrading performs no image processing.
--
-- An original carries an immutable copy of its authorized write scope so its
-- policy can apply the migration035 document predicate to its own columns.
-- Derivations are visible only through their original. Neither policy reads
-- documents, claim evidence or sources, so policy evaluation cannot recurse.
-- Source trust and claim review stay in the existing evidence registry and are
-- enforced by the audited image gateway.
CREATE TABLE public.image_originals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key text NOT NULL UNIQUE REFERENCES public.knowledge_sources(source_key),
    domain text NOT NULL REFERENCES public.domains(name),
    project_scope text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    mime text NOT NULL CHECK (mime IN ('image/png','image/jpeg','image/webp')),
    width integer NOT NULL CHECK (width BETWEEN 1 AND 8192),
    height integer NOT NULL CHECK (height BETWEEN 1 AND 8192),
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 4194304),
    bytes bytea,
    erased_at timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (width::bigint * height <= 16000000),
    CHECK ((erased_at IS NULL AND bytes IS NOT NULL AND octet_length(bytes) = byte_size
            AND encode(sha256(bytes),'hex') = sha256) OR (erased_at IS NOT NULL AND bytes IS NULL))
);
CREATE INDEX image_originals_scope ON public.image_originals(domain, project_scope);

CREATE TABLE public.image_derivations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    original_id uuid NOT NULL REFERENCES public.image_originals(id),
    kind text NOT NULL CHECK (kind IN ('ocr','interpretation')),
    identity_hash text NOT NULL CHECK (identity_hash ~ '^[0-9a-f]{64}$'),
    identity jsonb NOT NULL CHECK (jsonb_typeof(identity) = 'object'),
    status text NOT NULL CHECK (status IN ('text','empty')),
    text text NOT NULL CHECK (length(text) <= 32000),
    text_sha256 text NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$'),
    regions jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(regions) = 'array' AND jsonb_array_length(regions) <= 5000),
    warnings jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(warnings) = 'array'),
    -- A purged refuted claim leaves its derivation as history (no re-creation).
    document_id uuid REFERENCES public.documents(id) ON DELETE SET NULL,
    previous_id uuid REFERENCES public.image_derivations(id),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (original_id, kind, identity_hash),
    CHECK (status = 'text' OR document_id IS NULL)
);
CREATE INDEX image_derivations_document ON public.image_derivations(document_id) WHERE document_id IS NOT NULL;

-- Insert-only for the limited roles: identities and retained bytes are immutable.
GRANT SELECT ON public.image_originals, public.image_derivations TO rag_reader;
GRANT SELECT, INSERT ON public.image_originals, public.image_derivations TO rag_writer;
GRANT ALL ON public.image_originals, public.image_derivations TO rag_admin;

ALTER TABLE public.image_originals ENABLE ROW LEVEL SECURITY;
-- Same scope rule as documents, through the stable 021 helper (not the 035
-- initplan helper), so the documented 035 policy rollback stays valid on a
-- store with image tables. Access here is by key, never a large scan.
CREATE POLICY service_image_originals ON public.image_originals
 USING (public.rag_service_document(domain, project_scope))
 WITH CHECK (public.rag_service_document(domain, project_scope, true));

ALTER TABLE public.image_derivations ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_image_derivations ON public.image_derivations
 USING (NOT public.rag_service_active() OR EXISTS (
   SELECT 1 FROM public.image_originals o WHERE o.id = original_id))
 WITH CHECK (NOT public.rag_service_active() OR EXISTS (
   SELECT 1 FROM public.image_originals o WHERE o.id = original_id
     AND public.rag_service_document(o.domain, o.project_scope, true)));
