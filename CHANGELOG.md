# Changelog

## [0.2.0](https://github.com/catduckgnaf/hermes-legal/compare/hermes-legal-v0.1.0...hermes-legal-v0.2.0) (2026-11-20)


### Features

* add connector framework with Clio, DocuSign, and RECAP-first PACER (issue [#8](https://github.com/catduckgnaf/hermes-legal/issues/8)) ([48883c2](https://github.com/catduckgnaf/hermes-legal/commit/48883c2bf99dd97ac3700e3b9639693588996766))
* Bates-stamp and truly redact real PDFs; LibreOffice fidelity gate for redlines ([bf83d4d](https://github.com/catduckgnaf/hermes-legal/commit/bf83d4d9f5e047075a4898ade5051f347673fd2c))
* build the local dashboard for legal serve (issue [#21](https://github.com/catduckgnaf/hermes-legal/issues/21), step 5) ([8c64a30](https://github.com/catduckgnaf/hermes-legal/commit/8c64a30e0bbab40f196fd784e9d6f121b907ac2e))
* citation verification, Bluebook formatting, and Verify-All gate ([97b9804](https://github.com/catduckgnaf/hermes-legal/commit/97b9804d4b8deacd6e3df92bb9e3547158281048))
* **citations:** add Caselaw Access Project resolver ([cfd2f54](https://github.com/catduckgnaf/hermes-legal/commit/cfd2f547ee856284f1dac9c497904fb4220c09ba))
* **citations:** add Caselaw Access Project resolver ([406330f](https://github.com/catduckgnaf/hermes-legal/commit/406330fc3cf4787290620280af111fb4e6c8fe09))
* **citations:** govinfo statute resolver, opinion-text quote checks, LOCAL_ONLY lookup guard, and cite-attest (part of [#3](https://github.com/catduckgnaf/hermes-legal/issues/3), part of [#22](https://github.com/catduckgnaf/hermes-legal/issues/22)) ([6c5ff52](https://github.com/catduckgnaf/hermes-legal/commit/6c5ff5236f92cda5ae59660966af3eeaa641c9ef))
* connect the tools to agents through one dispatcher ([cbc555b](https://github.com/catduckgnaf/hermes-legal/commit/cbc555b5ba32098209f14c00a00f47ff26f74630))
* connect the tools to agents through one dispatcher ([86808d5](https://github.com/catduckgnaf/hermes-legal/commit/86808d5447bd646ebf4024842521cfa1223adb11))
* deadline remainders — calendar payload, warning on every surface, dual entry on all paths, holiday data ([5bf681c](https://github.com/catduckgnaf/hermes-legal/commit/5bf681c7d962ce694b58fd7483806293bee0eb9d))
* deadlines — extraction candidates, human confirmation, rule-based calculation, .ics export (Part of [#6](https://github.com/catduckgnaf/hermes-legal/issues/6)) ([81940c6](https://github.com/catduckgnaf/hermes-legal/commit/81940c6c435b04f9be57eab48b64a385552c111f))
* **desktop:** groundwork for the Hermes desktop client ([#34](https://github.com/catduckgnaf/hermes-legal/issues/34)) ([71d003c](https://github.com/catduckgnaf/hermes-legal/commit/71d003c3e2016e7379e8d4eaa5316ed044ab633e))
* **desktop:** lightweight desktop client that connects to Hermes ([018b081](https://github.com/catduckgnaf/hermes-legal/commit/018b081bcdb6aa6f9f88ee3576a3392072d66d29))
* **desktop:** Tauri 2 packaging scaffold for Linux and Windows installers ([b34c72c](https://github.com/catduckgnaf/hermes-legal/commit/b34c72c270226c4ec3bf84fe3379c14912e32292))
* DOCX compare and redline with real track changes, PDF Bates plan and redaction verification ([a0b5409](https://github.com/catduckgnaf/hermes-legal/commit/a0b54096cc842ff95f9211c1791b5556b933fc17))
* enforce privacy tiers with a raising provider router, AI log, preview, and doctor warnings ([6f8cf01](https://github.com/catduckgnaf/hermes-legal/commit/6f8cf01d42b072544244e1f41b57feed4a437a41))
* found hermes-legal — local-first legal desktop scaffold ([3fd7500](https://github.com/catduckgnaf/hermes-legal/commit/3fd750041f88a5dd03615683412f62299537db53))
* implement legal_chronology and legal_intake_summary ([a08e113](https://github.com/catduckgnaf/hermes-legal/commit/a08e1131e8ff9b0f6e70ee1b0da51cdcf335aa7c))
* implement legal_chronology and legal_intake_summary ([f264650](https://github.com/catduckgnaf/hermes-legal/commit/f26465024187917415ed8ff47b235cd363011355))
* implement legal_efile_bundle with Verify-All gate ([29263a2](https://github.com/catduckgnaf/hermes-legal/commit/29263a2bc85c75d75e7103362231d923ec07ae08))
* implement legal_efile_bundle with Verify-All gate ([c63b10b](https://github.com/catduckgnaf/hermes-legal/commit/c63b10b8d01560e4c974b823e0154c6bdb4f52b4))
* land the reviewed v1 stack (PRs [#10](https://github.com/catduckgnaf/hermes-legal/issues/10)-[#20](https://github.com/catduckgnaf/hermes-legal/issues/20), [#27](https://github.com/catduckgnaf/hermes-legal/issues/27)-[#32](https://github.com/catduckgnaf/hermes-legal/issues/32)) on main ([f1f721e](https://github.com/catduckgnaf/hermes-legal/commit/f1f721e1115a899112258a1f4283d5fb47e47c5a))
* log the exact sent payload tied to the approved preview ([99bde53](https://github.com/catduckgnaf/hermes-legal/commit/99bde5395dc1ca6b876d4dafd4e6ec75a15424d3))
* matter workspaces with recents and conflict-safe watcher ([3b42896](https://github.com/catduckgnaf/hermes-legal/commit/3b42896283c7efecf8a472958aaf92c43aeaa689))
* **pdf:** fail-closed whole-file audit for redact-verify and the redaction rebuild ([3118372](https://github.com/catduckgnaf/hermes-legal/commit/31183720b211e9936cd06668707181f64ad3c8c5)), closes [#23](https://github.com/catduckgnaf/hermes-legal/issues/23)
* **pdf:** fail-closed whole-file audit for redact-verify; manual Word and LibreOffice redline gate ([d9c693a](https://github.com/catduckgnaf/hermes-legal/commit/d9c693ab6f00f02ae65d719860e1e7e0a585bdc5))
* playbook review and clause library (Part of [#5](https://github.com/catduckgnaf/hermes-legal/issues/5)) ([d83a145](https://github.com/catduckgnaf/hermes-legal/commit/d83a145a3d33cf86a6e71e0d8f70a734671db93a))
* **playbooks:** negation-aware matching and fallback surfacing ([91acfdf](https://github.com/catduckgnaf/hermes-legal/commit/91acfdf11abe0d69ff6f88d30a275566e24c185a))
* ship a usable Windows and Linux thin client ([0433dd4](https://github.com/catduckgnaf/hermes-legal/commit/0433dd42d5e086ed7a6f7ad1317b2582b2abac5f))
* usable Windows and Linux thin client ([ed3014e](https://github.com/catduckgnaf/hermes-legal/commit/ed3014eea4d5aeeddb54cc80b5ca73edcbdea659))
* use PdfCraft as the engine for PDF redaction and Bates stamping ([4150116](https://github.com/catduckgnaf/hermes-legal/commit/4150116c3b9a784ee5350f1d612505012dd5767e))


### Bug Fixes

* **citations:** agent cite-check uses the statute router, attestations and a pre-send lookup preview ([8072960](https://github.com/catduckgnaf/hermes-legal/commit/8072960ae5db745f5afd212e8a29a7749390a76a))
* **citations:** ambiguous clusters, cite-check resolver, and human attestation (part of [#22](https://github.com/catduckgnaf/hermes-legal/issues/22)) ([af9f23c](https://github.com/catduckgnaf/hermes-legal/commit/af9f23c10187590f9d0684a89a61bc7e5d095d0a))
* **citations:** ambiguous clusters, cite-check resolver, and human attestation (part of [#22](https://github.com/catduckgnaf/hermes-legal/issues/22)) ([638fd7e](https://github.com/catduckgnaf/hermes-legal/commit/638fd7e4fe5247395b63326f45e41bf39c735141))
* **citations:** route agent cite-check through the router, attestations and a pre-send preview ([c24bc25](https://github.com/catduckgnaf/hermes-legal/commit/c24bc258c75941cb4a79a7a3f415894ac0079516)), closes [#22](https://github.com/catduckgnaf/hermes-legal/issues/22)
* **connectors:** close remaining issue 25 gaps on privacy reads, RECAP exact match and PACER fetch auth ([b8bc302](https://github.com/catduckgnaf/hermes-legal/commit/b8bc302fefe9683f0c74d5120c681bcc09f4616e))
* **connectors:** enforce RECAP-first, page Clio lists, fail closed on missing matter ([77e9e39](https://github.com/catduckgnaf/hermes-legal/commit/77e9e391e2e45414c243da2ca668c6c16001cef8))
* **connectors:** enforce RECAP-first, page Clio lists, fail closed on missing matter ([bae6fd4](https://github.com/catduckgnaf/hermes-legal/commit/bae6fd44471d96ca9a42f900ca404b1d79da83a8))
* **connectors:** fail closed on reads with no matter, exact-match RECAP check, authenticated PACER fetch ([398caf2](https://github.com/catduckgnaf/hermes-legal/commit/398caf2d6241b4e1dc63a6c49c5e3250c1c1d5d5)), closes [#25](https://github.com/catduckgnaf/hermes-legal/issues/25)
* correct public tool claims and finish the hygiene items in [#26](https://github.com/catduckgnaf/hermes-legal/issues/26) ([e1c0702](https://github.com/catduckgnaf/hermes-legal/commit/e1c07028def81b055c7ad03780d481a52470f7a3))
* correct public tool claims and route deadline columns through the migration list ([94353c3](https://github.com/catduckgnaf/hermes-legal/commit/94353c34ebdc4912e590188e24d918e150489429)), closes [#26](https://github.com/catduckgnaf/hermes-legal/issues/26)
* **desktop:** install the Windows shell as hermes-legal.exe ([c4f505c](https://github.com/catduckgnaf/hermes-legal/commit/c4f505c4fd4848ff749ecd9383b39ea984403d9c))
* **desktop:** make the Tauri app a thin client with no sidecar or shell permission ([3715496](https://github.com/catduckgnaf/hermes-legal/commit/3715496aa4861917cba387a22462482312a6cce5))
* **desktop:** make the token store object-safe and ship RGBA icons ([1ac9994](https://github.com/catduckgnaf/hermes-legal/commit/1ac99942078acf0e5fac39bda54db428fe2633ad))
* **desktop:** register the token commands so the capability resolves ([d1a1d35](https://github.com/catduckgnaf/hermes-legal/commit/d1a1d358428d34e4a763e9e092d687d862e81a3c))
* **desktop:** upload bundles from the real target directory ([91c3fac](https://github.com/catduckgnaf/hermes-legal/commit/91c3faccc0a0b267b946005203d1dc66d0920713))
* **desktop:** use a valid Tauri bundle category so Windows bundling runs ([246d6f9](https://github.com/catduckgnaf/hermes-legal/commit/246d6f98c96b595e158d2d8e3295b32176d3c133))
* keep redlines of Word-authored documents valid and lossless ([60377ac](https://github.com/catduckgnaf/hermes-legal/commit/60377ac4015978a52fb9881d211d32ee5a1fa814))
* legal doctor exit code, repo hygiene docs, and uv.lock ([3e57165](https://github.com/catduckgnaf/hermes-legal/commit/3e57165c970b5134657572d52ed3d0533bbdff07))
* legal doctor exit code, repo hygiene docs, and uv.lock ([6d5e880](https://github.com/catduckgnaf/hermes-legal/commit/6d5e880ae4cc567643dd8c3366ab52c557d2543e))
* make CI gates real and redact credentials on agent connections ([306fd86](https://github.com/catduckgnaf/hermes-legal/commit/306fd86a3a3ca3cf9c1ca3c94de79a01b5414612))
* make the Verify-All gate fail closed on what it cannot confirm ([21648a6](https://github.com/catduckgnaf/hermes-legal/commit/21648a64e27b32c619cd2478b116b895cde765b4))
* never overwrite externally created files and write atomically ([8035a18](https://github.com/catduckgnaf/hermes-legal/commit/8035a18e39e5f46c2b380d009fa33e6bcc46d673))
* place the credential column list away from the schema version ([44a3cfe](https://github.com/catduckgnaf/hermes-legal/commit/44a3cfe869b382962fe1fcba85387b18d185eaac))
* **privacy:** verify LOCAL_ONLY loopback at connect time and log the send endpoint ([61297c5](https://github.com/catduckgnaf/hermes-legal/commit/61297c50267884bb67279692672e7cb2b5958e30))
* **privacy:** verify loopback at connect time and log the send endpoint ([347c678](https://github.com/catduckgnaf/hermes-legal/commit/347c67856f04bf1c1889697d7957ad59c470af5f)), closes [#24](https://github.com/catduckgnaf/hermes-legal/issues/24)
* redact-verify says plainly when no PDF was checked ([a78d5ec](https://github.com/catduckgnaf/hermes-legal/commit/a78d5ec0a23695f2f2900115df5cc9bce2c7c22a))
* redact-verify says plainly when no PDF was checked (Part of [#23](https://github.com/catduckgnaf/hermes-legal/issues/23)) ([7173620](https://github.com/catduckgnaf/hermes-legal/commit/717362051832871022652b2e292d148db334dd5f))
* refuse providers that are not in the catalog ([02c7d66](https://github.com/catduckgnaf/hermes-legal/commit/02c7d664907c496fcd8b05ad116586d8846eb0d4))
* reject invalid playbook patterns at parse time ([c7c762a](https://github.com/catduckgnaf/hermes-legal/commit/c7c762a0d7f274ad21fb1c2b1ce449dfb90f4c8e))
* review fixes found landing PRs [#36](https://github.com/catduckgnaf/hermes-legal/issues/36)-[#46](https://github.com/catduckgnaf/hermes-legal/issues/46) together ([e74c3fd](https://github.com/catduckgnaf/hermes-legal/commit/e74c3fd731d9eee6e056ef3b086ed01e9100d29c))
* stop adding Rule 6(d) days to answers and enforce filing dual entry ([b40f93a](https://github.com/catduckgnaf/hermes-legal/commit/b40f93a596c17aaa57ab4fa76234bce48104b85b))


### Documentation

* clean up README to match the landed v1 stack ([e3e2a00](https://github.com/catduckgnaf/hermes-legal/commit/e3e2a0000dfc9f1c7f671163e4a71354cd8fb06b))
* **desktop:** add groundwork plan for the Hermes desktop client ([7d8a5b8](https://github.com/catduckgnaf/hermes-legal/commit/7d8a5b8e1862a788c8e5fe731915ba7f3631b79e))
* link the unsigned desktop 0.1.0 installers ([bbe4f14](https://github.com/catduckgnaf/hermes-legal/commit/bbe4f144099f49e31099692a454bfcbcbea0c426))
* map issue 5 and 6 acceptance criteria to tests and state unwired surfaces ([36f0bdb](https://github.com/catduckgnaf/hermes-legal/commit/36f0bdbd75f3e7650363f122a142baaa72e332d9))
* **pdf:** name the doc-redline command in the release gate and describe the whole-file check in help ([e8e32ba](https://github.com/catduckgnaf/hermes-legal/commit/e8e32bac295a209d096930122dceb22ea70d445f)), closes [#23](https://github.com/catduckgnaf/hermes-legal/issues/23)
* point at the unsigned desktop-v0.1.0 installers ([b1e8e45](https://github.com/catduckgnaf/hermes-legal/commit/b1e8e45220343ac93e9847d3e8b8514d20bdfb36))
* **privacy:** describe connect-time loopback check and logged endpoint ([83f4bbf](https://github.com/catduckgnaf/hermes-legal/commit/83f4bbfc524711ee5d2c0b80aaabba9fcedd4cc0)), closes [#24](https://github.com/catduckgnaf/hermes-legal/issues/24)
* use American spelling in CONTRIBUTING filing guidance ([97646b5](https://github.com/catduckgnaf/hermes-legal/commit/97646b58ed3c9ed103d5845c00755843f331c5b2))

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
