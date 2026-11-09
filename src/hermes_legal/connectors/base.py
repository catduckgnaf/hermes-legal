"""Base connector contract shared by every integration.

Rules, enforced here rather than by convention:

- All HTTP goes through an injectable transport, so tests run offline
  against fakes and no test ever touches the network.
- Credentials are read only through a credential store. The production
  store talks to the OS keychain; an environment fallback exists for
  tests and headless runs. No credential value is ever stored on a
  connector instance beyond the request that uses it.
- Connectors are read-only by default. A write is never performed
  inline: it is queued as a :class:`PendingAction` and only an explicit
  human approval may execute it.
- Each connector carries a data-flow label (what leaves the device, to
  whom) and a per-matter enable flag, and ships a doctor check.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol


# ---------------------------------------------------------------- transport

@dataclass(frozen=True)
class TransportResponse:
    status: int
    data: Any = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Transport(Protocol):
    """Minimal HTTP surface every connector depends on."""

    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                params: Mapping[str, Any] | None = None,
                json_body: Any = None) -> TransportResponse: ...


class UrllibTransport:
    """Production transport built on the standard library only."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def request(self, method, url, *, headers=None, params=None, json_body=None):
        if params:
            from urllib.parse import urlencode
            url = url + ("&" if "?" in url else "?") + urlencode(params)
        body = None
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - URLs come from connector config
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            status = exc.code
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        return TransportResponse(status=status, data=data, text=raw)


class FakeTransport:
    """Offline transport for tests and sandbox accounts.

    Handlers are registered per (method, URL prefix). Every request is
    recorded in ``calls`` so a test can prove that no write, send, or
    paid pull happened. An unregistered request raises, so a test can
    never silently reach the network through this object.
    """

    def __init__(self):
        self._handlers: list[tuple[str, str, Callable[..., TransportResponse]]] = []
        self.calls: list[dict] = []

    def add(self, method: str, url_prefix: str, handler):
        """Register ``handler(request_dict) -> TransportResponse | (status, data)``."""
        def wrap(req):
            out = handler(req)
            if isinstance(out, TransportResponse):
                return out
            status, data = out
            return TransportResponse(status=status, data=data, text=json.dumps(data) if data is not None else "")
        self._handlers.append((method.upper(), url_prefix, wrap))
        return self

    def request(self, method, url, *, headers=None, params=None, json_body=None):
        record = {"method": method.upper(), "url": url, "headers": dict(headers or {}),
                  "params": dict(params or {}), "json_body": json_body}
        self.calls.append(record)
        for m, prefix, handler in self._handlers:
            if m == method.upper() and url.startswith(prefix):
                return handler(record)
        raise AssertionError(f"FakeTransport: no handler for {method} {url} (offline tests must register one)")

    def calls_to(self, method: str | None = None, needle: str | None = None):
        out = self.calls
        if method:
            out = [c for c in out if c["method"] == method.upper()]
        if needle:
            out = [c for c in out if needle in c["url"]]
        return out


# --------------------------------------------------------------- credentials

class CredentialStore(Protocol):
    def get(self, service: str, key: str) -> str | None: ...


class MemoryCredentialStore:
    """In-process store for tests and synthetic sandbox accounts."""

    def __init__(self, values: Mapping[str, str] | None = None):
        self._values = dict(values or {})

    def set(self, service: str, key: str, value: str) -> None:
        self._values[f"{service}:{key}"] = value

    def get(self, service, key):
        return self._values.get(f"{service}:{key}")


class EnvCredentialStore:
    """Environment fallback, intended for tests and headless runs.

    Reads ``<SERVICE>_<KEY>`` uppercased, for example ``CLIO_ACCESS_TOKEN``.
    """

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = os.environ if environ is None else environ

    def get(self, service, key):
        return self._environ.get(f"{service}_{key}".upper().replace("-", "_"))


class KeychainCredentialStore:
    """OS keychain access via the platform command-line tool.

    macOS uses ``security``; Linux uses ``secret-tool`` (libsecret).
    When neither tool exists the store reports ``available == False``
    and returns ``None`` rather than falling back to a plaintext file.
    """

    def __init__(self, runner: Callable[..., Any] = subprocess.run, platform: str | None = None):
        import sys
        self._run = runner
        self.platform = platform or sys.platform

    @property
    def tool(self) -> str | None:
        import shutil
        if self.platform == "darwin":
            return shutil.which("security")
        return shutil.which("secret-tool")

    @property
    def available(self) -> bool:
        return self.tool is not None

    def get(self, service, key):
        tool = self.tool
        if not tool:
            return None
        try:
            if self.platform == "darwin":
                out = self._run([tool, "find-generic-password", "-s", service, "-a", key, "-w"],
                                capture_output=True, text=True, timeout=10)
            else:
                out = self._run([tool, "lookup", "service", service, "key", key],
                                capture_output=True, text=True, timeout=10)
        except Exception:
            return None
        if getattr(out, "returncode", 1) != 0:
            return None
        value = (out.stdout or "").strip()
        return value or None


class ChainCredentialStore:
    """Try stores in order; the keychain comes first, env is the fallback."""

    def __init__(self, stores):
        self.stores = list(stores)

    def get(self, service, key):
        for store in self.stores:
            value = store.get(service, key)
            if value:
                return value
        return None


