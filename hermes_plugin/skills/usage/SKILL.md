---
name: hermes-legal:usage
description: Use hermes-legal's legal_* tools for matters, documents, citations and deadlines. Local-first; writes need approval.
---
# hermes-legal usage

- Reads are local and return exactly what the matching `legal` CLI command prints.
- Never state that a citation is real, good law, or supportive of a proposition
  unless legal_cite_check returned that status from a resolver. "Exists" is not
  "good law": there is no Shepard's or KeyCite here, and the tool says so.
- A matter's privacy ceiling is a hard limit. If a matter is LOCAL-ONLY, do not
  send its content to any cloud model, connector or transcription service.
- Redlines are proposals. They are attributed to the AI, marked unverified, and
  become part of a document only when a human accepts them.
- Filing, sending and signing are never done by a tool. legal_efile_bundle only
  prepares a bundle for a human to file.
