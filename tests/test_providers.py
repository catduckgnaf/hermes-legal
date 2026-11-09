import json
from datetime import date

import pytest

from hermes_legal import cli, db, doctor, matters, providers
from hermes_legal.providers import (
    PROVIDERS,
    TIERS,
    BlockedProviderError,
    PrivacyViolationError,
    Provider,
    allowed,
    allowed_providers,
    build_preview,
    export_ai_log,
    find_provider,
    is_stale,
    list_ai_log,
    log_ai_use,
    require_allowed,
    route,
    route_and_log,
    stale_providers,
    terms_age_days,
    validate_ceiling,
)

CEILINGS = ("LOCAL_ONLY", "ZERO_RETENTION", "STANDARD")
FRESH = date(2026, 11, 10)   # one day after every catalog terms check
STALE = date(2027, 6, 1)     # well past the 90 day staleness limit


def by(name):
    return next(p for p in PROVIDERS if p.name.startswith(name))


def blocked_providers():
    return [p for p in PROVIDERS if p.tier == "BLOCKED"]


# --- Original catalog behavior (kept) --------------------------------------

def test_local_always_allowed():
    assert allowed(by("Local (llama"), "LOCAL_ONLY")

def test_consumer_chat_blocked_even_at_standard():
    assert not allowed(by("Consumer chat"), "STANDARD")

def test_standard_provider_refused_for_local_only_matter():
    assert not allowed(by("OpenAI API (paid)"), "LOCAL_ONLY")

def test_zdr_allowed_at_zdr_ceiling():
    assert allowed(by("AWS Bedrock"), "ZERO_RETENTION")

def test_no_provider_trains_except_blocked():
    assert all((not p.trains_on_data) or p.tier == "BLOCKED" for p in PROVIDERS)


# --- Catalog integrity: every entry carries a terms-checked date -----------

def test_every_provider_carries_a_valid_terms_checked_date():
    for provider in PROVIDERS:
        assert provider.tier in TIERS
        # Construction already validates, but pin the catalog itself.
        assert provider.terms_checked_date.isoformat() == provider.terms_checked

def test_provider_without_terms_date_is_rejected():
    with pytest.raises(ValueError):
        Provider("No date", "STANDARD", False, "30 days", "")

def test_provider_with_malformed_terms_date_is_rejected():
    with pytest.raises(ValueError):
        Provider("Bad date", "STANDARD", False, "30 days", "last Tuesday")

def test_provider_with_unknown_tier_is_rejected():
    with pytest.raises(ValueError):
        Provider("Bad tier", "FREE_FOR_ALL", False, "none", "2026-11-09")


# --- Ceiling validation fails closed ----------------------------------------

def test_blocked_is_not_a_valid_ceiling():
    with pytest.raises(ValueError):
        validate_ceiling("BLOCKED")

def test_unknown_ceiling_fails_closed_everywhere():
    with pytest.raises(ValueError):
        allowed(by("Local (llama"), "EVERYTHING")
    with pytest.raises(ValueError):
        route("EVERYTHING")
    with pytest.raises(ValueError):
        allowed_providers("")


# --- The router: selection and refusal --------------------------------------

def test_router_default_never_leaves_the_device():
    for ceiling in CEILINGS:
        assert route(ceiling).tier == "LOCAL_ONLY"

def test_router_returns_requested_provider_at_or_below_ceiling():
    assert route("ZERO_RETENTION", "AWS Bedrock") is by("AWS Bedrock")
    assert route("STANDARD", by("OpenAI API (paid)")) is by("OpenAI API (paid)")
    assert route("LOCAL_ONLY", "Local (LM Studio)") is by("Local (LM Studio)")

@pytest.mark.parametrize("ceiling", CEILINGS)
@pytest.mark.parametrize("name", ["Anthropic API (paid", "OpenAI API (paid)"])
def test_router_raises_for_standard_provider_on_local_only_matter(name, ceiling):
    if ceiling == "STANDARD":
        assert route(ceiling, name) is by(name)
    elif ceiling == "LOCAL_ONLY":
        with pytest.raises(PrivacyViolationError):
            route(ceiling, name)

