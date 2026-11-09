# Changelog

## [0.2.0](https://github.com/catduckgnaf/hermes-legal/compare/hermes-legal-v0.1.0...hermes-legal-v0.2.0) (2026-11-09)


### Features

* add connector framework with Clio, DocuSign, and RECAP-first PACER (issue [#8](https://github.com/catduckgnaf/hermes-legal/issues/8)) ([48883c2](https://github.com/catduckgnaf/hermes-legal/commit/48883c2bf99dd97ac3700e3b9639693588996766))
* citation verification, Bluebook formatting, and Verify-All gate ([97b9804](https://github.com/catduckgnaf/hermes-legal/commit/97b9804d4b8deacd6e3df92bb9e3547158281048))
* connect the tools to agents through one dispatcher ([73130bd](https://github.com/catduckgnaf/hermes-legal/commit/73130bd9db6a7bc0822cce25d8d487a46797a170))
* connect the tools to agents through one dispatcher ([414d384](https://github.com/catduckgnaf/hermes-legal/commit/414d384193929fd09cdf366ecbb7d371a1529c02))
* deadlines — extraction candidates, human confirmation, rule-based calculation, .ics export (Part of [#6](https://github.com/catduckgnaf/hermes-legal/issues/6)) ([81940c6](https://github.com/catduckgnaf/hermes-legal/commit/81940c6c435b04f9be57eab48b64a385552c111f))
* **desktop:** Tauri 2 packaging scaffold for Linux and Windows installers ([b34c72c](https://github.com/catduckgnaf/hermes-legal/commit/b34c72c270226c4ec3bf84fe3379c14912e32292))
* DOCX compare and redline with real track changes, PDF Bates plan and redaction verification ([a0b5409](https://github.com/catduckgnaf/hermes-legal/commit/a0b54096cc842ff95f9211c1791b5556b933fc17))
* enforce privacy tiers with a raising provider router, AI log, preview, and doctor warnings ([6f8cf01](https://github.com/catduckgnaf/hermes-legal/commit/6f8cf01d42b072544244e1f41b57feed4a437a41))
* found hermes-legal — local-first legal desktop scaffold ([3fd7500](https://github.com/catduckgnaf/hermes-legal/commit/3fd750041f88a5dd03615683412f62299537db53))
* land the reviewed v1 stack (PRs [#10](https://github.com/catduckgnaf/hermes-legal/issues/10)-[#20](https://github.com/catduckgnaf/hermes-legal/issues/20), [#27](https://github.com/catduckgnaf/hermes-legal/issues/27)-[#32](https://github.com/catduckgnaf/hermes-legal/issues/32)) on main ([2657f8a](https://github.com/catduckgnaf/hermes-legal/commit/2657f8aadbb8c4712c480681cb05e27840ebdca8))
* matter workspaces with recents and conflict-safe watcher ([3b42896](https://github.com/catduckgnaf/hermes-legal/commit/3b42896283c7efecf8a472958aaf92c43aeaa689))
* playbook review and clause library (Part of [#5](https://github.com/catduckgnaf/hermes-legal/issues/5)) ([d83a145](https://github.com/catduckgnaf/hermes-legal/commit/d83a145a3d33cf86a6e71e0d8f70a734671db93a))


### Bug Fixes

* **citations:** ambiguous clusters, cite-check resolver, and human attestation (part of [#22](https://github.com/catduckgnaf/hermes-legal/issues/22)) ([3e1b114](https://github.com/catduckgnaf/hermes-legal/commit/3e1b1145a5a250aa620403c0eb483b61a2420a63))
* **citations:** ambiguous clusters, cite-check resolver, and human attestation (part of [#22](https://github.com/catduckgnaf/hermes-legal/issues/22)) ([99a87eb](https://github.com/catduckgnaf/hermes-legal/commit/99a87eb8346521eb72caa1cea55e0776e2c43639))
* **connectors:** enforce RECAP-first, page Clio lists, fail closed on missing matter ([d27b850](https://github.com/catduckgnaf/hermes-legal/commit/d27b850c79a53694a5f553943977a1843b78955d))
* **connectors:** enforce RECAP-first, page Clio lists, fail closed on missing matter ([bb8a23e](https://github.com/catduckgnaf/hermes-legal/commit/bb8a23e385e3b649a67c556b9bd6287b8b539a81))
* **desktop:** upload bundles from the real target directory ([91c3fac](https://github.com/catduckgnaf/hermes-legal/commit/91c3faccc0a0b267b946005203d1dc66d0920713))
* keep redlines of Word-authored documents valid and lossless ([60377ac](https://github.com/catduckgnaf/hermes-legal/commit/60377ac4015978a52fb9881d211d32ee5a1fa814))
* legal doctor exit code, repo hygiene docs, and uv.lock ([eefc866](https://github.com/catduckgnaf/hermes-legal/commit/eefc866ab0df7b06924c77d0e471bba1bb5ab27e))
* legal doctor exit code, repo hygiene docs, and uv.lock ([c63d448](https://github.com/catduckgnaf/hermes-legal/commit/c63d448b0cae8cdc3a7c35ca482370399c4ab426))
* make CI gates real and redact credentials on agent connections ([7792a98](https://github.com/catduckgnaf/hermes-legal/commit/7792a988239035608f88ac62ef34d68646375b79))
* make the Verify-All gate fail closed on what it cannot confirm ([21648a6](https://github.com/catduckgnaf/hermes-legal/commit/21648a64e27b32c619cd2478b116b895cde765b4))
* never overwrite externally created files and write atomically ([8035a18](https://github.com/catduckgnaf/hermes-legal/commit/8035a18e39e5f46c2b380d009fa33e6bcc46d673))
* place the credential column list away from the schema version ([698bd01](https://github.com/catduckgnaf/hermes-legal/commit/698bd01e4ed8e84e347c8bde36d4ab5af15d0996))
* redact-verify says plainly when no PDF was checked ([415c27f](https://github.com/catduckgnaf/hermes-legal/commit/415c27fe4f44706c6f076d3b486ebbc78c394086))
* redact-verify says plainly when no PDF was checked (Part of [#23](https://github.com/catduckgnaf/hermes-legal/issues/23)) ([791f739](https://github.com/catduckgnaf/hermes-legal/commit/791f739209af0f14c7e613de30598811e73ed268))
* refuse providers that are not in the catalog ([02c7d66](https://github.com/catduckgnaf/hermes-legal/commit/02c7d664907c496fcd8b05ad116586d8846eb0d4))
* reject invalid playbook patterns at parse time ([c7c762a](https://github.com/catduckgnaf/hermes-legal/commit/c7c762a0d7f274ad21fb1c2b1ce449dfb90f4c8e))
* stop adding Rule 6(d) days to answers and enforce filing dual entry ([87dd411](https://github.com/catduckgnaf/hermes-legal/commit/87dd411767b7e629ed35ddd815754561f3cbd4a0))


### Documentation

* use American spelling in CONTRIBUTING filing guidance ([15936e9](https://github.com/catduckgnaf/hermes-legal/commit/15936e98f2aacda3ea92c36565022cf41a55adf2))

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
