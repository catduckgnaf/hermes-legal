# Models and privacy tiers

## Tiers
| Tier | What leaves the device | Training | Retention |
|---|---|---|---|
| LOCAL-ONLY | Nothing | Impossible | Your files only |
| ZERO-RETENTION | Approved prompt + chunks, TLS, named provider/region | Contractually no | None under the agreement (safety-classifier results may be kept by some providers) |
| STANDARD | Same, to a no-training paid API | No | Typically up to 30 days of abuse/safety logs |
| BLOCKED | Consumer chat accounts, free AI Studio tier | May train | 30 days or longer |

## Local models (downloaded at your request, never bundled)
| Model | Size (Q4) | Hardware | License | Role |
|---|---|---|---|---|
| Qwen3 4B | 3-5 GB | 8 GB RAM | Apache-2.0 | Triage, summaries, classification |
| Qwen3 8B | 5-7 GB | 16 GB RAM / 8 GB VRAM | Apache-2.0 | Default minimum |
| Qwen3 14B | 9-10 GB | 12 GB VRAM | Apache-2.0 | Laptop sweet spot |
| Mistral Small 24B | 14-16 GB | 16 GB VRAM | Apache-2.0 | Contract review first pass |
| Qwen3 32B | 18-21 GB | 24 GB VRAM | Apache-2.0 | Recommended quality tier |
| Llama 3.3 70B | 40-44 GB | 48 GB+ VRAM | Llama Community License | Best local reasoning |

Runtimes: Ollama, LM Studio, llama.cpp, Jan. Embeddings are local too
(bge / nomic class models) — a cloud embedding call leaks as much as a chat call.

## Zero-retention cloud (terms checked 2026-11-09; re-verify before relying)
Anthropic API with a zero-retention agreement; OpenAI API with zero data
retention (eligible endpoints, by approval); Azure OpenAI; AWS Bedrock;
Groq and Fireworks for open models. OpenRouter is offered only in a
zero-retention-provider allowlist mode — per-provider variance is the trap, and
Together with storage left on is **not** zero retention.

## Enforcement in code

The ceiling is enforced by the provider router in
`hermes_legal.providers`, not by a settings page:

- `route(ceiling, requested)` returns a provider only when its tier is at
  or below the matter ceiling. With no request it returns the first
  allowed provider, which is always a local one.
- A provider above the ceiling raises `PrivacyViolationError`. A
  BLOCKED-tier provider — and any provider that trains on data, whatever
  tier it claims — raises `BlockedProviderError` at every ceiling.
  Routing by name resolves through the catalog, so a blocked product
  cannot be laundered by asserting a lower tier.
- OpenRouter raises unless zero-retention allowlist mode is enabled
  explicitly (`zero_retention_allowlist=True`).
- An unknown ceiling or tier raises `ValueError`: a typo fails closed
  instead of comparing as allowed. BLOCKED is a provider tier, never a
  valid matter ceiling.
- Every catalog entry carries a `terms_checked` date; an entry with a
  missing or malformed date cannot be constructed.

Run `legal models` to see the full catalog grouped by tier with each
provider's retention and terms-checked date, `legal models --ceiling
LOCAL_ONLY` to see only what a LOCAL_ONLY matter may use, and
`legal models --json` for the machine-readable form.

## Pre-send preview

Every Ask and send is preceded by a preview built by `build_preview`:
the tier badge, the provider, the matter ceiling, the model, exactly
which files and chunks would go out (with character counts), the
retention terms, and whether anything leaves the device at all. The
preview is built only after the router has allowed the provider, so a
refused send produces an error, never a preview that looks approved.

## Per-matter AI log

Each allowed call is written to the `ai_log` table with the matter,
provider, tier, model, action and time. `log_ai_use` enforces the
matter's stored ceiling before writing, so a refused call is never
recorded as if it happened, and `route_and_log` routes and logs in one
enforced step. The log is exportable per matter as JSON or CSV
(`export_ai_log`).

## Doctor warnings

`legal doctor` warns, offline, when a cloud provider's terms-checked
date is stale (older than 90 days) and when a STANDARD-tier provider is
selected for a LOCAL_ONLY matter. Warnings are `warn` lines: they name
the problem without failing the integration checks.
