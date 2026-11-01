# Issue92 A2: optional background embedding isolation

Purpose: identify the admission and identity boundaries changed by A2 before
implementation. Source: runtime5667ee7, independent design review6ffeb3d,
`docs/specs/6-10-agent-plugins/plan.md` A2. Requirements FR04..08, AC02/04/05.
Date2026-11-01. Mode: design; conditional on E-LANE-1. Mermaid source inspected
semantically; not rendered. The absence of a renderer is not a runtime result.

```mermaid
flowchart LR
    Client[Actual client and durable outbox] -->|existing retry_after hint| API[API and bounded consumers]
    API -->|existing foreground SQL lock| Primary[Existing primary embedding endpoint]
    Worker[Singleton fenced extraction worker] --> Gate{New background work admitted?}
    Gate -->|lane unset or managed profile| Primary
    Gate -->|optional legacy lane and separate SQL lock| Background[One background runner with finite resources]
    Primary --> Identity[Primary model identity and dimension]
    Background --> Verify[Verify both endpoints before and after inference]
    Identity --> Verify
    Verify -->|same digest and proven vector parity| Cache[Canonical reuse identity]
    Verify -->|unknown identity or pressure| Pending[Retain accepted output and pending work]
    Cache --> Gateway[Existing audited gateway and authority recheck]
```

No step truncates or replaces an original, weakens a truth/access gate or
publishes a result before its existing authorization check. Existing shared
model admission remains the default; the optional background runner is not a
new knowledge store. Physical resource feasibility, lane failure recovery and
actual-client observation are unexecuted gates, not claims of this diagram.