def test_router_raises_for_zdr_provider_on_local_only_matter():
    with pytest.raises(PrivacyViolationError):
        route("LOCAL_ONLY", "AWS Bedrock")
    with pytest.raises(PrivacyViolationError):
        require_allowed(by("AWS Bedrock"), "LOCAL_ONLY")

def test_find_provider_rejects_unknown_and_ambiguous_names():
    with pytest.raises(ValueError):
        find_provider("Some Invented Cloud")
    with pytest.raises(ValueError):
        find_provider("OpenAI API")  # matches both the ZDR and paid entries


# --- BLOCKED cannot be bypassed ---------------------------------------------

@pytest.mark.parametrize("ceiling", CEILINGS)
@pytest.mark.parametrize("provider", blocked_providers(), ids=lambda p: p.name)
def test_blocked_tier_refused_at_every_ceiling(provider, ceiling):
    assert not allowed(provider, ceiling)
    assert provider not in allowed_providers(ceiling)
    with pytest.raises(BlockedProviderError):
        require_allowed(provider, ceiling)
    with pytest.raises(BlockedProviderError):
        route(ceiling, provider)
    with pytest.raises(BlockedProviderError):
        route(ceiling, provider.name)

@pytest.mark.parametrize("ceiling", CEILINGS)
def test_blocked_lookup_by_lowercase_name_is_still_blocked(ceiling):
    with pytest.raises(BlockedProviderError):
        route(ceiling, "consumer chat (free / plus / pro personal accounts)")
    with pytest.raises(BlockedProviderError):
        route(ceiling, "google ai studio free tier")

def test_blocked_name_with_forged_local_tier_is_still_blocked():
    forged = Provider(
        "Consumer chat (free / Plus / Pro personal accounts)",
        "LOCAL_ONLY", False, "none", "2026-11-09",
    )
    with pytest.raises(BlockedProviderError):
        route("STANDARD", forged)

def test_training_provider_is_blocked_whatever_tier_it_claims():
    sneaky = Provider("Helpful Cloud", "LOCAL_ONLY", True, "forever", "2026-11-09")
    assert not allowed(sneaky, "LOCAL_ONLY")
    with pytest.raises(BlockedProviderError):
        require_allowed(sneaky, "STANDARD")

def test_allowed_providers_matrix_counts():
    assert len(allowed_providers("LOCAL_ONLY")) == 2
    assert len(allowed_providers("ZERO_RETENTION")) == 7
    # STANDARD without allowlist mode excludes OpenRouter.
    assert len(allowed_providers("STANDARD")) == 9
    assert len(allowed_providers("STANDARD", zero_retention_allowlist=True)) == 10
    for ceiling in CEILINGS:
        assert all(p.tier != "BLOCKED" for p in allowed_providers(ceiling))


# --- OpenRouter only in zero-retention allowlist mode ------------------------

def test_openrouter_requires_allowlist_mode():
    openrouter = by("OpenRouter")
    assert not allowed(openrouter, "STANDARD")
    with pytest.raises(PrivacyViolationError):
        route("STANDARD", openrouter)
    assert allowed(openrouter, "STANDARD", zero_retention_allowlist=True)
    assert route("STANDARD", openrouter, zero_retention_allowlist=True) is openrouter


# --- Terms freshness ----------------------------------------------------------

def test_terms_age_and_staleness():
    provider = by("AWS Bedrock")
    assert terms_age_days(provider, FRESH) == 1
    assert not is_stale(provider, FRESH)
    assert is_stale(provider, STALE)

def test_stale_providers_are_cloud_only():
    stale = stale_providers(STALE)
    assert stale and all(p.tier != "LOCAL_ONLY" for p in stale)
    assert stale_providers(FRESH) == []


# --- Pre-send preview ---------------------------------------------------------

