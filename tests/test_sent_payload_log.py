"""Issue #24 remainder: log what was actually sent, tied to the preview.

The AI log used to record routing (and, on the local Ask path, a hash of
the prompt text), but not the exact payload bytes that went to the model.
An auditor could not prove the sent payload was the payload the pre-send
preview approved. These tests pin:

- a hash, byte size and chunk identifiers for the exact payload bytes,
  recorded in the per-matter AI log together with the fingerprint of the
  approved preview;
- fail-closed behavior when the payload to send diverges from the
  preview (different chunks or a different model);
- the local Ask path sending the single payload byte string it hashed
  and logged, end to end under a network deny.

They also sweep the remaining issue #4 acceptance items in this lane's
surface: catalog terms-checked validation, doctor warnings for a
STANDARD provider on a privileged matter, export of the sent-payload
record, and the OpenRouter zero-retention allowlist gate.
"""
import hashlib
import json
import socket
from types import SimpleNamespace

import pytest

from hermes_legal import db, doctor, local_model, matters, providers
from hermes_legal.providers import (
    PrivacyViolationError,
    Provider,
    build_preview,
    export_ai_log,
    list_ai_log,
    log_sent_payload,
    route,
    sent_payload_hash,
    validate_provider_catalog,
    verify_payload_matches_preview,
)

OLLAMA = "Local (llama.cpp / Ollama)"


def _matter(tmp_path, ceiling=None):
    conn = db.connect(tmp_path / "legal.db")
    folder = tmp_path / "matter"
    folder.mkdir()
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    if ceiling:
        conn.execute("UPDATE matters SET privacy_ceiling=? WHERE id=?", (ceiling, mid))
        conn.commit()
    return conn, mid


def _preview(chunks=("fictional intake text",), model="Qwen3 8B"):
    chunk_records = [{"file": "intake.md", "text": text} for text in chunks]
    return build_preview(OLLAMA, "LOCAL_ONLY", chunks=chunk_records, model=model, environ={})


# --- Exact payload hashing ----------------------------------------------------

def test_sent_payload_hash_matches_the_exact_bytes():
    payload = b'{"model": "qwen3:8b", "messages": []}'
    assert sent_payload_hash(payload) == hashlib.sha256(payload).hexdigest()
    assert sent_payload_hash(payload.decode()) == hashlib.sha256(payload).hexdigest()
    # One changed byte is a different payload and a different hash.
    assert sent_payload_hash(payload + b" ") != hashlib.sha256(payload).hexdigest()


def test_preview_chunks_carry_content_hashes_and_preview_has_a_fingerprint():
    preview = _preview()
    chunk = preview.chunks[0]
    assert chunk["sha256"] == hashlib.sha256(b"fictional intake text").hexdigest()
    assert preview.preview_sha256
    assert preview.to_dict()["preview_sha256"] == preview.preview_sha256
    # The fingerprint is stable for the same approved content and changes
    # when the approved content changes.
    assert _preview().preview_sha256 == preview.preview_sha256
    assert _preview(chunks=("different text",)).preview_sha256 != preview.preview_sha256


