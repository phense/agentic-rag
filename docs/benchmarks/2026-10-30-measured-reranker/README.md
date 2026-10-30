---
title: Measured local reranker configurations
type: reference
readers: [maintainer, operator]
version: 0.6.15
status: measuring
---

# Measured local reranker configurations

Issue62 compares the existing0.6.14ordering module at7a61955 with focused Qwen
and the explicit English-trained Jina tiny local challenger. The public corpus,
three profiles and budgets are frozen before held-out results. Actual resource
measurement is pending; this draft makes no quality or speedup claim.

The [operator procedure](../../local-reranker.md) describes separate adoption and
rollback. Default policy/model/deadline remain unchanged. No production database,
private source, hosted inference or production model service is part of this lab.


## Retained invalid attempts

- Attempt a aborted before PostgreSQL/model startup: the user cgroup delegates
  CPU/memory/pids but has no cpuset controller. A separate capability probe
  proved `CPUAffinity=0-3` and quota400% with8GiB/zero swap. The wrapper now verifies
  actual evaluator and child affinity instead of assuming cpuset delegation.
- Attempt b at b16ee74 exited1 after retaining all development/held-out outputs.
  Its current-status fixture was authored without replacement, several fresh
  questions returned no lexical candidates, and busy native idle-endpoint reads
  timed out. It had39/40development and15/18held-out sources indexed. Its quality
  outputs are invalid. Cleanup verified all owned parents and cgroup descendants
  stopped; peak1,643,061,248bytes, no OOM. The rejected corpus is retained as
  `agentic_rag/benchmark/corpus-reranker-rejected-v1.json` and in that revision.
  Fresh corpus-v2 uses new held-out identities after dev-only route validation.