def test_preview_for_local_send_leaves_nothing():
    preview = build_preview(
        "Local (llama.cpp / Ollama)", "LOCAL_ONLY",
        files=["complaint.docx"],
        chunks=[{"file": "complaint.docx", "text": "hello world"}],
        model="Qwen3 8B",
    )
    assert preview.leaves_device is False
    assert preview.badge.startswith("[LOCAL_ONLY]")
    assert preview.file_list == ["complaint.docx"]
    assert preview.chunk_count == 1 and preview.total_chars == len("hello world")
    rendered = preview.render()
    assert "Local (llama.cpp / Ollama)" in rendered
    assert "complaint.docx" in rendered and "nothing leaves the device" in rendered
    assert preview.to_dict()["tier"] == "LOCAL_ONLY"

def test_preview_for_cloud_send_names_provider_tier_and_files():
    preview = build_preview(
        "AWS Bedrock", "ZERO_RETENTION",
        chunks=[("memo.docx", "privileged text"), ("memo.docx", "more text")],
    )
    assert preview.leaves_device is True
    assert preview.chunk_count == 2
    assert preview.file_list == ["memo.docx"]
    assert "ZERO_RETENTION" in preview.render()

def test_preview_refuses_blocked_and_over_ceiling_sends():
    with pytest.raises(BlockedProviderError):
        build_preview("Consumer chat", "STANDARD", chunks=["secret"])
    with pytest.raises(PrivacyViolationError):
        build_preview("OpenAI API (paid)", "LOCAL_ONLY", chunks=["secret"])


# --- Per-matter AI log ---------------------------------------------------------

def _matter(tmp_path, ceiling=None):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"; folder.mkdir()
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    if ceiling:
        conn.execute("UPDATE matters SET privacy_ceiling=? WHERE id=?", (ceiling, mid))
        conn.commit()
    return conn, mid

def test_ai_log_records_provider_tier_model_action_and_time(tmp_path):
    conn, mid = _matter(tmp_path)
    row_id = log_ai_use(conn, mid, by("Local (llama"), "draft summary", model="Qwen3 8B")
    rows = list_ai_log(conn, mid)
    assert len(rows) == 1 and rows[0]["id"] == row_id
    assert rows[0]["provider"].startswith("Local (llama")
    assert rows[0]["tier"] == "LOCAL_ONLY"
    assert rows[0]["model"] == "Qwen3 8B"
    assert rows[0]["action"] == "draft summary"
    assert rows[0]["created_at"]  # timestamp default filled in

def test_ai_log_refuses_over_ceiling_and_blocked_without_writing(tmp_path):
    conn, mid = _matter(tmp_path)  # LOCAL_ONLY by default
    with pytest.raises(PrivacyViolationError):
        log_ai_use(conn, mid, by("OpenAI API (paid)"), "draft")
    with pytest.raises(BlockedProviderError):
        log_ai_use(conn, mid, by("Consumer chat"), "draft")
    assert list_ai_log(conn, mid) == []

def test_route_and_log_uses_the_stored_matter_ceiling(tmp_path):
    conn, mid = _matter(tmp_path, ceiling="ZERO_RETENTION")
    provider = route_and_log(conn, mid, "AWS Bedrock", action="research memo", model="Qwen3 32B")
    assert provider is by("AWS Bedrock")
    assert list_ai_log(conn, mid)[0]["tier"] == "ZERO_RETENTION"
    with pytest.raises(PrivacyViolationError):
        route_and_log(conn, mid, "OpenAI API (paid)", action="draft")
    assert len(list_ai_log(conn, mid)) == 1  # the refused call wrote nothing

