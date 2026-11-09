"""Issue #24: a LOCAL_ONLY tier must be verified local, not just labeled.

These tests pin three things:

- a LOCAL_ONLY provider is routed only when its endpoint resolves to
  loopback (an ``OLLAMA_HOST`` or explicit endpoint pointing at another
  machine is refused, as is a name that does not resolve to loopback);
- a cloud-routed model tag (Ollama ``:cloud`` / ``-cloud``) is refused
  for a LOCAL_ONLY provider, in routing, preview and the AI log;
- raising a matter ceiling records who raised it and the client consent
  behind it, persisted in the database.
"""
import socket

import pytest

from hermes_legal import db, matters, providers
from hermes_legal.providers import (
    PrivacyViolationError,
    build_preview,
    is_cloud_routed_model,
    is_local_endpoint,
    list_ai_log,
    log_ai_use,
    provider_endpoint,
    require_allowed,
    route,
)

OLLAMA = "Local (llama.cpp / Ollama)"
LM_STUDIO = "Local (LM Studio)"


def by(name):
    return next(p for p in providers.PROVIDERS if p.name.startswith(name))


# --- Endpoint parsing and loopback checks -----------------------------------

@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:11434",
    "http://127.5.0.9:11434",
    "127.0.0.1:11434",
    "http://localhost:11434",
    "http://localhost.:1234/v1",
    "http://[::1]:11434",
])
def test_loopback_endpoints_are_local(endpoint):
    assert is_local_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", [
    "http://192.168.1.20:11434",
    "http://10.0.0.5:11434",
    "http://8.8.8.8:11434",
    "http://0.0.0.0:11434",
    "https://example.com:11434",
    "",
    "http://",
])
def test_non_loopback_or_missing_endpoints_are_not_local(endpoint):
    def resolver(host):
        return ["93.184.216.34"]

    assert not is_local_endpoint(endpoint, resolver=resolver)


def test_hostname_resolving_only_to_loopback_is_local():
    assert is_local_endpoint(
        "http://mybox.lan:11434", resolver=lambda host: ["127.0.0.1"]
    )


def test_hostname_resolving_to_a_public_address_is_not_local():
    assert not is_local_endpoint(
        "http://mybox.lan:11434", resolver=lambda host: ["203.0.113.7"]
    )


def test_hostname_resolving_to_mixed_addresses_is_not_local():
    assert not is_local_endpoint(
        "http://mybox.lan:11434",
        resolver=lambda host: ["127.0.0.1", "203.0.113.7"],
    )


def test_unresolvable_hostname_is_not_local():
    def boom(host):
        raise OSError("name does not resolve")

    assert not is_local_endpoint("http://gone.lan:11434", resolver=boom)
    assert not is_local_endpoint(
        "http://gone.lan:11434", resolver=lambda host: []
    )


def test_catalog_local_providers_carry_loopback_default_endpoints():
    for provider in providers.PROVIDERS:
        if provider.tier == "LOCAL_ONLY":
            endpoint = provider_endpoint(provider, environ={})
            assert endpoint, provider.name
            assert is_local_endpoint(endpoint)


# --- Routing enforcement ------------------------------------------------------

def test_route_refuses_local_provider_with_remote_explicit_endpoint():
    with pytest.raises(PrivacyViolationError, match="loopback|local"):
        route("LOCAL_ONLY", OLLAMA, endpoint="http://192.168.1.20:11434",
              environ={})
    with pytest.raises(PrivacyViolationError):
        require_allowed(by("Local (llama"), "LOCAL_ONLY",
                        endpoint="https://example.com:11434", environ={})


def test_route_accepts_local_provider_with_loopback_explicit_endpoint():
    provider = route("LOCAL_ONLY", OLLAMA, endpoint="http://127.0.0.1:9999",
                     environ={})
    assert provider is by("Local (llama")


def test_ollama_host_environment_is_honored_but_validated():
    remote = {"OLLAMA_HOST": "192.168.1.20:11434"}
    with pytest.raises(PrivacyViolationError):
        route("LOCAL_ONLY", OLLAMA, environ=remote)
    local = {"OLLAMA_HOST": "localhost:11434"}
    assert route("LOCAL_ONLY", OLLAMA, environ=local) is by("Local (llama")
    assert provider_endpoint(by("Local (llama"), environ=local) == "localhost:11434"


def test_route_refuses_local_provider_with_unresolvable_endpoint():
    def boom(host):
        raise OSError("no such host")

    with pytest.raises(PrivacyViolationError):
        route("LOCAL_ONLY", LM_STUDIO, endpoint="http://gone.lan:1234/v1",
              environ={}, resolver=boom)


def test_local_route_makes_no_network_connection(monkeypatch):
    """Network-deny: verifying a literal loopback endpoint needs no network."""

    def denied(*args, **kwargs):
        raise AssertionError("network connection attempted on the local path")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    provider = route("LOCAL_ONLY", OLLAMA, environ={})
    preview = build_preview(provider, "LOCAL_ONLY", model="Qwen3 8B",
                            chunks=["fictional intake"], environ={})
    assert preview.leaves_device is False


