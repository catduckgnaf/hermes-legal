"""The privacy tier model. This is the product, not a settings afterthought.

A matter carries a ceiling tier. The router refuses any provider above that
ceiling, and refuses consumer chat products for client work outright.
Terms change: every cloud entry carries the date its terms were last checked,
and `legal doctor` warns when a check is stale.

Enforcement lives here, in code, not in a settings page:

- ``allowed()`` answers the boolean question for display code.
- ``require_allowed()`` and ``route()`` are the enforcement path: they raise
  ``PrivacyViolationError`` instead of returning a provider, so a caller
  cannot accidentally (or deliberately) proceed with a refused provider.
- ``build_preview()`` builds the pre-send preview only after enforcement has
  passed, so a refused send never produces a preview that looks approved.
- ``log_ai_use()`` writes the per-matter AI log, and only for a call the
  router allowed.
"""
import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date

TIERS = ("LOCAL_ONLY", "ZERO_RETENTION", "STANDARD", "BLOCKED")

# Rank for ceiling comparison. BLOCKED has no rank: it is never a valid
# ceiling and never an allowed provider tier.
TIER_ORDER = {"LOCAL_ONLY": 0, "ZERO_RETENTION": 1, "STANDARD": 2}

# A cloud provider whose terms were checked longer ago than this is stale.
STALE_AFTER_DAYS = 90


class PrivacyViolationError(ValueError):
    """A provider was requested that the matter ceiling does not allow."""


class BlockedProviderError(PrivacyViolationError):
    """A BLOCKED-tier (consumer) provider was requested for client work."""


def _parse_date(value, field_name="terms_checked"):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


@dataclass(frozen=True)
class Provider:
    name: str
    tier: str            # one of TIERS
    trains_on_data: bool
    retention: str
    terms_checked: str   # ISO date the privacy terms were last verified
    notes: str = ""
    requires_zero_retention_allowlist: bool = False

    def __post_init__(self):
        if self.tier not in TIERS:
            raise ValueError(f"unknown provider tier {self.tier!r}; expected one of {TIERS}")
        if not str(self.name).strip():
            raise ValueError("provider name must not be empty")
        # Every provider entry carries a terms-checked date (acceptance
        # criterion for issue #4); a missing or malformed date fails here,
        # at construction, not later in a doctor run.
        _parse_date(self.terms_checked)

    @property
    def terms_checked_date(self):
        return _parse_date(self.terms_checked)

    @property
    def is_local(self):
        return self.tier == "LOCAL_ONLY"

    @property
    def is_cloud(self):
        return self.tier != "LOCAL_ONLY"


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
    Provider("OpenRouter, zero-retention providers only", "STANDARD", False, "per provider; routing must be pinned to the zero-retention allowlist", "2026-11-09", "Together with storage left on is not zero-retention.", requires_zero_retention_allowlist=True),
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


# ---------------------------------------------------------------------------
# Ceiling validation and the boolean check
# ---------------------------------------------------------------------------

def validate_ceiling(matter_ceiling):
    """Return the normalized ceiling or raise ValueError.

    A ceiling must be LOCAL_ONLY, ZERO_RETENTION or STANDARD. BLOCKED is a
    provider tier, never a matter ceiling, and an unknown string is a
    programming error that must fail closed rather than compare as allowed.
    """
    ceiling = str(matter_ceiling or "").strip().upper()
    if ceiling == "BLOCKED":
        raise ValueError("BLOCKED is a provider tier, not a matter ceiling")
    if ceiling not in TIER_ORDER:
        raise ValueError(
            f"unknown matter ceiling {matter_ceiling!r}; expected one of "
            f"{tuple(TIER_ORDER)}"
        )
    return ceiling


