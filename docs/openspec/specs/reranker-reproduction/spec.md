# Reranker reproduction

## Purpose

Keep a maintained offline reproduction path while preserving immutable
historical reranker evidence and explicit failed experiments.

## Requirements

### Requirement: Immutable historical benchmark identity

The maintained path SHALL preserve every archived benchmark file byte-for-byte
and SHALL label new results with their own source, environment, corpus and
model hashes.

#### Scenario: Reproduce after a dependency security update

- **WHEN** a maintainer rebuilds the maintained environment
- **THEN** old measurements retain their original dependency identity and failed
  protocol status, and new results carry separate identities.

### Requirement: Offline pinned ONNX reproduction

The maintained runner SHALL accept only the pinned MiniLM L6, mMARCO and Jina
v2 ONNX profiles, use verified staged model/tokenizer files, refuse installed
Transformers/setuptools, and perform no model download or custom Python load.

#### Scenario: Unsupported custom-code candidate

- **WHEN** v3.5 is requested
- **THEN** the runner refuses before loading or downloading a model.

### Requirement: Bounded failures remain evidence

The runner SHALL bound inference in an owned child process, retain each failed
attempt and partial output, and report actual successes, failures and
unattempted cases without substituting missing observations with zero.

#### Scenario: Child exceeds its deadline

- **WHEN** a native inference exceeds the declared deadline
- **THEN** the owned child is terminated, the run exits nonzero and its retained
  result marks all missing cases unattempted.
