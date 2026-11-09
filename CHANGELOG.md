# Changelog

## [Unreleased]

### Changed
- The product name is confirmed as **Hermes Legal**. Display text everywhere
  (README, docs, plugin descriptions, site name, CLI description) now uses
  Hermes Legal; technical identifiers (`hermes-legal` repository and package,
  `hermes_legal`, `HERMES_LEGAL_*`, `hermes-legal://`) are the same name in
  kebab, snake and upper-snake case and do not change.

## [0.1.0] - 2026-11-09

### Added
- Project founded: local-first legal desktop scaffold inspired by hermes-finance,
  set up with Print Handy's repository governance, AGPL-3.0-or-later.
- `legal_*` agent tools defined once in `src/hermes_legal/tooldefs.py` and shared
  by the CLI, the Hermes plugin, MCP and the dashboard Ask panel.
- Matter workspaces over ordinary folders, a local SQLite database, a synthetic
  demo matter, `legal doctor`, and the LOCAL-ONLY / ZERO-RETENTION / STANDARD
  privacy tier model with consumer chat accounts blocked.
- Foundation research report in `docs/research/foundation-report.md`.