def test_ai_log_is_exportable_as_json_and_csv(tmp_path):
    conn, mid = _matter(tmp_path)
    log_ai_use(conn, mid, by("Local (LM Studio)"), "intake summary", model="Qwen3 8B")
    exported = json.loads(export_ai_log(conn, mid))
    assert exported[0]["action"] == "intake summary"
    csv_text = export_ai_log(conn, mid, format="csv")
    assert csv_text.splitlines()[0] == "id,matter_id,provider,tier,model,action,created_at"
    assert "intake summary" in csv_text
    with pytest.raises(ValueError):
        export_ai_log(conn, mid, format="xml")


# --- Doctor privacy warnings ---------------------------------------------------

def test_doctor_warns_on_stale_terms_for_cloud_providers():
    warnings = doctor.privacy_warnings(STALE)
    assert warnings
    assert any("AWS Bedrock" in w and "2026-11-09" in w for w in warnings)
    assert not any("Local (llama" in w for w in warnings)  # local terms do not go stale
    assert doctor.privacy_warnings(FRESH) == []

def test_doctor_warns_on_standard_provider_for_local_only_matter():
    warnings = doctor.privacy_warnings(
        FRESH, selected_provider="OpenAI API (paid)", matter_ceiling="LOCAL_ONLY"
    )
    assert len(warnings) == 1 and "STANDARD" in warnings[0] and "LOCAL_ONLY" in warnings[0]
    assert doctor.privacy_warnings(
        FRESH, selected_provider="Local (llama.cpp / Ollama)", matter_ceiling="LOCAL_ONLY"
    ) == []
    assert doctor.privacy_warnings(
        FRESH, selected_provider="OpenAI API (paid)", matter_ceiling="STANDARD"
    ) == []

def test_doctor_warns_on_blocked_selection():
    warnings = doctor.privacy_warnings(
        FRESH, selected_provider="Consumer chat", matter_ceiling="STANDARD"
    )
    assert len(warnings) == 1 and "BLOCKED" in warnings[0]

def test_doctor_run_appends_warn_lines_without_counting_them_missing():
    lines, _ = doctor.run(STALE)
    assert any(line.startswith("warn") and "AWS Bedrock" in line for line in lines)
    lines, _ = doctor.run(FRESH)
    assert not any(line.startswith("warn") for line in lines)


# --- CLI: legal models shows the tiers -----------------------------------------

def test_cli_models_shows_tiers_providers_and_local_models(capsys):
    assert cli.main(["models"]) == 0
    out = capsys.readouterr().out
    for tier in TIERS:
        assert tier in out
    assert "Qwen3 8B" in out and "Qwen3 32B" in out  # 16 GB and 24 GB VRAM catalog rows
    assert "terms checked: 2026-11-09" in out

def test_cli_models_json_and_ceiling_filter(capsys):
    assert cli.main(["models", "--json", "--ceiling", "LOCAL_ONLY"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ceiling"] == "LOCAL_ONLY"
    assert data["providers"] and all(p["tier"] == "LOCAL_ONLY" for p in data["providers"])
    assert all(p["terms_checked"] for p in data["providers"])
    assert cli.main(["models", "--json"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert {p["tier"] for p in full["providers"]} == set(TIERS)


# --- Demo matter: local end to end, networking conceptually off ----------------

def test_demo_matter_runs_locally_end_to_end(tmp_path):
    conn, mid = _matter(tmp_path)  # default ceiling is LOCAL_ONLY
    provider = route_and_log(conn, mid, action="intake summary", model="Qwen3 8B")
    preview = build_preview(
        provider, "LOCAL_ONLY", files=["intake.md"],
        chunks=[{"file": "intake.md", "text": "fictional intake"}],
        model="Qwen3 8B",
    )
    assert preview.leaves_device is False
    assert list_ai_log(conn, mid)[0]["provider"] == provider.name


def test_uncataloged_provider_claiming_local_only_is_refused():
    import pytest
    from hermes_legal.providers import PrivacyViolationError, Provider, route
    invented = Provider("Totally Local Trust Me", "LOCAL_ONLY", False, "none", "2026-11-09")
    with pytest.raises(PrivacyViolationError, match="not in the provider catalog"):
        route("LOCAL_ONLY", invented)
