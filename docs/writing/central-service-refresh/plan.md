# Central-service handbook refresh

Scale: large, because one change must agree across the existing handbook's
reader paths. Version0.6.10; canonical work6.0 / Issue58 / PR76. This is a
scoped update of existing chapters, not a replacement manual. Preserve historic
release notes, verified commands and chapter anchors.

Readers: agent users choosing local or service access, and Linux operators
upgrading a populated installation. Start with the least experienced user who
can install Python but has no PostgreSQL account on the service host.

| Chunk | Type | Path | Reader goal | State |
|---|---|---|---|---|
| NAV | reference | docs/README.md | Choose local setup or a remote client | reviewed |
| QS | task | docs/03-quick-start.md | Install the right prerequisites | reviewed |
| MIN | concept | docs/05-session-mining-and-curation.md | Understand source capture, ACK and extraction | reviewed |
| CFG | reference | docs/06-configuration-reference.md | Configure each service mode and its limits | reviewed |
| SEC | concept | docs/07-privacy-and-cost.md | Understand department and secret boundaries | reviewed |
| OPS | task | docs/09-maintenance-and-backups.md | Back up the canonical server and client pending input | reviewed |
| ARCH | concept | docs/10-architecture.md | Distinguish local flock from database fencing | reviewed |
| CLI | reference | docs/11-reference-cli-and-mcp.md | Find actual service commands and HTTP statuses | reviewed |
| SERVER | task | docs/13-central-service.md | Follow the reviewed operator procedures | reviewed |

Content root: existing docs/. Dependency order NAV→QS→CFG→MIN/SEC→OPS→ARCH/CLI;
SERVER remains the canonical detailed procedure rather than duplicating it.
Existing chapters retain their established mixed legacy structure/frontmatter;
review changes plus affected statements, not untouched historical material.
New chunks use the repository's frontmatter convention. No new screenshots.

Acceptance: working local and remote reading paths; exact parser/config keys;
no unconditional client-local DB/model/worker statements; ACK distinguished from
application; explicit IT sharing/accounting denial and OS/tool boundary; no
claim of generalized queued requests before68. Relative links and command help
must pass. An independent reviewer checks the whole documentation delta.
