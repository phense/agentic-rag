# Shared terms

```json
[
 {"term":"standalone","definition":"Local engine and PostgreSQL without an HTTP account","avoid":[]},
 {"term":"server","definition":"API and fenced worker on the canonical store","avoid":[]},
 {"term":"client","definition":"Agent adapter and protected durable upload spool","avoid":[]},
 {"term":"spool","definition":"Unacknowledged client input retained privately","avoid":[]},
 {"term":"receipt","definition":"Opaque proof of durable server input acceptance","avoid":[]},
 {"term":"applied","definition":"Canonical knowledge application completed","avoid":[]},
 {"term":"session team","definition":"Explicit shared-read group for retained session logs","avoid":["Herdr authorization"]},
 {"term":"uploader profile","definition":"Stable cursor namespace, without additional permission","avoid":[]}
]
```

Use server/client for location, session team for log visibility, and uploader
profile for cursor separation. A session label is never authentication.