def default_credential_store(environ: Mapping[str, str] | None = None) -> ChainCredentialStore:
    return ChainCredentialStore([KeychainCredentialStore(), EnvCredentialStore(environ)])


# ------------------------------------------------------------ pending actions

class ApprovalRequired(RuntimeError):
    """Raised when a write, send, filing, or paid pull lacks approval."""


class ConnectorDisabled(RuntimeError):
    """Raised when a connector is used for a matter that has not enabled it."""


@dataclass
class PendingAction:
    """A write that has been prepared but not performed.

    ``execute`` runs only through :meth:`approve`, which records who
    approved it. Constructing a PendingAction never performs the write.
    """

    connector: str
    kind: str
    summary: str
    payload: dict = field(default_factory=dict)
    _executor: Callable[["PendingAction"], Any] | None = field(default=None, repr=False)
    approved_by: str | None = None
    executed: bool = False
    result: Any = None

    def approve(self, approved_by: str):
        if not approved_by or not str(approved_by).strip():
            raise ApprovalRequired("a pending action needs a named human approver")
        if self.executed:
            raise RuntimeError("pending action was already executed")
        self.approved_by = str(approved_by)
        if self._executor is not None:
            self.result = self._executor(self)
        self.executed = True
        return self.result


@dataclass(frozen=True)
class DataFlowLabel:
    """What leaves the device, to whom, when this connector is used."""

    destination: str
    data_sent: str
    data_received: str
    leaves_device: bool = True

    def describe(self) -> str:
        if not self.leaves_device:
            return f"Nothing leaves the device. Local destination: {self.destination}."
        return (f"Sends {self.data_sent} to {self.destination}; "
                f"receives {self.data_received}.")


@dataclass(frozen=True)
class DoctorResult:
    name: str
    status: str  # "ok", "missing", "off", "warn"
    detail: str = ""

    def line(self) -> str:
        return f"{self.status:<7} {self.name}" + (f" — {self.detail}" if self.detail else "")


# ------------------------------------------------------------------- base

class BaseConnector:
    """Common contract: doctor check, data-flow label, per-matter flag."""

    name: str = "base"
    data_flow: DataFlowLabel = DataFlowLabel("nowhere", "nothing", "nothing", leaves_device=False)
    read_only: bool = True

    def __init__(self, transport: Transport, credentials: CredentialStore | None = None,
                 *, enabled_matters: set | frozenset | None = None, enabled: bool = True):
        self.transport = transport
        self.credentials = credentials or default_credential_store()
        self._enabled_matters = None if enabled_matters is None else set(enabled_matters)
        self.enabled = enabled
        self.pending_actions: list[PendingAction] = []

    # -- per-matter enable flag -------------------------------------------
    def enabled_for_matter(self, matter_id) -> bool:
        if not self.enabled:
            return False
        if self._enabled_matters is None:
            return True
        return matter_id in self._enabled_matters

    def require_enabled(self, matter_id=None) -> None:
        if not self.enabled:
            raise ConnectorDisabled(f"{self.name} is disabled")
        if self.enabled_for_matter(matter_id):
            return
        if matter_id is None:
            # Fail closed: a restricted connector (enabled_matters is a
            # set) must not silently skip its per-matter check just
            # because the caller supplied no matter. Only an
            # unrestricted connector (enabled_matters=None) allows a
            # call with no matter context.
            raise ConnectorDisabled(
                f"{self.name} is restricted to specific matters; "
                "a matter_id is required")
        raise ConnectorDisabled(f"{self.name} is not enabled for matter {matter_id}")

    # -- credentials --------------------------------------------------------
    def credential(self, key: str) -> str | None:
        return self.credentials.get(self.name, key)

    def require_credential(self, key: str) -> str:
        value = self.credential(key)
        if not value:
            raise RuntimeError(
                f"{self.name}: credential '{key}' is missing; add it to the OS keychain "
                f"(service '{self.name}') — connectors never prompt for or store plaintext secrets")
        return value

    def bearer_headers(self, key: str = "access_token") -> dict:
        return {"Authorization": f"Bearer {self.require_credential(key)}",
                "Accept": "application/json"}

    # -- writes -------------------------------------------------------------
    def queue_write(self, kind: str, summary: str, payload: dict,
                    executor: Callable[[PendingAction], Any] | None = None) -> PendingAction:
        """Queue a write as a pending action. Never executes it."""
        action = PendingAction(connector=self.name, kind=kind, summary=summary,
                               payload=dict(payload), _executor=executor)
        self.pending_actions.append(action)
        return action

    # -- doctor ---------------------------------------------------------------
    def doctor(self) -> DoctorResult:
        if not self.enabled:
            return DoctorResult(self.name, "off", "disabled by setting; off never fails the run")
        missing = [k for k in self.required_credentials() if not self.credential(k)]
        if missing:
            return DoctorResult(self.name, "missing",
                                "add to the OS keychain: " + ", ".join(missing))
        return DoctorResult(self.name, "ok", self.data_flow.describe())

    def required_credentials(self) -> tuple[str, ...]:
        return ("access_token",)

    # -- HTTP helper ------------------------------------------------------------
    def _get_json(self, url: str, *, params=None, headers=None):
        resp = self.transport.request("GET", url, headers=headers or self.bearer_headers(),
                                      params=params)
        if not resp.ok:
            raise RuntimeError(f"{self.name}: GET {url} failed with HTTP {resp.status}")
        return resp.data