def _violation_reason(provider, matter_ceiling, *, zero_retention_allowlist=False):
    """Human reason a provider is refused, or None when it is allowed."""
    ceiling = validate_ceiling(matter_ceiling)
    if provider.tier == "BLOCKED" or provider.trains_on_data:
        return (
            f"{provider.name} is in the BLOCKED tier and is refused for "
            "client work at every ceiling"
        )
    if TIER_ORDER[provider.tier] > TIER_ORDER[ceiling]:
        return (
            f"{provider.name} is {provider.tier}, above the matter ceiling "
            f"{ceiling}"
        )
    if provider.requires_zero_retention_allowlist and not zero_retention_allowlist:
        return (
            f"{provider.name} may only be used in zero-retention provider "
            "allowlist mode; enable that mode explicitly so routing stays "
            "pinned to the allowlist"
        )
    return None


def allowed(provider: Provider, matter_ceiling: str, *, zero_retention_allowlist: bool = False) -> bool:
    """May this provider be used for a matter with this ceiling tier?

    Returns False for the BLOCKED tier and for any provider above the
    ceiling. Raises ValueError for an unknown ceiling or tier so a typo
    fails closed instead of silently comparing as allowed.
    """
    return _violation_reason(
        provider, matter_ceiling,
        zero_retention_allowlist=zero_retention_allowlist,
    ) is None


def require_allowed(provider: Provider, matter_ceiling: str, *, zero_retention_allowlist: bool = False) -> Provider:
    """Return the provider, or raise PrivacyViolationError.

    This is the enforcement entry point. Unlike ``allowed()``, there is no
    boolean for a caller to ignore: a refused provider raises, and a
    BLOCKED-tier provider raises the BlockedProviderError subclass.
    """
    reason = _violation_reason(
        provider, matter_ceiling,
        zero_retention_allowlist=zero_retention_allowlist,
    )
    if reason is None:
        return provider
    if provider.tier == "BLOCKED" or provider.trains_on_data:
        raise BlockedProviderError(reason)
    raise PrivacyViolationError(reason)


# ---------------------------------------------------------------------------
# Catalog lookup and the router
# ---------------------------------------------------------------------------

