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
