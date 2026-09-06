# Retrieval quality (RAG-008, issue #8)

Status: accepted under the user's next-issue implementation instruction.
Improve the existing hybrid search result budget and source snippets. Repeated chunks
currently crowd out other documents; prefix snippets hide late matches. Keep all
existing scope, evidence, temporal and privilege boundaries. No new hosted query model.

Deliver measured document-aware diversity, contiguous query-centered evidence spans,
stable chunk citations and deterministic ties. Evaluate bounded existing-graph expansion,
a local reranker seam with failure fallback, and negative-query relevance separately.
No unconditional query rewrite or added model is justified without measured benefit.