def find_provider(name) -> Provider:
    """Resolve a catalog provider by exact or unique prefix name.

    Routing by name always resolves through the catalog, so the tier that
    is enforced is the catalog tier, not a tier a caller asserts.
    """
    if isinstance(name, Provider):
        # A caller-supplied object that claims a catalog name is enforced
        # as the catalog entry, not as the tier the object asserts: naming
        # a blocked product "LOCAL_ONLY" does not launder it.
        for provider in PROVIDERS:
            if provider.name.casefold() == name.name.strip().casefold():
                return provider
        return name
    wanted = str(name or "").strip().casefold()
    if not wanted:
        raise ValueError("provider name must not be empty")
    for provider in PROVIDERS:
        if provider.name.casefold() == wanted:
            return provider
    matches = [p for p in PROVIDERS if p.name.casefold().startswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(
            f"ambiguous provider name {name!r}: "
            + ", ".join(p.name for p in matches)
        )
    raise ValueError(f"unknown provider {name!r}; see `legal models` for the catalog")


def allowed_providers(matter_ceiling: str, *, zero_retention_allowlist: bool = False):
    """Every catalog provider the ceiling allows, catalog order preserved."""
    ceiling = validate_ceiling(matter_ceiling)
    return [
        p for p in PROVIDERS
        if allowed(p, ceiling, zero_retention_allowlist=zero_retention_allowlist)
    ]


def route(matter_ceiling: str, requested=None, *, zero_retention_allowlist: bool = False) -> Provider:
    """Select a provider for a matter ceiling; raise on any violation.

    With no request, the first allowed catalog provider is selected, which
    is a local provider: the default never leaves the device. With a
    request (a Provider or a catalog name), the request is enforced: a
    provider above the ceiling, a BLOCKED provider, a provider that trains
    on data, or an allowlist-only provider used outside allowlist mode all
    raise instead of being returned.
    """
    ceiling = validate_ceiling(matter_ceiling)
    if requested is None:
        candidates = allowed_providers(
            ceiling, zero_retention_allowlist=zero_retention_allowlist
        )
        if not candidates:  # pragma: no cover - a local provider always qualifies
            raise PrivacyViolationError(f"no provider is allowed at ceiling {ceiling}")
        return candidates[0]
    provider = find_provider(requested)
    return require_allowed(
        provider, ceiling, zero_retention_allowlist=zero_retention_allowlist
    )


# Backwards-readable alias: routing *is* provider selection.
select_provider = route


# ---------------------------------------------------------------------------
# Terms freshness (doctor support)
# ---------------------------------------------------------------------------

def terms_age_days(provider: Provider, today=None) -> int:
    today = today or date.today()
    if isinstance(today, str):
        today = _parse_date(today, "today")
    return (today - provider.terms_checked_date).days


def is_stale(provider: Provider, today=None, *, stale_after_days: int = STALE_AFTER_DAYS) -> bool:
    """True when a cloud provider's terms check is older than the limit.

    Local providers are checked too if their date is malformed, but
    construction already guarantees a valid date; staleness warnings are
    about cloud terms, which are the ones that change under the user.
    """
    return terms_age_days(provider, today) > stale_after_days


def stale_providers(today=None, *, stale_after_days: int = STALE_AFTER_DAYS, providers=None):
    """Cloud providers whose terms-checked date is stale."""
    return [
        p for p in (providers if providers is not None else PROVIDERS)
        if p.is_cloud and is_stale(p, today, stale_after_days=stale_after_days)
    ]


def tier_badge(provider) -> str:
    """The short badge shown on every Ask and send surface."""
    provider = find_provider(provider)
    return f"[{provider.tier}] {provider.name}"


# ---------------------------------------------------------------------------
# Pre-send preview
# ---------------------------------------------------------------------------

def _chunk_record(chunk, index):
    """Normalize one chunk (str, mapping, or (file, text) pair) for display."""
    if isinstance(chunk, str):
        return {"index": index, "file": "", "chars": len(chunk), "excerpt": chunk[:80]}
    if isinstance(chunk, dict):
        text = str(chunk.get("text", chunk.get("content", "")))
        return {
            "index": index,
            "file": str(chunk.get("file", chunk.get("path", ""))),
            "chars": int(chunk.get("chars", len(text))),
            "excerpt": text[:80],
        }
    if isinstance(chunk, (tuple, list)) and len(chunk) == 2:
        file_name, text = chunk
        text = str(text)
        return {"index": index, "file": str(file_name), "chars": len(text), "excerpt": text[:80]}
    text = str(chunk)
    return {"index": index, "file": "", "chars": len(text), "excerpt": text[:80]}


@dataclass(frozen=True)
class PreSendPreview:
    """Exactly what would go out, to whom, under which tier.

    Built only after the router has allowed the provider, so holding a
    preview means the send it describes is permitted at the ceiling.
    """
    provider: Provider
    matter_ceiling: str
    model: str = ""
    files: tuple = ()
    chunks: tuple = field(default_factory=tuple)

    @property
    def badge(self):
        return tier_badge(self.provider)

    @property
    def leaves_device(self):
        return self.provider.tier != "LOCAL_ONLY"

    @property
    def chunk_count(self):
        return len(self.chunks)

    @property
    def total_chars(self):
        return sum(c["chars"] for c in self.chunks)

    @property
    def file_list(self):
        names = list(self.files)
        for chunk in self.chunks:
            if chunk["file"] and chunk["file"] not in names:
                names.append(chunk["file"])
        return names

    def to_dict(self):
        return {
            "provider": self.provider.name,
            "tier": self.provider.tier,
            "badge": self.badge,
            "matter_ceiling": self.matter_ceiling,
            "model": self.model,
            "leaves_device": self.leaves_device,
            "retention": self.provider.retention,
            "terms_checked": self.provider.terms_checked,
            "files": self.file_list,
            "chunks": [dict(c) for c in self.chunks],
            "chunk_count": self.chunk_count,
            "total_chars": self.total_chars,
        }

    def render(self):
        destination = (
            "nothing leaves the device"
            if not self.leaves_device
            else f"sends to {self.provider.name} over TLS"
        )
        lines = [
            f"Pre-send preview — {self.badge}",
            f"Matter ceiling: {self.matter_ceiling} | Model: {self.model or '(default)'}",
            f"Destination: {destination} | Retention: {self.provider.retention}",
            f"Files ({len(self.file_list)}):",
        ]
        lines += [f"  - {name}" for name in self.file_list] or ["  - (none)"]
        lines.append(f"Chunks ({self.chunk_count}, {self.total_chars} characters):")
        for chunk in self.chunks:
            where = f" from {chunk['file']}" if chunk["file"] else ""
            lines.append(f"  - chunk {chunk['index']}{where}: {chunk['chars']} characters")
        return "\n".join(lines)

    __str__ = render


def build_preview(provider, matter_ceiling, files=(), chunks=(), *, model="", zero_retention_allowlist=False) -> PreSendPreview:
    """Build the pre-send preview, raising on any ceiling violation.

    Enforcement runs first: a BLOCKED or over-ceiling provider raises
    PrivacyViolationError and no preview is produced.
    """
    ceiling = validate_ceiling(matter_ceiling)
    resolved = route(
        ceiling, provider, zero_retention_allowlist=zero_retention_allowlist
    )
    return PreSendPreview(
        provider=resolved,
        matter_ceiling=ceiling,
        model=model,
        files=tuple(str(f) for f in files),
        chunks=tuple(_chunk_record(c, i) for i, c in enumerate(chunks)),
    )


# ---------------------------------------------------------------------------
# Per-matter AI log (ai_log table in db.py)
# ---------------------------------------------------------------------------

def _matter_ceiling(conn, matter_id):
    row = conn.execute(
        "SELECT privacy_ceiling FROM matters WHERE id=?", (matter_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown matter id: {matter_id!r}")
    return validate_ceiling(row[0])


def log_ai_use(conn, matter_id, provider, action, *, model="", matter_ceiling=None, zero_retention_allowlist=False):
    """Write one ai_log row for an allowed call; return the row id.

    The provider is enforced against the matter's stored ceiling (or the
    ceiling passed explicitly) before anything is written, so the log can
    never record a refused call as if it happened. The row carries the
    provider, its tier, the model, the action and the timestamp the table
    defaults to now.
    """
    resolved = find_provider(provider)
    ceiling = (
        validate_ceiling(matter_ceiling)
        if matter_ceiling is not None
        else _matter_ceiling(conn, matter_id)
    )
    require_allowed(
        resolved, ceiling, zero_retention_allowlist=zero_retention_allowlist
    )
    if not str(action or "").strip():
        raise ValueError("action must not be empty")
    cur = conn.execute(
        "INSERT INTO ai_log (matter_id, provider, tier, model, action) "
        "VALUES (?, ?, ?, ?, ?)",
        (matter_id, resolved.name, resolved.tier, str(model), str(action)),
    )
    conn.commit()
    return cur.lastrowid


def route_and_log(conn, matter_id, requested=None, *, action, model="", zero_retention_allowlist=False) -> Provider:
    """Route for a matter and log the selection in one enforced step."""
    ceiling = _matter_ceiling(conn, matter_id)
    provider = route(
        ceiling, requested, zero_retention_allowlist=zero_retention_allowlist
    )
    log_ai_use(
        conn, matter_id, provider, action, model=model, matter_ceiling=ceiling,
        zero_retention_allowlist=zero_retention_allowlist,
    )
    return provider


def list_ai_log(conn, matter_id):
    """All ai_log rows for one matter, oldest first, as plain dicts."""
    rows = conn.execute(
        "SELECT id, matter_id, provider, tier, model, action, created_at "
        "FROM ai_log WHERE matter_id=? ORDER BY id",
        (matter_id,),
    ).fetchall()
    keys = ("id", "matter_id", "provider", "tier", "model", "action", "created_at")
    return [dict(zip(keys, row)) for row in rows]


def export_ai_log(conn, matter_id, *, format="json"):
    """Export one matter's AI log as JSON (default) or CSV text."""
    records = list_ai_log(conn, matter_id)
    if format == "json":
        return json.dumps(records, indent=2)
    if format == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(
            out, fieldnames=["id", "matter_id", "provider", "tier", "model", "action", "created_at"]
        )
        writer.writeheader()
        writer.writerows(records)
        return out.getvalue()
    raise ValueError(f"unknown export format {format!r}; expected 'json' or 'csv'")
