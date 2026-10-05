# Domain-bound assertion verification

Issue: [#48](https://github.com/phense/agentic-rag/issues/48). Base:
`9071693` (0.6.4, schema 019); candidate 0.6.5, schema 020,
`fix/p1-domain-assertions`. All measurements use owned public synthetic
PostgreSQL databases. No production migration, provider call or repair occurs.

## Before and after

| Case | Before | After | Sample |
|---|---|---|---|
| Equal event/value in two domains | One document; foreign-domain duplicate returned | Two accepted originals and domain-local source attachments | Both insertion orders |
| Different values at the same event time in two domains | Second original is review-only | Both originals accepted; own-domain duplicates still reuse their original | Both insertion orders |
| Two independent old facts and one general replacement | Programming original suppressed or collapsed | Programming original stays eligible; general current selects its replacement | All six insertion orders |

Regression command: `uv run pytest -q tests/test_domain_assertions.py`.
Source run: **12 failed, 1 passed** for the intended domain-isolation failures.
Candidate coverage additionally forces simultaneous equal-title slug allocation,
using real concurrent writer transactions and a barrier around the existing
SELECT/INSERT seam. A savepoint retry preserves two originals, previous slug
format and exactly two audited assertion/source effects. No throughput or
private-corpus quality improvement is claimed.

## Existing-installation evidence

`uv run pytest -q tests/test_domain_upgrade.py` covers two populated source
schemas, 018 and 019. The historical gateway fixture is byte-for-byte source code
from `9071693:agentic_rag/validity.py`; it does not depend on Git history being
available at test runtime. It reproduces one historical cross-domain supersedes
edge and read-side suppression in each source before the migration.

Each source contains multiple domains, both reader/writer roles, original
assertions, claim/source evidence, pins, a nonempty checkpoint, queued work and
audits. The strict exported-snapshot backup helper restores into a marker-owned
copy and compares every public source row and the three application roles' table
privileges. Source018 applies019+020; source 019 applies020. Transaction rollback
restores the old function, retry succeeds, a repeated migration is a no-op,
original table row fingerprints and grants match exactly, and function OID,
owner and execute ACL remain unchanged. Original migration ledger rows remain.

After migration, original programming evidence becomes eligible and its general
counterpart stays superseded. The SQL012 `claim_eligible` wrapper remains: proposal and withdrawn-source
claims are excluded from current/as-of reads and retained in explicit history.
Legacy SQL reader and current search contract agree;
`rag_reader` still cannot mutate assertions. An interrupted candidate write rolls
back without changing original rows. The aggregate diagnosis still reports the
same one historical cross-domain edge; the upgrade never rewrites it or claims
that a collapsed duplicate's original domain can be reconstructed.

## Adoption limits

This PR requires migration020 and a separately approved writer cutover. Readers
retain the SQL function signature. Old writers retain wrong domain-free comparison
and lock semantics; they must be quiesced and reconnected before new writes resume.
Code recovery with 020 retained is read-only until a forward fix is ready. Full
upgrade/recovery order and downgrade/data-loss limits are in
[atomic facts](../fact-validity.md#existing-installation-upgrade-and-recovery).

## Verification and review

Baseline affected validity/entity/role suite: **89 passed in 9.17 s**.
After the domain repair, the complete affected domain/scope/role suite passed
**123 tests in 12.51 s**. Initial full integration verification exposed43 failures:
SQL020 had copied the pre-SQL012 temporal body and omitted its claim/source guard,
and the corrections adapter rejected schema020. The independent review identified
the guard as a High bug. SQL020 was corrected to match SQL012 exactly, adding only
`nd.domain=d.domain`; explicit populated-migration tests retain source withdrawal
and proposal exclusion. The correction adapter now supports018/019/020 while
preserving format, source hash/revision and schema validation. These failures
were resolved before PR creation, without changing acceptance criteria.

Final commands:

- `uv run pytest -q`: **1,317 passed in 182.52 s**.
- Affected domain/upgrade, corrections, evidence, adaptive search, vector planner,
  cache, graph and neural ordering suite: **247 passed in 111.68 s**.
- `node --test tests/test_opencode_plugin.mjs`: **7 passed**.
- `uv lock --check`, `git diff --check`, all four0.6.5 metadata references,
  source-fixture byte comparison, minimal SQL delta and **89 local documentation
  links** passed.
- `uv build`: wheel and sdist built; wheel includes SQL020.

Independent complete bounded review and re-review report **Ready**, with no
Critical, High, Medium or Low findings. No source/private content was sent to a
new provider. A read-only aggregate diagnosis on the running source found zero
cross-domain temporal assertion edges; historical collapsed-duplicate attribution
remains unverified and this does not establish absence of all prior domain errors.
