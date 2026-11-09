# Security and confidentiality

## What stays on your computer
- `legal.db` (SQLite, WAL) in a 0700 directory, file 0600. Read-only agent
  connections redact credential columns to NULL.
- Matter files stay in your folders. Nothing is uploaded to open, index or edit
  a document: indexing, OCR, embeddings and transcription all run locally.
- A downloadable backup excludes every credential, session and token.

## Access modes
**This computer only** (default, loopback, no login) · **Behind your proxy
login** (Tailscale Serve, Cloudflare Access, Authelia) · **Built-in login**
(argon2id password + authenticator app). The app refuses to start where it would
be reachable from other devices without one of these protecting it.

## Ethics, built in (ABA Formal Opinion 512, 29 July 2024)
- Rule 1.1 competence: the app logs which model and version produced what.
- Rule 1.6 confidentiality: LOCAL-ONLY is the default; putting matter material
  into a self-learning tool needs informed client consent, and boilerplate
  consent is not sufficient — so consumer chat products are blocked, not warned.
- Rules 5.1 / 5.3 supervision: the tool is supervised like a nonlawyer assistant.
  Its output is draft until a lawyer accepts it.
- Rule 3.3 candor: no citation enters a document without a resolver check.
  *Mata v. Avianca* (S.D.N.Y. 2023) drew a $5,000 sanction for six invented
  opinions the lawyers then stood behind. The Verify-All gate exists because of it.
- *Heppner* (S.D.N.Y. 2026): consumer AI chats were held neither privileged nor
  work product, in part because consumer terms allowed disclosure. That is why
  the blocked tier exists.

## What leaves your computer
Only what a connector or a non-local model call sends, shown per connector in
[Integrations](integrations.md) and, in the app, in a pre-send preview that lists
exactly which files and chunks would go out, to whom, under which tier.
