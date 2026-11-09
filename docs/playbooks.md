# Playbooks and the clause library

A playbook is a firm's own review positions written as an open,
editable Markdown file. Reviewing a contract against a playbook is
the behavior behind the `legal_playbook_review` tool: it splits the
contract into clauses, checks each rule in the playbook, and returns
findings tied to clauses, with a rationale and, where the playbook
gives one, fallback language. It changes nothing.

Proposed language in a finding is a suggestion only. It becomes a
redline only through the approval-gated `legal_doc_redline` tool,
which creates real Word track changes for a human to accept or reject.

## The sample playbooks

Three samples ship in the `playbooks/` folder at the repository root:

- `playbooks/nda.md` — mutual non-disclosure agreement
- `playbooks/msa.md` — master services agreement
- `playbooks/employment.md` — employment agreement

A synthetic demo contract ships beside them at
`playbooks/demo-contract.md`. Every name and fact in it is fictional.
All three sample playbooks run against that demo contract and produce
findings tied to clauses: for example a forbidden perpetuity finding
on its confidentiality clause under the NDA playbook, a payment-window
deviation on its payment clause under the MSA playbook, and an
overbroad non-compete finding on its restrictive-covenants clause
under the employment playbook.

The samples are starting points. Replace their positions with your
firm's positions before relying on a review. Employment positions in
particular vary by jurisdiction.

## Editing a playbook changes the review

No code change is needed. Edit a rule in the Markdown file — change a
pattern, a severity, a preferred position, or the fallback language —
save the file, and run the review again. The next result reflects the
edited file because the parser reads the file at review time. The test
suite pins this behavior: it reviews a contract, edits a copied
playbook file on disk, reviews again, and checks that the output
changed.

## Playbook file format

The format is Markdown with YAML-ish `key: value` lines, parsed with
the standard library only. There is no YAML dependency.

A file has three parts:

1. A header: a `# Playbook: ...` title followed by `id:`, `name:`,
   `version:`, and `description:` lines. The `id` is required.
2. A `## Rules` section. Each rule is a `### rule-id` heading followed
   by field lines.
3. An optional `## Clause library` section. Each library entry is a
   `### clause-id` heading followed by field lines.

Prose outside a `###` block is ignored, so a playbook can carry human
notes without breaking the parser.

### Rule fields

- `title:` — the human-readable name of the position.
- `kind:` — one of `required`, `forbidden`, or `fallback`. The longer
  spellings `required_clause`, `forbidden_language`, and
  `fallback_position` are also accepted.
- `severity:` — for example `high`, `medium`, or `low`.
- `topic:` — a short topic label, carried into each finding.
- `patterns:` — semicolon-separated phrases that locate the relevant
  clause and, for a forbidden rule, the offending language. A pattern
  wrapped in slashes, such as `/net\s+30/`, is a regular expression;
  every other pattern is a case-insensitive substring. Semicolons are
  the separator so a phrase may contain commas.
- `must_contain:` — semicolon-separated elements a required clause
  must also contain. If the clause is present but an element is
  missing, the finding status is `incomplete` and names the clause.
- `preferred:` and `acceptable:` — for a `fallback` rule, the
  preferred position and the acceptable fallback positions,
  semicolon-separated.
- `rationale:` — why the firm holds this position. It is carried into
  the finding so the reader sees the reason, not only a flag.
- `fallback:` — proposed language for the position. For a `fallback`
  rule this is the language to propose when the contract deviates.

### How each rule kind is checked

- `required` — if no clause matches `patterns`, the finding status is
  `missing`. If a clause matches but a `must_contain` element is
  absent, the status is `incomplete` and the finding names that clause.
- `forbidden` — every clause that matches `patterns` produces a
  `forbidden` finding tied to that clause, with an excerpt.
- `fallback` — the located clause is compared with `preferred` first,
  then with `acceptable`. A preferred match produces no finding. An
  acceptable match produces a `fallback_acceptable` finding at low
  severity. Any other text produces a `deviation` finding that carries
  the playbook's fallback language. If no clause is located, the
  status is `missing`.

### Clause library fields

- `title:` — the clause name.
- `language:` — the preferred clause language.
- `fallback:` — the fallback language or the fallback trade-off if
  the preferred language will not be accepted.
- `notes:` — guidance for the human reviewer.

Library entries do not change rule checking by themselves. They are
the reusable language a reviewer (or, through the approval gate, the
redline tool) draws on when a finding calls for proposed language.

## Clause splitting

`split_clauses` in `hermes_legal.playbooks` splits contract text by
Markdown headings, by `Section`, `Article`, or `Clause` headings, and
by numbered headings such as `1. Confidentiality`. If a contract has
no usable headings, it falls back to splitting on blank lines, one
clause per paragraph. Each clause keeps its index, number, heading,
and full text, and each finding that names a clause carries that
index and heading so a reader can find the passage in the contract.

## Programmatic use

```python
from pathlib import Path
from hermes_legal.playbooks import legal_playbook_review, load_playbook

playbook = load_playbook(Path("playbooks/nda.md"))
contract = Path("playbooks/demo-contract.md").read_text(encoding="utf-8")
result = legal_playbook_review(contract, playbook)
for finding in result.findings:
    print(finding.rule_id, finding.status, finding.clause_heading, finding.message)
print(result.to_dict()["summary"])
```

`legal_playbook_review` also accepts a path to a playbook file or raw
playbook text, which is how the editing test drives it.
