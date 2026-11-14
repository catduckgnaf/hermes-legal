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
- ``log_sent_payload()`` records what was actually sent: the hash and
  size of the exact payload bytes and the per-chunk content hashes,
  tied to the approved preview's fingerprint, refusing first when the
  payload diverges from that preview.
- A LOCAL_ONLY provider is verified local, not just labeled local: its
  endpoint (catalog default, its endpoint environment variable such as
  ``OLLAMA_HOST``, or an explicit endpoint) must resolve to loopback,
  and a cloud-routed model tag such as ``:cloud`` is refused.
"""
import csv
import hashlib
import io
import ipaddress
import json
import os
import socket
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

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
    # Where a LOCAL_ONLY runtime actually listens. Empty for cloud
    # providers, whose endpoint is the provider itself. ``endpoint_env``
    # names an environment variable that may override the endpoint (for
    # Ollama that is the runtime's own ``OLLAMA_HOST``); an override is
    # honored only after the loopback check in ``is_local_endpoint``.
    endpoint: str = ""
    endpoint_env: str = ""

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
    Provider("Local (llama.cpp / Ollama)", "LOCAL_ONLY", False, "none — nothing leaves the device", "2026-11-09", "Default. Embeddings, OCR and transcription local too.", endpoint="http://127.0.0.1:11434", endpoint_env="OLLAMA_HOST"),
    Provider("Local (LM Studio)", "LOCAL_ONLY", False, "none — nothing leaves the device", "2026-11-09", "Closed-source runtime, free for work use; weights keep their own licenses.", endpoint="http://127.0.0.1:1234/v1"),
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
# Locality: a LOCAL_ONLY label is verified, not trusted (issue #24)
# ---------------------------------------------------------------------------

def _default_resolver(host):
    """IP strings a host name resolves to, via the system resolver."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def provider_endpoint(provider: Provider, *, endpoint=None, environ=None) -> str:
    """The endpoint a provider would actually be reached at.

    An explicit ``endpoint`` wins, then the provider's endpoint
    environment variable (for example ``OLLAMA_HOST``), then the catalog
    default. Returns an empty string when no endpoint is known.
    """
    if endpoint is not None:
        return str(endpoint).strip()
    env = os.environ if environ is None else environ
    if provider.endpoint_env:
        value = str(env.get(provider.endpoint_env) or "").strip()
        if value:
            return value
    return str(provider.endpoint or "").strip()