def test_log_sent_payload_records_hash_size_chunks_and_preview_link(tmp_path):
    conn, mid = _matter(tmp_path)
    preview = _preview()
    payload = local_model.LocalModelClient.build_body(
        "Qwen3 8B", local_model.SYSTEM_PROMPT, "user text"
    )
    record = log_sent_payload(
        conn, mid, preview, payload, action="ask", chunks=[
            {"file": "intake.md", "text": "fictional intake text"}
        ],
    )
    assert record["sent_sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["payload_sha256"] == record["sent_sha256"]
    assert record["sent_bytes"] == len(payload)
    assert record["preview_sha256"] == preview.preview_sha256
    assert record["chunk_count"] == 1
    assert record["chunk_sha256"] == [
        hashlib.sha256(b"fictional intake text").hexdigest()
    ]
    rows = list_ai_log(conn, mid)
    assert len(rows) == 1 and rows[0]["id"] == record["ai_log_id"]
    action = rows[0]["action"]
    assert f"sent_sha256={record['sent_sha256']}" in action
    assert f"preview_sha256={preview.preview_sha256}" in action
    assert f"sent_bytes={len(payload)}" in action
    # The record is exportable with the rest of the per-matter AI log.
    exported = json.loads(export_ai_log(conn, mid))
    assert exported[0]["action"] == action
    csv_text = export_ai_log(conn, mid, format="csv")
    assert record["sent_sha256"] in csv_text


# --- Divergence fails closed ----------------------------------------------------

def test_log_sent_payload_refuses_chunks_that_diverge_from_the_preview(tmp_path):
    conn, mid = _matter(tmp_path)
    preview = _preview()
    payload = b"payload built from other chunks"
    with pytest.raises(PrivacyViolationError, match="preview"):
        log_sent_payload(
            conn, mid, preview, payload, action="ask",
            chunks=[{"file": "intake.md", "text": "swapped privileged text"}],
        )
    with pytest.raises(PrivacyViolationError, match="preview"):
        verify_payload_matches_preview(
            preview, chunks=[{"file": "other.md", "text": "fictional intake text"}]
        )
    assert list_ai_log(conn, mid) == []


def test_log_sent_payload_refuses_a_model_that_diverges_from_the_preview(tmp_path):
    conn, mid = _matter(tmp_path)
    preview = _preview(model="Qwen3 8B")
    with pytest.raises(PrivacyViolationError, match="preview"):
        log_sent_payload(conn, mid, preview, b"payload", action="ask", model="Other 9B")
    assert list_ai_log(conn, mid) == []


def test_client_refuses_a_payload_whose_hash_does_not_match_before_sending():
    opened = []

    class Opener:
        def open(self, request, timeout=None):
            opened.append(request)
            raise AssertionError("a mismatched payload must not be sent")

    client = local_model.LocalModelClient("http://127.0.0.1:11434/v1", opener=Opener())
    body = local_model.LocalModelClient.build_body("qwen3:8b", "sys", "user")
    expected = hashlib.sha256(b"some other payload").hexdigest()
    with pytest.raises(local_model.LocalEndpointError, match="preview|hash|match"):
        client.chat_payload(body, expected_sha256=expected)
    assert opened == []


# --- The local Ask path: sent == approved, end to end offline -------------------

class _CapturingClient:
    """A local-model client double that captures the exact bytes sent."""

    def __init__(self):
        self.bodies = []

    def chat_payload(self, body, expected_sha256=None):
        assert isinstance(body, bytes)
        if expected_sha256 is not None:
            assert hashlib.sha256(body).hexdigest() == expected_sha256
        self.bodies.append(body)
        return "The lease ends in June."

    def chat(self, model, system, user):  # pragma: no cover - must not be used
        raise AssertionError("ask_matter must send the previewed payload bytes")


def test_ask_matter_logs_and_sends_the_same_payload_bytes(tmp_path, monkeypatch):
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "note.txt").write_text("The lease ends in June.", encoding="utf-8")
    conn = db.connect(tmp_path / "legal.db")
    mid = matters.open_folder_as_matter(conn, folder, "Demo")
    client = _CapturingClient()

    def denied(*args, **kwargs):
        raise AssertionError("network connection attempted on the local Ask path")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)

    outcome = local_model.ask_matter(
        conn, mid, "When does the lease end?", model="qwen3:8b", client=client
    )
    assert len(client.bodies) == 1
    sent = client.bodies[0]
    record = outcome["sent_payload"]
    assert record["sent_sha256"] == hashlib.sha256(sent).hexdigest()
    assert record["sent_bytes"] == len(sent)
    assert record["preview_sha256"] == outcome["preview"]["preview_sha256"]
    # The wire payload really is the chat body for this model and question.
    wire = json.loads(sent.decode("utf-8"))
    assert wire["model"] == "qwen3:8b"
    assert "lease ends in June" in wire["messages"][1]["content"]
    rows = list_ai_log(conn, mid)
    assert len(rows) == 1
    assert f"sent_sha256={record['sent_sha256']}" in rows[0]["action"]
    assert f"preview_sha256={record['preview_sha256']}" in rows[0]["action"]
    assert "prompt_sha256=" in rows[0]["action"]


# --- Issue #4 sweep ---------------------------------------------------------------

@pytest.mark.parametrize("bad_date", ["", None, "last Tuesday", "2026-13-40"])
def test_provider_entry_without_a_valid_terms_date_is_rejected(bad_date):
    with pytest.raises(ValueError):
        Provider("No valid date", "STANDARD", False, "30 days", bad_date)


def test_catalog_validation_passes_for_the_catalog_and_names_bad_entries():
    assert validate_provider_catalog()  # the shipped catalog is complete
    bad = SimpleNamespace(name="Invented Cloud", tier="STANDARD", terms_checked="")
    with pytest.raises(ValueError, match="Invented Cloud"):
        validate_provider_catalog([bad])
    missing = SimpleNamespace(name="Dateless Cloud", tier="STANDARD")
    with pytest.raises(ValueError, match="Dateless Cloud"):
        validate_provider_catalog([missing])


def test_doctor_warns_on_standard_provider_for_privileged_matters():
    from datetime import date

    fresh = date(2026, 11, 10)
    for ceiling in ("LOCAL_ONLY", "ZERO_RETENTION"):
        warnings = doctor.privacy_warnings(
            fresh, selected_provider="OpenAI API (paid)", matter_ceiling=ceiling
        )
        assert len(warnings) == 1
        assert "STANDARD" in warnings[0] and ceiling in warnings[0]
    assert doctor.privacy_warnings(
        fresh, selected_provider="OpenAI API (paid)", matter_ceiling="STANDARD"
    ) == []


def test_openrouter_allowlist_mode_still_respects_the_ceiling():
    openrouter = next(p for p in providers.PROVIDERS if p.name.startswith("OpenRouter"))
    # Allowlist mode does not lift the ceiling: STANDARD stays refused
    # for LOCAL_ONLY and ZERO_RETENTION matters even with the mode on.
    for ceiling in ("LOCAL_ONLY", "ZERO_RETENTION"):
        with pytest.raises(PrivacyViolationError):
            route(ceiling, openrouter, zero_retention_allowlist=True)
    with pytest.raises(PrivacyViolationError):
        route("STANDARD", openrouter)
    assert route("STANDARD", openrouter, zero_retention_allowlist=True) is openrouter
