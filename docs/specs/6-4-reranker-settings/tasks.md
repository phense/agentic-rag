# Tasks: RAG-062 settings extension

All work sequential; basea8441eb. Shared interfaces preclude parallel writes.

### Slice C062-S1: Preset identity and offline runtime

- [x] T001 (AC001/005/006, AF062-S2): Add failing default/profile/identity tests;
  catalogue in agentic_rag/reranker_profiles.json and reranker_profiles.py;
  update config.py/neural_rerank.py with explicit-config compatibility.
- [x] T002 (depends T001, AC006): Add optional reranker dependencies and
  agentic_rag/reranker_runtime.py prepare/serve; test bounded HTTP and hash rejection.

### Slice C062-S2: Audited Settings workflow

- [x] T003 (depends T001/T002, AC001–005, AF062-S1): Add failing real API tests;
  protected [reranker] field, settings state/preview/apply, atomic journal reuse,
  live-session/concurrent-revision rejection; implement settings UI in app.js.

### Slice C062-S3: Upgrade, browser and delivery

- [x] T004 (depends T003, AC007/008, AF062-S3): Native3-model smoke; real old/new
  populated local/REST/MCP upgrade and rollback; unchanged canonical hashes;
  desktop/mobile Settings flows; full suite, Node, wheel checks.
- [ ] T005 (depends T004): PB062-SETTINGS authoring/rehearsal/content review;
  reconcile architecture, derive and pass independent success/recovery tests;
  independent complete extension diff review, fix C/H/M, Low->Issue75;
  update PR82/Issue62 with scope/default change and await NEW merge approval.

### Slice C062-S4: Reject unsupported native bind before startup

- [x] T006 (AC006/008): Reproduce offered IPv6 bind returning400 in the framework
  Host guard; constrain the new daemon to its documented/tested127.0.0.1 binding
  and reject IPv6 at argument parsing before artifact load. Preserve the legacy
  adapter capability to use separately supplied IPv6 loopback runtimes. Run the
  RED/GREEN regression, independent recheck and a fresh full suite. Final full
  and recheck evidence are part of the existing T004/T005 acceptance gates.
