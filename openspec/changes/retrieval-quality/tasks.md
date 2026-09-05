# Tasks — RAG-008

- [x] T001 Create reproducible crowding/late-span/symbol/German/negative/multihop
  fixtures and meaningful failing tests against prior search (RQ001–004).
- [x] T002 Implement migration013 fair candidate pools, stable diversity and contiguous
  query spans with source offsets; preserve all eligibility gates (RQ001/002/004).
- [x] T003 Implement optional bounded graph/local reranker seams, deterministic failure
  fallback and exact-symbol preservation. Calibrate negative relevance; retain no generic
  cutoff/rewrite unless measured gain justifies it (RQ003/004). Depends T002.
- [x] T004 Publish equal-budget before/after and separate graph/rerank/query experiments,
  inspect held-out evidence and latency, independent review/fixes, full suite/wheel,
  user docs/backlog/features (all RQ). Depends T001–003.
- [ ] T005 Backup-gated migration/activation, unchanged legacy/pin verification,
  publication/CI/issue closure and OpenSpec archive (compatibility). Depends T004.
