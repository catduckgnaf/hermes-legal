# Contributing to Hermes Legal

Thanks for helping improve Hermes Legal. This guide describes the repository workflow and project specific checks. The [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) provides the expected pull request description structure.

## Before starting

- Search open issues and pull requests for related work. For larger changes, discuss the approach in an issue first so scope and safety expectations are clear.
- Read the relevant project documentation and code. The README describes supported matters and workflows; configuration details are in `docs/architecture.md`.
- Keep changes focused. Separate unrelated fixes and avoid including machine specific settings, credentials, private matter data, or personal model files.
- Matter control is safety sensitive. Keep offline analysis and tests separate from live matter operations. A code change or successful test does not authorize contacting or operating a matter.

## Filing an issue

- Use the [issue forms](.github/ISSUE_TEMPLATE). Bug reports require the observed behaviour, the steps that reproduce it, the Hermes Legal version and install method, and evidence. Feature requests require the problem, the proposed behaviour, scope, and acceptance criteria. Research issues require the question and the decision the answer informs. The forms mark which fields are required.
- State measured facts, and label estimates and suspicions as such. Do not present a cause as verified when it is a hypothesis; say what evidence would settle it.
- Never include credentials, tokens, private model files, or personal runtime records in an issue. Redact logs before posting.
- Everything you write here is public, and the edit history keeps old versions. Do not include local file paths, machine or host names, private IP addresses, MAC addresses, email addresses, SSH targets, chat or account IDs, or anything else that says where you keep things. Say "the host", "the container" or "the matter" instead. There is no automated public-text checker in this repository yet, so check your own text before posting; the pull request template carries the same rule as a checkbox.
- There is no diagnostics bundle command in this repository yet: Hermes Legal has no bundle command and no `hermes_legal.diagnostics_bundle` module. For a bug report, run `uv run legal doctor` and `uv run legal --version`, review the output, redact anything private, and paste it into the report's Evidence field instead.
- An issue never authorizes operating a live matter. If a report involves client material reaching a model or connector it should not have reached, or a write that happened without approval, say so in the first line so it can be prioritized.
- Labels describe the kind of issue (`bug`, `enhancement`, `documentation`, `question`). Priority (`P0`–`P2`) and planning labels (`backlog`, `MVP`) are applied by maintainers during triage, not by the reporter.
- Duplicates are closed with a link to the canonical issue. Issues closed as not planned get a short reason and, where one exists, a link to the issue that supersedes them. A closed issue can be reopened when new evidence or a changed scope justifies it.

## Prepare a change

- Use a branch for your change and keep commits focused and clearly named.
- Add or update tests for changed behavior. For a bug fix, include a regression test where practical. Every pull request answers for this in its `Tests added and regression scoping` section: which tests were added, why none were added when that is the case, and how the change was scoped against the full suite and the existing regression tests.
- Follow the existing Python and configuration patterns. Do not weaken matter readiness, privacy ceilings, citation verification, document validation, or approval gates to make a test pass.
- For public document fixtures, use only synthetic or redistributable documents and record exact provenance and license alongside the fixture. Keep private or non redistributable files outside the repository.
- Update documentation when user visible behavior, setup, configuration, or supported capabilities change. Do not claim support beyond what code and tests establish.

## Run checks

Use Python 3.12 or newer. From the repository root, create an isolated environment, install test dependencies and run the offline suite:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest -q tests
```

Relevant focused checks can be run individually. For example:

```bash
python3 -m pytest -q tests/test_cli_doc.py
python3 -m pytest -q tests/test_providers.py
```

Checks that call a real external legal data service are marked `live` and are excluded from the default run; run them explicitly with `python -m pytest -m live`. The offline suite uses fake transports and synthetic fixtures and does not contact a matter or a real service. Check the CI workflow for the current Python versions and additional integration jobs.

Report which checks you actually ran and their result in the pull request. Clearly identify checks not run and why. Do not describe a pending CI job as passing.

### US spelling in prose

Prose in this repository uses American spellings for the color/honor family: color, honor, behavior, not the British forms. The `spelling` CI job runs `scripts/check_us_spelling.py`, which scans only the lines a pull request adds to Markdown files, plus the PR description, and fails with the American replacement for each British form it finds. Text a change does not touch is never scanned, and code identifiers are not prose. The word list lives in one place, `BRITISH_TO_US` in the script. Run it locally before pushing:

```bash
python3 scripts/check_us_spelling.py --base origin/main
```

A line that must keep a British spelling (quoted upstream text, an exact identifier) carries an HTML comment naming the allowed word: `<!-- us-spelling: allow colour -->` allows that word on that line, and a bare `<!-- us-spelling: allow -->` allows every listed word on the line. <!-- us-spelling: allow -->


## Legal-work safety rules (Hermes Legal specific)

- **Never commit real client material.** No real matters, documents, names,
  docket numbers from a live case, or correspondence. Use the synthetic demo
  matter, or write a new fictional fixture and say so in the PR.
- **Privacy ceilings are a hard gate,** like a confirmation gate elsewhere:
  do not weaken the LOCAL-ONLY default, the per-matter ceiling check, or the
  blocked consumer tier to make a test pass.
- **Citations are verified by a resolver or not at all.** Never add code or
  copy that presents a model-generated citation as checked.
- **Writes ask first.** Filing, sending, signing and syncing stay approval
  gated, and refused in unattended runs.