def endpoint_host(endpoint) -> str:
    """The host part of an endpoint, or an empty string when unparsable.

    Scheme-less values such as ``127.0.0.1:11434`` (the usual
    ``OLLAMA_HOST`` shape) are parsed as host and port.
    """
    raw = str(endpoint or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    return str(parsed.hostname or "").strip().rstrip(".").casefold()


def is_local_endpoint(endpoint, *, resolver=None) -> bool:
    """True only when an endpoint's host is verified loopback.

    ``localhost`` names and literal loopback addresses (127.0.0.0/8 and
    ::1) need no lookup. Any other name is resolved, and every resolved
    address must be loopback: a name that resolves to a mix, resolves
    only off the device, or does not resolve at all is not local.
    """
    host = endpoint_host(endpoint)
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    resolve = resolver or _default_resolver
    try:
        addresses = list(resolve(host))
    except Exception:
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            if not ipaddress.ip_address(str(address)).is_loopback:
                return False
        except ValueError:
            return False
    return True


def is_cloud_routed_model(model) -> bool:
    """True for a model tag a local runtime routes to the cloud.

    Ollama marks cloud-routed models with a ``:cloud`` or ``-cloud``
    suffix (for example ``llama3.1:cloud`` or ``gpt-oss:120b-cloud``);
    running one through a local endpoint still sends data off the
    device, so the LOCAL_ONLY tier refuses it.
    """
    name = str(model or "").strip().casefold()
    return bool(name) and (
        name.endswith(":cloud") or name.endswith("-cloud") or ":cloud-" in name
    )


def _locality_reason(provider, *, model="", endpoint=None, environ=None, resolver=None):
    """Human reason a LOCAL_ONLY provider fails locality, or None."""
    if is_cloud_routed_model(model):
        return (
            f"model {model!r} is a cloud-routed model tag; a LOCAL_ONLY "
            "provider must run a model that stays on this device"
        )
    resolved_endpoint = provider_endpoint(
        provider, endpoint=endpoint, environ=environ
    )
    if not resolved_endpoint:
        return (
            f"{provider.name} is LOCAL_ONLY but has no endpoint on record, "
            "so there is no local endpoint to verify; refused"
        )
    if not is_local_endpoint(resolved_endpoint, resolver=resolver):
        return (
            f"{provider.name} is LOCAL_ONLY but its endpoint "
            f"{resolved_endpoint!r} does not resolve to a loopback address "
            "(localhost, 127.0.0.0/8 or ::1); a LOCAL_ONLY provider whose "
            "endpoint is remote or unresolvable as local is refused"
        )
    return None


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


def _violation_reason(provider, matter_ceiling, *, zero_retention_allowlist=False,
                      model="", endpoint=None, environ=None, resolver=None):
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
    if provider.tier == "LOCAL_ONLY":
        return _locality_reason(
            provider, model=model, endpoint=endpoint,
            environ=environ, resolver=resolver,
        )
    return None


def allowed(provider: Provider, matter_ceiling: str, *, zero_retention_allowlist: bool = False,
            model="", endpoint=None, environ=None, resolver=None) -> bool:
    """May this provider be used for a matter with this ceiling tier?

    Returns False for the BLOCKED tier and for any provider above the
    ceiling. A LOCAL_ONLY provider also returns False when its endpoint
    is not verified loopback or the model is cloud-routed. Raises
    ValueError for an unknown ceiling or tier so a typo fails closed
    instead of silently comparing as allowed.
    """
    return _violation_reason(
        provider, matter_ceiling,
        zero_retention_allowlist=zero_retention_allowlist,
        model=model, endpoint=endpoint, environ=environ, resolver=resolver,
    ) is None


def require_allowed(provider: Provider, matter_ceiling: str, *, zero_retention_allowlist: bool = False,
                    model="", endpoint=None, environ=None, resolver=None) -> Provider:
    """Return the provider, or raise PrivacyViolationError.

    This is the enforcement entry point. Unlike ``allowed()``, there is no
    boolean for a caller to ignore: a refused provider raises, and a
    BLOCKED-tier provider raises the BlockedProviderError subclass.
    """
    reason = _violation_reason(
        provider, matter_ceiling,
        zero_retention_allowlist=zero_retention_allowlist,
        model=model, endpoint=endpoint, environ=environ, resolver=resolver,
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


def _require_cataloged(provider: Provider) -> Provider:
    """Refuse a provider that is not in the catalog.

    A tier is only meaningful when this project recorded it. An object built
    at runtime can claim LOCAL_ONLY for anything, so it is never routable.
    """
    if provider not in PROVIDERS:
        raise PrivacyViolationError(
            f"{provider.name} is not in the provider catalog, so its privacy "
            "tier cannot be trusted; see `legal models`"
        )
    return provider


def allowed_providers(matter_ceiling: str, *, zero_retention_allowlist: bool = False,
                      model="", environ=None, resolver=None):
    """Every catalog provider the ceiling allows, catalog order preserved.

    Each LOCAL_ONLY provider is checked against its own catalog or
    environment endpoint, because providers do not share endpoints; an
    explicit per-provider endpoint is checked through allowed(),
    require_allowed() or route() for that one provider.
    """
    ceiling = validate_ceiling(matter_ceiling)
    return [
        p for p in PROVIDERS
        if allowed(p, ceiling, zero_retention_allowlist=zero_retention_allowlist,
                   model=model if p.tier == "LOCAL_ONLY" else "",
                   environ=environ, resolver=resolver)
    ]


def route(matter_ceiling: str, requested=None, *, zero_retention_allowlist: bool = False,
          model="", endpoint=None, environ=None, resolver=None) -> Provider:
    """Select a provider for a matter ceiling; raise on any violation.

    With no request, the first allowed catalog provider is selected, which
    is a local provider: the default never leaves the device. With a
    request (a Provider or a catalog name), the request is enforced: a
    provider above the ceiling, a BLOCKED provider, a provider that trains
    on data, or an allowlist-only provider used outside allowlist mode all
    raise instead of being returned. A LOCAL_ONLY provider also raises
    when its endpoint (catalog default, its endpoint environment
    variable, or the explicit ``endpoint``) is not verified loopback, or
    when ``model`` is a cloud-routed tag.
    """
    ceiling = validate_ceiling(matter_ceiling)
    if requested is None:
        candidates = allowed_providers(
            ceiling, zero_retention_allowlist=zero_retention_allowlist,
            model=model, environ=environ, resolver=resolver,
        )
        if not candidates:
            raise PrivacyViolationError(f"no provider is allowed at ceiling {ceiling}")
        return candidates[0]
    provider = find_provider(requested)
    # Catalog membership comes first: a tier asserted by an uncataloged
    # object cannot be trusted, whatever locality it also claims.
    _require_cataloged(provider)
    require_allowed(
        provider, ceiling, zero_retention_allowlist=zero_retention_allowlist,
        model=model, endpoint=endpoint, environ=environ, resolver=resolver,
    )
    return provider


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


def validate_provider_catalog(entries=None):
    """Return the catalog entries, or raise naming every bad entry.

    Every entry must carry a valid terms-checked date and a known tier.
    ``Provider`` construction already enforces this for catalog entries
    built in code; this validator covers catalogs assembled elsewhere
    (for example a doctor run over a supplied catalog), so a missing or
    malformed date fails loudly instead of reading as checked.
    """
    catalog = list(PROVIDERS if entries is None else entries)
    problems = []
    for entry in catalog:
        name = str(getattr(entry, "name", "") or "(unnamed provider)")
        if getattr(entry, "tier", None) not in TIERS:
            problems.append(f"{name}: unknown provider tier {getattr(entry, 'tier', None)!r}")
        try:
            _parse_date(getattr(entry, "terms_checked", ""))
        except ValueError:
            problems.append(
                f"{name}: missing or malformed terms-checked date "
                f"{getattr(entry, 'terms_checked', None)!r}"
            )
    if problems:
        raise ValueError("invalid provider catalog: " + "; ".join(problems))
    return catalog


def tier_badge(provider) -> str:
    """The short badge shown on every Ask and send surface."""
    provider = find_provider(provider)
    return f"[{provider.tier}] {provider.name}"


# ---------------------------------------------------------------------------
# Pre-send preview
# ---------------------------------------------------------------------------

def _chunk_record(chunk, index):
    """Normalize one chunk (str, mapping, or (file, text) pair) for display.

    Each record also carries the SHA-256 of the chunk's full text, so a
    preview record identifies its chunks by content, not only by an
    80-character excerpt, and a later payload can be checked against the
    exact chunks that were approved.
    """
    if isinstance(chunk, str):
        file_name, text, chars = "", chunk, len(chunk)
    elif isinstance(chunk, dict):
        text = str(chunk.get("text", chunk.get("content", "")))
        file_name = str(chunk.get("file", chunk.get("path", "")))
        chars = int(chunk.get("chars", len(text)))
    elif isinstance(chunk, (tuple, list)) and len(chunk) == 2:
        file_name, text = str(chunk[0]), str(chunk[1])
        chars = len(text)
    else:
        file_name, text = "", str(chunk)
        chars = len(text)
    return {
        "index": index,
        "file": file_name,
        "chars": chars,
        "excerpt": text[:80],
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


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
    endpoint: str = ""

    @property
    def preview_sha256(self):
        """Fingerprint of this approved preview.

        A hash over the provider, tier, ceiling, model, endpoint, files
        and per-chunk records (including each chunk's content hash). The
        sent-payload log records this fingerprint next to the hash of
        the payload actually sent, tying the send to this approval.
        """
        canonical = {
            "provider": self.provider.name,
            "tier": self.provider.tier,
            "matter_ceiling": self.matter_ceiling,
            "model": self.model,
            "endpoint": self.endpoint,
            "files": list(self.files),
            "file_list": self.file_list,
            "chunks": [dict(c) for c in self.chunks],
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

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
            "endpoint": self.endpoint,
            "leaves_device": self.leaves_device,
            "retention": self.provider.retention,
            "terms_checked": self.provider.terms_checked,
            "files": self.file_list,
            "chunks": [dict(c) for c in self.chunks],
            "chunk_count": self.chunk_count,
            "total_chars": self.total_chars,
            "preview_sha256": self.preview_sha256,
        }

    def render(self):
        destination = (
            "nothing leaves the device"
            + (f" — verified local endpoint {self.endpoint}" if self.endpoint else "")
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


def build_preview(provider, matter_ceiling, files=(), chunks=(), *, model="", zero_retention_allowlist=False,
                  endpoint=None, environ=None, resolver=None) -> PreSendPreview:
    """Build the pre-send preview, raising on any ceiling violation.

    Enforcement runs first: a BLOCKED or over-ceiling provider raises
    PrivacyViolationError and no preview is produced. For a LOCAL_ONLY
    provider the endpoint is verified loopback and a cloud-routed model
    tag raises too, so a preview can never describe a local send that
    would actually leave the device.
    """
    ceiling = validate_ceiling(matter_ceiling)
    resolved = route(
        ceiling, provider, zero_retention_allowlist=zero_retention_allowlist,
        model=model, endpoint=endpoint, environ=environ, resolver=resolver,
    )
    return PreSendPreview(
        provider=resolved,
        matter_ceiling=ceiling,
        model=model,
        files=tuple(str(f) for f in files),
        chunks=tuple(_chunk_record(c, i) for i, c in enumerate(chunks)),
        endpoint=(provider_endpoint(resolved, endpoint=endpoint, environ=environ)
                  if resolved.tier == "LOCAL_ONLY" else ""),
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


def log_ai_use(conn, matter_id, provider, action, *, model="", matter_ceiling=None, zero_retention_allowlist=False,
               endpoint=None, environ=None, resolver=None):
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
    _require_cataloged(resolved)
    require_allowed(
        resolved, ceiling, zero_retention_allowlist=zero_retention_allowlist,
        model=model, endpoint=endpoint, environ=environ, resolver=resolver,
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


def route_and_log(conn, matter_id, requested=None, *, action, model="", zero_retention_allowlist=False,
                  endpoint=None, environ=None, resolver=None) -> Provider:
    """Route for a matter and log the selection in one enforced step."""
    ceiling = _matter_ceiling(conn, matter_id)
    provider = route(
        ceiling, requested, zero_retention_allowlist=zero_retention_allowlist,
        model=model, endpoint=endpoint, environ=environ, resolver=resolver,
    )
    log_ai_use(
        conn, matter_id, provider, action, model=model, matter_ceiling=ceiling,
        zero_retention_allowlist=zero_retention_allowlist,
        endpoint=endpoint, environ=environ, resolver=resolver,
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


# ---------------------------------------------------------------------------
# Sent-payload log: what was actually sent, tied to the approved preview
# (issue #24 remainder)
# ---------------------------------------------------------------------------

def payload_bytes(payload) -> bytes:
    """The exact bytes of a payload to be sent.

    Bytes pass through unchanged (that identity is the point: the bytes
    hashed are the bytes sent). Text is encoded as UTF-8, and a mapping
    or sequence is serialized as canonical JSON.
    """
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, (bytearray, memoryview)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sent_payload_hash(payload) -> str:
    """SHA-256 of the exact payload bytes."""
    return hashlib.sha256(payload_bytes(payload)).hexdigest()


# Backwards-readable alias: the hash is of the payload, not of a prompt.
payload_sha256 = sent_payload_hash


def verify_payload_matches_preview(preview, chunks=None, *, model=None, files=None):
    """Raise when payload inputs diverge from the approved preview.

    The preview is the approval record. If the chunks (or the model, or
    the file list) that a caller is about to send differ from the ones
    the preview carries, the send must fail closed rather than log a
    hash that quietly describes different material than was approved.
    Returns the preview when everything supplied matches it.
    """
    if not isinstance(preview, PreSendPreview):
        raise ValueError("a PreSendPreview from build_preview() is required")
    if model is not None and str(model) != preview.model:
        raise PrivacyViolationError(
            f"model {model!r} does not match the approved preview model "
            f"{preview.model!r}; rebuild the preview and get it approved "
            "before sending"
        )
    if files is not None and [str(f) for f in files] != list(preview.files):
        raise PrivacyViolationError(
            "the files to send do not match the approved preview file "
            "list; rebuild the preview and get it approved before sending"
        )
    if chunks is not None:
        normalized = tuple(_chunk_record(c, i) for i, c in enumerate(chunks))
        if normalized != tuple(dict(c) for c in preview.chunks):
            raise PrivacyViolationError(
                "the chunks to send do not match the chunks in the "
                "approved preview; rebuild the preview and get it "
                "approved before sending"
            )
    return preview


def build_sent_payload_record(preview, payload, chunks=None, *, model=None, files=None):
    """The record tying one exact payload to its approved preview."""
    verify_payload_matches_preview(preview, chunks, model=model, files=files)
    raw = payload_bytes(payload)
    return {
        "provider": preview.provider.name,
        "tier": preview.provider.tier,
        "model": preview.model,
        "preview_sha256": preview.preview_sha256,
        "sent_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "sent_bytes": len(raw),
        "chunk_count": preview.chunk_count,
        "chunk_ids": [
            f"{c['index']}:{c['file']}" if c["file"] else str(c["index"])
            for c in preview.chunks
        ],
        "chunk_sha256": [c["sha256"] for c in preview.chunks],
        "files": preview.file_list,
    }


def log_sent_payload(conn, matter_id, preview, payload, *, action="ask", chunks=None,
                     model=None, files=None, endpoint=None, environ=None, resolver=None):
    """Write the AI log row for a payload actually sent; return its record.

    Verification runs first: a payload whose chunks or model diverge
    from the approved preview raises ``PrivacyViolationError`` and no
    row is written. The row's action carries the hash of the exact
    payload bytes, its size in bytes, the per-chunk content hashes and
    the approved preview's fingerprint, so an auditor holding the
    payload and the preview can prove sent == approved. The record is
    part of the per-matter AI log, so ``export_ai_log`` exports it with
    the rest of the log.
    """
    record = build_sent_payload_record(preview, payload, chunks, model=model, files=files)
    base = str(action or "").strip()
    if not base:
        raise ValueError("action must not be empty")
    detail = (
        f"{base} sent_sha256={record['sent_sha256']}"
        f" preview_sha256={record['preview_sha256']}"
        f" sent_bytes={record['sent_bytes']}"
        f" chunks={record['chunk_count']}"
        f" chunk_sha256={','.join(record['chunk_sha256']) or '-'}"
    )
    row_id = log_ai_use(
        conn, matter_id, preview.provider, detail, model=preview.model,
        matter_ceiling=preview.matter_ceiling,
        endpoint=endpoint, environ=environ, resolver=resolver,
    )
    return {**record, "ai_log_id": row_id, "action": detail}
