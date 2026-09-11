## Purpose
Adapt canonical RAG context, checkpoint and mining services to OpenCode.

## Requirements
### Requirement: Main-session continuity
The adapter SHALL inject bounded context before main model requests and reconcile compaction by actual request identity.
#### Scenario: Resume after compaction
- WHEN a completed summary exists for an observed compaction request
- THEN its matching checkpoint receives the handoff and subsequent context restores it.

### Requirement: Private bounded projection
The adapter SHALL preserve stable identities and exclude reasoning, tool results, synthetic context and child sessions from mining.
#### Scenario: Repeated idle
- WHEN completed messages are exported repeatedly
- THEN the projection contains one record per identity and the shared debounced queue remains authoritative.

### Requirement: Reversible installation
Installation SHALL own only its loader, preserve settings and refuse modified bytes or symlinks.
#### Scenario: Check or uninstall
- WHEN check runs it writes nothing; WHEN uninstall runs it removes only exact owned bytes.