def test_cli_models_json_shows_local_endpoints(capsys):
    import json

    from hermes_legal import cli

    assert cli.main(["models", "--json", "--ceiling", "LOCAL_ONLY"]) == 0
    data = json.loads(capsys.readouterr().out)
    endpoints = {p["name"]: p["endpoint"] for p in data["providers"]}
    assert endpoints[OLLAMA].startswith("http://127.0.0.1")
    assert endpoints[LM_STUDIO].startswith("http://127.0.0.1")


# --- Cloud-routed model tags ----------------------------------------------------

@pytest.mark.parametrize("model", [
    "llama3.1:cloud",
    "gpt-oss:120b-cloud",
    "qwen3-cloud",
])
def test_cloud_routed_model_tags_are_detected(model):
    assert is_cloud_routed_model(model)


@pytest.mark.parametrize("model", ["", "Qwen3 8B", "qwen3:32b", "llama3.3:70b"])
def test_ordinary_local_model_tags_are_not_cloud_routed(model):
    assert not is_cloud_routed_model(model)


def test_route_and_preview_refuse_cloud_model_for_local_provider():
    with pytest.raises(PrivacyViolationError, match="cloud"):
        route("LOCAL_ONLY", OLLAMA, model="gpt-oss:120b-cloud", environ={})
    with pytest.raises(PrivacyViolationError, match="cloud"):
        build_preview(OLLAMA, "LOCAL_ONLY", model="llama3.1:cloud",
                      chunks=["secret"], environ={})


def test_cloud_tag_check_is_scoped_to_local_providers():
    preview = build_preview("AWS Bedrock", "ZERO_RETENTION",
                            model="some-model:cloud", chunks=["memo"])
    assert preview.leaves_device is True


# --- AI log enforcement ---------------------------------------------------------

def _matter(tmp_path, ceiling=None):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"
    folder.mkdir()
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    if ceiling:
        conn.execute(
            "UPDATE matters SET privacy_ceiling=? WHERE id=?", (ceiling, mid)
        )
        conn.commit()
    return conn, mid


def test_ai_log_refuses_remote_endpoint_and_cloud_model_without_writing(tmp_path):
    conn, mid = _matter(tmp_path)
    with pytest.raises(PrivacyViolationError):
        log_ai_use(conn, mid, by("Local (llama"), "draft",
                   endpoint="http://192.168.1.20:11434", environ={})
    with pytest.raises(PrivacyViolationError):
        log_ai_use(conn, mid, by("Local (llama"), "draft",
                   model="llama3.1:cloud", environ={})
    assert list_ai_log(conn, mid) == []


def test_ai_log_accepts_verified_local_call(tmp_path):
    conn, mid = _matter(tmp_path)
    log_ai_use(conn, mid, by("Local (llama"), "draft", model="Qwen3 8B",
               endpoint="http://127.0.0.1:11434", environ={})
    rows = list_ai_log(conn, mid)
    assert len(rows) == 1 and rows[0]["tier"] == "LOCAL_ONLY"


# --- Ceiling-raise record ---------------------------------------------------------

def test_raise_matter_ceiling_records_who_and_consent(tmp_path):
    conn, mid = _matter(tmp_path)
    record_id = matters.raise_matter_ceiling(
        conn, mid, "ZERO_RETENTION",
        raised_by="matter operator",
        consent_note="Client consented in writing on 2026-11-09.",
    )
    assert matters.get_matter(conn, mid)["privacy_ceiling"] == "ZERO_RETENTION"
    records = matters.list_ceiling_raises(conn, mid)
    assert len(records) == 1 and records[0]["id"] == record_id
    assert records[0]["previous_ceiling"] == "LOCAL_ONLY"
    assert records[0]["new_ceiling"] == "ZERO_RETENTION"
    assert records[0]["raised_by"] == "matter operator"
    assert records[0]["consent_note"] == "Client consented in writing on 2026-11-09."
    assert records[0]["created_at"]


def test_raise_matter_ceiling_requires_who_and_consent(tmp_path):
    conn, mid = _matter(tmp_path)
    with pytest.raises(ValueError):
        matters.raise_matter_ceiling(
            conn, mid, "ZERO_RETENTION", raised_by="", consent_note="consent"
        )
    with pytest.raises(ValueError):
        matters.raise_matter_ceiling(
            conn, mid, "ZERO_RETENTION", raised_by="operator", consent_note=" "
        )
    assert matters.get_matter(conn, mid)["privacy_ceiling"] == "LOCAL_ONLY"
    assert matters.list_ceiling_raises(conn, mid) == []


def test_raise_matter_ceiling_refuses_lower_equal_unknown_and_missing(tmp_path):
    conn, mid = _matter(tmp_path)
    with pytest.raises(ValueError):
        matters.raise_matter_ceiling(
            conn, mid, "LOCAL_ONLY", raised_by="op", consent_note="consent"
        )
    with pytest.raises(ValueError):
        matters.raise_matter_ceiling(
            conn, mid, "BLOCKED", raised_by="op", consent_note="consent"
        )
    with pytest.raises(ValueError):
        matters.raise_matter_ceiling(
            conn, 9999, "STANDARD", raised_by="op", consent_note="consent"
        )
    assert matters.list_ceiling_raises(conn, mid) == []
