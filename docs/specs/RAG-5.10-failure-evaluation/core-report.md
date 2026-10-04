# S01: Private confirmed correction export and evaluation

Owned files: `agentic_rag/benchmark/corrections.py` and
`tests/benchmark/test_corrections.py`. Source baseline00e1fa9, schema018/019;
no migration, client contract or application gateway change. Root integrates
and runs database checks sequentially. This worker makes no commit.

## Implemented boundary

`export_confirmed_corrections(cfg, *, domain, project=None, scope=None,
limit=32, output_path)` opens a fresh reader REPEATABLE READ/READ ONLY snapshot.
It selects one exact domain/project or explicit global scope, examines complete
accepted histories before applying validity/trust gates, and exports only current
accepted replacements with stated/confirmed claims and the exact original retained
complete reviewed active user span. A newer unsupported or expired replacement
cannot revive an old label. Original document/assertion/source/span hashes and row
revisions remain attached; earlier history is reference, not current truth.

Confirmed current alias roots, original source IDs, copied quote hashes and entire
correction histories form connected split families. Their deterministic assignment
cannot put a shared alias/source/history in both development and held-out splits.
Ambiguous, unavailable or over-bound entity selections withhold labels. The format
is `private-confirmed-corrections`, version1, `synthetic=False`; zero cases is valid.

`evaluate_export(cfg, *, export_path, output_path)` validates format, hashes,
selectors, original references and family splits before database access. It checks
frozen labels against current original support and exact original chunk citations.
Every miss/error remains in the denominator. Existing top-level cases/supported/
misses refer to the current entity route, preserving the initial API contract.

Private optimization separately compares two local routes on development cases:
raw FTS with a NULL vector and one literal scope, and exact entity routing. Both
use a12000-character budget. Neither can invoke embeddings, rerankers, contextual
vectors, graph expansion or providers. A new private candidate file is sealed at
`OUTPUT.candidate.json` before selected held-out evaluation. Selection depends only
on development scores; fixed tie order chooses FTS. If independent dev/test source
families are absent, selection is explicitly unavailable. No live profile loader or
configuration mutation exists. The synthetic/public optimizer remains separate.

Files are new0600 artifacts in a0700 parent outside all Git/worktree roots.
Symlinks, overwrite, secret-shaped/redacted strings and credential-shaped assertion
attributes are rejected. Returned dictionaries contain aggregate counts/profile
metadata; source content, per-case IDs and private references stay in private files.
Exceptions in evaluation expose their type only.

## Verification performed by this worker

- Initial five pure tests failed on the absent module, then passed after implementation.
- Four resealed malformed-format tests failed because they reached the database seam;
  strict metadata validation then made them pass before that seam.
- A credential-attribute regression failed because an unrecognizable password value
  could be serialized; attribute-aware withholding made it pass.
- An existing candidate-path regression failed because evaluation entered the database
  seam before refusing overwrite; candidate preflight now rejects before that seam.
- Final bounded pure selection:22 passed in0.78s. It includes dev-only selection,
  candidate sealing before opposed held-out outcomes, literal-scope FTS and forbidden
  inference seams. No selected test requested `conn`, `cfg`, `dbinit` or database reset.

Database regressions are authored for original support, local citation support,
withdrawal/incomplete/unreviewed/expired/later-withdrawn support, independent later
attachments, complete-family bounds, domain/project/global isolation, frozen-label
misses and confirmed alias stars with independent source spans. **Not executed by
this worker**: database tests, production/private reads, provider calls or migrations.
Root must run those tests and the affected complete suites before acceptance; complete
bounded independent code review remains required.

## Limits and open gates

At most32 candidate exact families and64 accepted historical rows per family are
examined. Additional families set `limited=True`; an over-bound family is withheld.
Artifacts are capped at8MiB and SQL statements at5 seconds. Conservative filtering,
source/review/row-version changes and unresolved aliases can reduce recall. Family
uncertainty remains null; a small private export does not establish general accuracy.
Deterministic secret detection cannot recognize every arbitrary secret, so explicitly
credential-shaped attributes are also withheld. Private measurements cannot enter
the public corpus or any native-provider stage. No production quality gain is claimed.
