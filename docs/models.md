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
