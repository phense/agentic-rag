# Changelog

All notable changes to agentic-rag are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). It is **pre-1.0** — the entries below summarize
milestones rather than every commit, and interfaces may still change between `0.x` releases.

## [Unreleased]

## [0.1.0] - 2026-07-09

Initial public release.

### Added
- **Storage layer:** PostgreSQL + pgvector document store with hybrid search (full-text +
  vector similarity) and a curated knowledge graph of typed edges between documents.
- **Claude Code integration:** hooks for session-start context injection and transcript
  mining, plus MCP servers exposing memory search, retrieval, and curation tools to Claude
  Code sessions.
- **Autonomous curation:** `claude -p`-driven background jobs that mine session transcripts
  into candidate documents/edges and curate them (dedup, review, promote/refute) without
  blocking interactive use.
- **Cross-platform install:** a single install command that provisions the right background
  scheduler for the platform — `launchd` on macOS; documented `cron`/`systemd` recipes to set up on Linux.
- **Migration tooling:** a generic `migrate` importer for bringing existing wiki-style
  document collections into the store.
- **CLI (`rag`):** commands for search, review, pin management, domain administration, and
  maintenance (log rotation, status reporting).
