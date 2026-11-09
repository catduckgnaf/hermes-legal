"""The privacy tier model. This is the product, not a settings afterthought.

A matter carries a ceiling tier. The router refuses any provider above that
ceiling, and refuses consumer chat products for client work outright.
Terms change: every cloud entry carries the date its terms were last checked,
and `legal doctor` warns when a check is stale.
"""
from dataclasses import dataclass

TIERS = ("LOCAL_ONLY", "ZERO_RETENTION", "STANDARD", "BLOCKED")

@dataclass(frozen=True)
class Provider:
    name: str
    tier: str            # one of TIERS
    trains_on_data: bool
    retention: str
    terms_checked: str   # ISO date the privacy terms were last verified
    notes: str = ""

PROVIDERS = [
    Provider("Local (llama.cpp / Ollama)", "LOCAL_ONLY", False, "none — nothing leaves the device", "2026-11-09", "Default. Embeddings, OCR and transcription local too."),
    Provider("Local (LM Studio)", "LOCAL_ONLY", False, "none — nothing leaves the device", "2026-11-09", "Closed-source runtime, free for work use; weights keep their own licenses."),
    Provider("Anthropic API with a zero-retention agreement", "ZERO_RETENTION", False, "none under the agreement; safety-classifier results may be retained", "2026-11-09"),
    Provider("OpenAI API with zero data retention", "ZERO_RETENTION", False, "none for eligible endpoints, by prior approval", "2026-11-09"),
    Provider("Azure OpenAI", "ZERO_RETENTION", False, "in-tenant; abuse monitoring limited for approved customers", "2026-11-09"),
    Provider("AWS Bedrock", "ZERO_RETENTION", False, "in-region; zero-retention mode available", "2026-11-09"),
    Provider("Groq / Fireworks (open models)", "ZERO_RETENTION", False, "not retained by default for open models", "2026-11-09", "Verify the store flag is off."),
    Provider("Anthropic API (paid, no zero-retention agreement)", "STANDARD", False, "up to 30 days of abuse/safety logs", "2026-11-09"),
    Provider("OpenAI API (paid)", "STANDARD", False, "up to 30 days of abuse logs", "2026-11-09"),
    Provider("OpenRouter, zero-retention providers only", "STANDARD", False, "per provider; routing must be pinned to the zero-retention allowlist", "2026-11-09", "Together with storage left on is not zero-retention."),
    Provider("Consumer chat (free / Plus / Pro personal accounts)", "BLOCKED", True, "30 days or longer; personal-account terms", "2026-11-09", "Blocked for client work. Heppner (S.D.N.Y. 2026): consumer chats were held neither privileged nor work product."),
    Provider("Google AI Studio free tier", "BLOCKED", True, "per consumer terms", "2026-11-09", "Use Vertex AI instead for Google models on client work."),
]

LOCAL_MODELS = [
    # name, approx size at Q4, minimum useful hardware, license, role
    ("Qwen3 4B", "3-5 GB", "8 GB RAM, no GPU", "Apache-2.0", "Summaries, classification, intake triage only"),
    ("Qwen3 8B", "5-7 GB", "16 GB RAM / 8 GB VRAM", "Apache-2.0", "Default minimum for drafting"),
    ("Qwen3 14B", "9-10 GB", "16-24 GB RAM / 12 GB VRAM", "Apache-2.0", "Better drafting and reasoning on a laptop"),
    ("Mistral Small 24B", "14-16 GB", "32 GB RAM / 16 GB VRAM", "Apache-2.0", "Strong contract review first pass"),
    ("Qwen3 32B", "18-21 GB", "24 GB VRAM / 32 GB unified memory", "Apache-2.0", "Recommended quality local tier"),
    ("Llama 3.3 70B", "40-44 GB", "48 GB+ VRAM / 64-128 GB unified memory", "Llama Community License", "Best local reasoning; license is not OSI"),
]

def allowed(provider: Provider, matter_ceiling: str) -> bool:
    """May this provider be used for a matter with this ceiling tier?"""
    if provider.tier == "BLOCKED":
        return False
    order = {"LOCAL_ONLY": 0, "ZERO_RETENTION": 1, "STANDARD": 2}
    return order[provider.tier] <= order[matter_ceiling]
