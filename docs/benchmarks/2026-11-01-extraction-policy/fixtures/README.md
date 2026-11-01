# Frozen RAG-067 extraction-policy fixtures

Frozen on 2026-11-01 before any RAG-067 product change (task T067-001).
`cases.json` holds synthetic English and German source events and the
predetermined output of a mock provider; `labels.json` holds the author's
expected deterministic outcome; `policies/` holds the policy files the cases
use. `FROZEN.sha256` lists the SHA-256 of every file; the measurement and the
tests refuse to run when a value differs. Labels are not changed afterwards.

What the fixtures can show: category and limit enforcement on all output
channels, exact source-event grounding, secret stripping, provider-call counts,
policy identity across a provider-failure retry, replay without a second call,
an all-disabled policy without a provider call and visible rejection of a
malformed file.

What they cannot show: real-model extraction quality. The provider output is
written by hand, partly to ignore the advisory guidance on purpose. Case L1
records the known semantic limit: an abandoned experiment that a provider
labels as an allowed category is retained, because guidance is advisory and an
exact quote does not prove that a statement is true or entailed.
