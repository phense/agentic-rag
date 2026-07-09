-- 004_graph.sql — real traversal over the edges table (recursive CTEs).

-- Undirected breadth exploration up to p_depth hops, cycle-safe per branch.
CREATE OR REPLACE FUNCTION graph_neighbors(
    p_id uuid, p_depth int DEFAULT 1, p_predicates text[] DEFAULT NULL
) RETURNS TABLE (
    edge_id uuid, src_id uuid, dst_id uuid, predicate text,
    evidence text, confidence text, depth int
) LANGUAGE sql STABLE AS $$
WITH RECURSIVE hops(edge_id, src_id, dst_id, predicate, evidence, confidence,
                    depth, frontier, visited) AS (
    SELECT e.id, e.src_id, e.dst_id, e.predicate, e.evidence, e.confidence, 1,
           CASE WHEN e.src_id = p_id THEN e.dst_id ELSE e.src_id END,
           ARRAY[p_id, CASE WHEN e.src_id = p_id THEN e.dst_id ELSE e.src_id END]
    FROM edges e
    WHERE (e.src_id = p_id OR e.dst_id = p_id) AND e.dst_id IS NOT NULL
      AND (p_predicates IS NULL OR e.predicate = ANY (p_predicates))
  UNION ALL
    SELECT e.id, e.src_id, e.dst_id, e.predicate, e.evidence, e.confidence,
           h.depth + 1,
           CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END,
           h.visited || CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END
    FROM hops h
    JOIN edges e ON (e.src_id = h.frontier OR e.dst_id = h.frontier)
    WHERE h.depth < p_depth AND e.dst_id IS NOT NULL
      AND (p_predicates IS NULL OR e.predicate = ANY (p_predicates))
      AND NOT (CASE WHEN e.src_id = h.frontier THEN e.dst_id ELSE e.src_id END
               = ANY (h.visited))
)
SELECT DISTINCT ON (edge_id) edge_id, src_id, dst_id, predicate,
       evidence, confidence, depth
FROM hops
ORDER BY edge_id, depth
$$;

-- Shortest path (BFS by construction: shorter paths generated first).
CREATE OR REPLACE FUNCTION graph_path(
    p_from uuid, p_to uuid, p_max_depth int DEFAULT 4
) RETURNS TABLE (step int, doc_id uuid, via_predicate text)
LANGUAGE sql STABLE AS $$
WITH RECURSIVE walk(path, preds) AS (
    SELECT ARRAY[p_from], ARRAY[]::text[]
  UNION ALL
    SELECT w.path || n.next_id, w.preds || e.predicate
    FROM walk w
    JOIN edges e ON (e.src_id = w.path[array_length(w.path, 1)]
                  OR e.dst_id = w.path[array_length(w.path, 1)])
    CROSS JOIN LATERAL (
        SELECT CASE WHEN e.src_id = w.path[array_length(w.path, 1)]
                    THEN e.dst_id ELSE e.src_id END AS next_id
    ) n
    WHERE e.dst_id IS NOT NULL
      AND n.next_id IS NOT NULL
      AND NOT n.next_id = ANY (w.path)
      AND w.path[array_length(w.path, 1)] <> p_to
      AND array_length(w.path, 1) <= p_max_depth
),
found AS (
    SELECT path, preds
    FROM walk
    WHERE path[array_length(path, 1)] = p_to
    ORDER BY array_length(path, 1)
    LIMIT 1
)
SELECT i AS step, f.path[i] AS doc_id,
       CASE WHEN i = 1 THEN NULL ELSE f.preds[i - 1] END AS via_predicate
FROM found f, generate_subscripts(f.path, 1) AS i
ORDER BY i
$$;

-- All edges touching a document, ordered by validity start (bi-temporal view).
CREATE OR REPLACE FUNCTION graph_timeline(p_id uuid)
RETURNS TABLE (
    edge_id uuid, src_slug text, dst_slug text, predicate text,
    valid_from timestamptz, valid_to timestamptz
) LANGUAGE sql STABLE AS $$
SELECT e.id, ds.slug, COALESCE(dd.slug, e.dst_slug), e.predicate,
       e.valid_from, e.valid_to
FROM edges e
JOIN documents ds ON ds.id = e.src_id
LEFT JOIN documents dd ON dd.id = e.dst_id
WHERE e.src_id = p_id OR e.dst_id = p_id
ORDER BY e.valid_from, e.id
$$;
