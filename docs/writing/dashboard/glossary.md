# Dashboard glossary

| Preferred term | Definition | Avoid |
|---|---|---|
| Dashboard | Browser interface at /dashboard/ | control center |
| Principal | Configured person or VM identity | tenant user as a permission shortcut |
| Policy | Sole authoritative file defining identities and scopes | database policy override |
| Revision | SHA-256 digest of the exact policy file | version as a file concurrency token |
| Bootstrap token | Operator-armed one-time first-admin authorization | default credential |
| Freshness | Time since authenticated activity; online/stale/never-seen | connected socket count |
| Revoked | Credential no longer authorizes requests | offline |
| Setup check | Saved safe result of an explicit validation | automatic migration |
| Prepared change | Durable administrative audit written before atomic file apply | completed change |
| Foreground request | Current interactive tool work in the existing bounded queue | session-log batch |

```json
[
  {
    "preferred": "Dashboard",
    "definition": "Browser interface at /dashboard/",
    "avoid": [
      "control center"
    ]
  },
  {
    "preferred": "Principal",
    "definition": "Configured person or VM identity",
    "avoid": [
      "tenant user as a permission shortcut"
    ]
  },
  {
    "preferred": "Policy",
    "definition": "Sole authoritative file defining identities and scopes",
    "avoid": [
      "database policy override"
    ]
  },
  {
    "preferred": "Revision",
    "definition": "SHA-256 digest of the exact policy file",
    "avoid": [
      "version as a file concurrency token"
    ]
  },
  {
    "preferred": "Bootstrap token",
    "definition": "Operator-armed one-time first-admin authorization",
    "avoid": [
      "default credential"
    ]
  },
  {
    "preferred": "Freshness",
    "definition": "Time since authenticated activity; online/stale/never-seen",
    "avoid": [
      "connected socket count"
    ]
  },
  {
    "preferred": "Revoked",
    "definition": "Credential no longer authorizes requests",
    "avoid": [
      "offline"
    ]
  },
  {
    "preferred": "Setup check",
    "definition": "Saved safe result of an explicit validation",
    "avoid": [
      "automatic migration"
    ]
  },
  {
    "preferred": "Prepared change",
    "definition": "Durable administrative audit written before atomic file apply",
    "avoid": [
      "completed change"
    ]
  },
  {
    "preferred": "Foreground request",
    "definition": "Current interactive tool work in the existing bounded queue",
    "avoid": [
      "session-log batch"
    ]
  }
]
```
