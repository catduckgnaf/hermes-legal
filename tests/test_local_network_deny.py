"""Network-deny tests around the real local path (issue #24).

The earlier network-deny tests used a client double, so they proved the
router and the log made no connection but never exercised the real HTTP
client. These run the real ``LocalModelClient`` against a stub server on
loopback while every connection to a non-loopback address fails the
test, and they pin the connect-time check that closes the gap between
"the URL was checked" and "the socket was opened".

All matter content here is fictional.
"""
from __future__ import annotations

import hashlib
import http.server
import ipaddress
import json
import socket
import threading

import pytest

from hermes_legal import db, local_model, matters, providers
from hermes_legal.providers import PrivacyViolationError, is_local_endpoint, list_ai_log


class _StubHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        self.server.bodies.append(self.rfile.read(length))
        body = json.dumps({"choices": [{"message": {"content": "The lease ends in June."}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def stub_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _StubHandler)
    server.bodies = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def deny_non_loopback(monkeypatch):
    """Fail the test on any socket connect to a non-loopback address."""
    attempts = []
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = str(address[0]).split("%")[0]
        attempts.append(host)
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise AssertionError(f"non-loopback connection attempted on the local path: {address!r}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return attempts


def _matter(tmp_path):
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "note.txt").write_text("The lease ends in June.", encoding="utf-8")
    conn = db.connect(tmp_path / "legal.db")
    return conn, matters.open_folder_as_matter(conn, folder, "Demo")


def test_real_local_ask_only_connects_to_loopback(tmp_path, stub_server, deny_non_loopback, monkeypatch):
    # A proxy setting must not pull the request off the device either.
    monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.9:3128")
    monkeypatch.setenv("http_proxy", "http://203.0.113.9:3128")
    conn, mid = _matter(tmp_path)
    url = f"http://127.0.0.1:{stub_server.server_address[1]}/v1"
    outcome = local_model.ask_matter(
        conn, mid, "When does the lease end?", model="qwen3:8b",
        client=local_model.LocalModelClient(url),
    )
    assert outcome["answer"] == "The lease ends in June."
    assert deny_non_loopback and all(ipaddress.ip_address(h).is_loopback for h in deny_non_loopback)
    # The bytes the server received are the bytes hashed into the log.
    assert len(stub_server.bodies) == 1
    record = outcome["sent_payload"]
    assert record["sent_sha256"] == hashlib.sha256(stub_server.bodies[0]).hexdigest()
    assert record["endpoint"] == url
    row = list_ai_log(conn, mid)[-1]
    assert f"sent_sha256={record['sent_sha256']}" in row["action"]
    assert f"preview_sha256={record['preview_sha256']}" in row["action"]
    assert f"endpoint={url}" in row["action"]


def test_name_that_rebinds_after_the_check_is_refused_before_connecting(tmp_path, stub_server, deny_non_loopback, monkeypatch):
    """The URL passes the build-time check, then the name moves off the device."""
    conn, mid = _matter(tmp_path)
    port = stub_server.server_address[1]
    client = local_model.LocalModelClient(f"http://localhost:{port}/v1")
    real_getaddrinfo = socket.getaddrinfo

    def rebound(host, *args, **kwargs):
        if host == "localhost":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.7", port))]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebound)
    body = local_model.LocalModelClient.build_body("qwen3:8b", "sys", "user")
    with pytest.raises(local_model.LocalEndpointError, match="not a loopback"):
        client.chat_payload(body)
    assert deny_non_loopback == []
    assert stub_server.bodies == []
    # The full Ask path refuses too, and writes no log row for a send that
    # did not happen.
    with pytest.raises((PrivacyViolationError, local_model.LocalEndpointError)):
        local_model.ask_matter(conn, mid, "lease", model="qwen3:8b", client=client)
    assert stub_server.bodies == []
    assert list_ai_log(conn, mid) == []


def test_mixed_resolution_at_connect_time_is_refused(stub_server, deny_non_loopback, monkeypatch):
    port = stub_server.server_address[1]
    client = local_model.LocalModelClient(f"http://localhost:{port}/v1")

    def mixed(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.4", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    with pytest.raises(local_model.LocalEndpointError):
        client.chat_payload(local_model.LocalModelClient.build_body("qwen3:8b", "s", "u"))
    assert deny_non_loopback == []
    assert stub_server.bodies == []


@pytest.mark.parametrize("url", [
    "http://0.0.0.0:11434/v1",
    "http://[::]:11434/v1",
    "http://[::ffff:203.0.113.7]:11434/v1",
    "http://127.0.0.1@203.0.113.7:11434/v1",
    "http://127.0.0.1.example.com:11434/v1",
])
def test_client_refuses_unspecified_and_disguised_addresses(url):
    with pytest.raises(local_model.LocalEndpointError):
        local_model.LocalModelClient(url)
    assert not is_local_endpoint(url, resolver=lambda host: ["203.0.113.7"])


def test_client_accepts_ipv6_loopback_literal():
    assert local_model.LocalModelClient("http://[::1]:11434/v1").base_url == "http://[::1]:11434/v1"
    assert is_local_endpoint("http://[::1]:11434/v1")


def test_localhost_name_is_resolved_not_trusted_by_the_router():
    """A hosts file can point ``localhost`` at another machine."""
    assert is_local_endpoint("http://localhost:11434", resolver=lambda host: ["127.0.0.1", "::1"])
    assert not is_local_endpoint("http://localhost:11434", resolver=lambda host: ["10.0.0.5"])
    assert not is_local_endpoint("http://app.localhost:11434", resolver=lambda host: ["127.0.0.1", "10.0.0.5"])

    def unresolvable(host):
        raise OSError("no such host")

    assert not is_local_endpoint("http://localhost:11434", resolver=unresolvable)
    with pytest.raises(PrivacyViolationError):
        providers.route("LOCAL_ONLY", "Local (llama.cpp / Ollama)",
                        environ={"OLLAMA_HOST": "localhost:11434"}, resolver=lambda host: ["192.0.2.10"])


def test_sent_payload_log_refuses_a_remote_endpoint_without_writing(tmp_path):
    conn, mid = _matter(tmp_path)
    provider = providers.route("LOCAL_ONLY", environ={})
    preview = providers.build_preview(provider, "LOCAL_ONLY", chunks=["fictional intake"], model="qwen3:8b", environ={})
    with pytest.raises(PrivacyViolationError):
        providers.log_sent_payload(conn, mid, preview, b"{}", chunks=["fictional intake"],
                                   endpoint="http://203.0.113.7:11434/v1")
    assert list_ai_log(conn, mid) == []


def test_ask_refuses_a_client_whose_endpoint_is_not_loopback(tmp_path):
    conn, mid = _matter(tmp_path)

    class RemoteClient:
        base_url = "http://203.0.113.7:11434/v1"

        def chat_payload(self, body, expected_sha256=None):  # pragma: no cover - must not be reached
            raise AssertionError("a remote endpoint must be refused before sending")

    with pytest.raises(PrivacyViolationError, match="loopback"):
        local_model.ask_matter(conn, mid, "lease", model="qwen3:8b", client=RemoteClient())
    assert list_ai_log(conn, mid) == []


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "llama3.1:cloud", "qwen3-cloud", "Kimi:CLOUD"])
def test_local_client_refuses_every_cloud_tag_the_router_refuses(model):
    assert providers.is_cloud_routed_model(model)
    with pytest.raises(local_model.LocalEndpointError):
        local_model.require_local_model(model)
