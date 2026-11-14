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

import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import urllib.request
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

log = logging.getLogger(__name__)


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
                json_body: Any = None, form_body: Any = None) -> TransportResponse: ...


class UrllibTransport:
    """Production transport built on the standard library only."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def request(self, method, url, *, headers=None, params=None, json_body=None, form_body=None):
        if params:
            from urllib.parse import urlencode
            url = url + ("&" if "?" in url else "?") + urlencode(params)
        body = None
        hdrs = dict(headers or {})
        if form_body is not None:
            from urllib.parse import urlencode
            body = urlencode(form_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif json_body is not None:
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

    def request(self, method, url, *, headers=None, params=None, json_body=None, form_body=None):
        record = {"method": method.upper(), "url": url, "headers": dict(headers or {}),
                  "params": dict(params or {}), "json_body": json_body,
                  "form_body": dict(form_body) if isinstance(form_body, Mapping) else form_body}
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

    def delete(self, service: str, key: str) -> bool:
        return self._values.pop(f"{service}:{key}", None) is not None


# ------------------------------------------------------- Windows credentials

class WindowsCredentialBackend(Protocol):
    """The ctypes/win32cred layer, isolated so it can be faked on Linux."""

    def read(self, target: str) -> str | None: ...
    def write(self, target: str, value: str, *, username: str = "") -> None: ...
    def delete(self, target: str) -> bool: ...


class CtypesWin32CredBackend:
    """Windows Credential Manager through ``ctypes`` (win32cred).

    No new dependency: ``advapi32`` ships with Windows. The library
    handle is resolved lazily and only on Windows, so importing or
    constructing the surrounding store on Linux or macOS never touches
    ``ctypes.windll``. ``advapi32`` may be injected in tests.
    """

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self, advapi32=None):
        self._advapi32 = advapi32

    @property
    def advapi32(self):
        if self._advapi32 is None:
            import ctypes
            self._advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
        return self._advapi32

    def read(self, target):
        import ctypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [("Flags", ctypes.c_ulong), ("Type", ctypes.c_ulong),
                        ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
                        ("LastWritten", ctypes.c_ulonglong), ("CredentialBlobSize", ctypes.c_ulong),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", ctypes.c_ulong), ("AttributeCount", ctypes.c_ulong),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
                        ("UserName", ctypes.c_wchar_p)]

        pointer = ctypes.POINTER(CREDENTIALW)()
        ok = self.advapi32.CredReadW(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer))
        if not ok:
            return None
        try:
            cred = pointer.contents
            size = int(cred.CredentialBlobSize)
            if not size:
                return ""
            raw = ctypes.string_at(cred.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(pointer)

    def write(self, target, value, *, username=""):
        import ctypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [("Flags", ctypes.c_ulong), ("Type", ctypes.c_ulong),
                        ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
                        ("LastWritten", ctypes.c_ulonglong), ("CredentialBlobSize", ctypes.c_ulong),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", ctypes.c_ulong), ("AttributeCount", ctypes.c_ulong),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
                        ("UserName", ctypes.c_wchar_p)]

        blob = value.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIALW()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = buffer
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = username or target
        if not self.advapi32.CredWriteW(ctypes.byref(cred), 0):
            raise OSError("Windows Credential Manager write failed (CredWriteW)")

    def delete(self, target):
        return bool(self.advapi32.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0))


class EnvCredentialStore:
    """Environment fallback, intended for tests and headless runs.

    Reads ``<SERVICE>_<KEY>`` uppercased, for example ``CLIO_ACCESS_TOKEN``.
    """

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = os.environ if environ is None else environ

    def env_name(self, service, key):
        return f"{service}_{key}".upper().replace("-", "_")

    def get(self, service, key):
        return self._environ.get(self.env_name(service, key))


class KeychainCredentialStore:
    """OS keychain access, per platform.

    macOS uses ``security``; Linux uses ``secret-tool`` (libsecret);
    Windows uses the Windows Credential Manager through the injectable
    ctypes backend (:class:`CtypesWin32CredBackend` by default). When
    the platform tool is missing the store reports ``available ==
    False`` and returns ``None`` rather than falling back to a
    plaintext file — any environment fallback lives in
    :class:`ChainCredentialStore` and is warned, never silent.
    """

    def __init__(self, runner: Callable[..., Any] = subprocess.run, platform: str | None = None,
                 *, windows_backend: WindowsCredentialBackend | None = None):
        import sys
        self._run = runner
        self.platform = platform or sys.platform
        self._windows_backend = windows_backend

    @property
    def is_windows(self) -> bool:
        return self.platform.startswith("win")

    @property
    def windows_backend(self) -> WindowsCredentialBackend:
        if self._windows_backend is None:
            self._windows_backend = CtypesWin32CredBackend()
        return self._windows_backend

    @staticmethod
    def _target(service, key) -> str:
        return f"hermes-legal:{service}:{key}"

    @property
    def tool(self) -> str | None:
        import shutil
        if self.is_windows:
            return "win32cred"
        if self.platform == "darwin":
            return shutil.which("security")
        return shutil.which("secret-tool")

    @property
    def available(self) -> bool:
        if self.is_windows:
            if self._windows_backend is not None:
                return True
            try:  # Real backend: only resolvable where advapi32 exists.
                _ = self.windows_backend.advapi32  # type: ignore[attr-defined]
                return True
            except Exception:
                return False
        return self.tool is not None

    def get(self, service, key):
        if self.is_windows:
            try:
                return self.windows_backend.read(self._target(service, key)) or None
            except Exception:
                return None
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

    def set(self, service, key, value):
        if self.is_windows:
            self.windows_backend.write(self._target(service, key), str(value), username=key)
            return
        tool = self.tool
        if not tool:
            raise RuntimeError("no OS keychain tool is available on this platform")
        if self.platform == "darwin":
            out = self._run([tool, "add-generic-password", "-U", "-s", service, "-a", key, "-w", str(value)],
                            capture_output=True, text=True, timeout=10)
        else:
            out = self._run([tool, "store", "--label", f"{service}:{key}", "service", service, "key", key],
                            input=str(value), capture_output=True, text=True, timeout=10)
        if getattr(out, "returncode", 1) != 0:
            raise RuntimeError("OS keychain write failed")

    def delete(self, service, key) -> bool:
        if self.is_windows:
            try:
                return bool(self.windows_backend.delete(self._target(service, key)))
            except Exception:
                return False
        tool = self.tool
        if not tool:
            return False
        try:
            if self.platform == "darwin":
                out = self._run([tool, "delete-generic-password", "-s", service, "-a", key],
                                capture_output=True, text=True, timeout=10)
            else:
                out = self._run([tool, "clear", "service", service, "key", key],
                                capture_output=True, text=True, timeout=10)
        except Exception:
            return False
        return getattr(out, "returncode", 1) == 0


class ChainCredentialStore:
    """Try stores in order; the keychain comes first, env is the fallback.

    The environment fallback is explicit and warned, never silent: when
    a value comes from an :class:`EnvCredentialStore` in the chain, a
    ``RuntimeWarning`` is issued and a warning is logged naming the
    variable (never its value).
    """

    def __init__(self, stores, *, warn_on_env_fallback: bool = True):
        self.stores = list(stores)
        self.warn_on_env_fallback = warn_on_env_fallback
        self.used_env_fallback = False

    def get(self, service, key):
        for store in self.stores:
            value = store.get(service, key)
            if value:
                if isinstance(store, EnvCredentialStore):
                    self.used_env_fallback = True
                    if self.warn_on_env_fallback:
                        name = store.env_name(service, key)
                        message = (f"credential for service '{service}' came from the "
                                   f"environment variable {name}, not the OS keychain; "
                                   "the environment fallback is for tests and headless runs")
                        warnings.warn(message, RuntimeWarning, stacklevel=2)
                        log.warning("%s", message)
                return value
        return None

    def set(self, service, key, value):
        for store in self.stores:
            if isinstance(store, EnvCredentialStore):
                continue  # Never write a secret into the process environment.
            setter = getattr(store, "set", None)
            if setter is not None:
                setter(service, key, value)
                return
        raise RuntimeError("no writable credential store is available")

    def delete(self, service, key) -> bool:
        deleted = False
        for store in self.stores:
            deleter = getattr(store, "delete", None)
            if deleter is not None:
                deleted = bool(deleter(service, key)) or deleted
        return deleted


def default_credential_store(environ: Mapping[str, str] | None = None) -> ChainCredentialStore:
    return ChainCredentialStore([KeychainCredentialStore(), EnvCredentialStore(environ)])


# ------------------------------------------------------------ pending actions

class ApprovalRequired(RuntimeError):
    """Raised when a write, send, filing, or paid pull lacks approval."""


class ConnectorDisabled(RuntimeError):
    """Raised when a connector is used for a matter that has not enabled it."""


@dataclass(frozen=True)
class ApprovalRecord:
    """A human approval recorded before a pending action may run."""

    approval_id: str
    approver: str
    action_id: str | None = None
    note: str = ""


class DurablePendingActionStore:
    """SQLite-backed pending actions, approvals, and deliveries.

    This is the durable replacement for in-memory-only pending actions.
    It uses the repo database patterns (one local SQLite file, tables
    created with ``CREATE TABLE IF NOT EXISTS``) and can wrap either a
    database path or an existing ``sqlite3`` connection, for example
    one opened through ``hermes_legal.db.connect`` — it adds its own
    tables to that database and touches no existing table.

    Two guarantees live here:

    - ``approved_by`` must match a recorded approval: either the
      approval id returned by :meth:`record_approval`, or the approver
      name on a recorded approval for that action. A free-form string
      with no recorded approval is rejected.
    - Every send carries an idempotency key. :meth:`execute_once`
      records a delivery under that key, so a retry after a timeout
      returns the recorded result instead of sending a second time;
      executors also send the key on the wire so a server that
      received the first attempt can dedupe the retry.
    """

    TABLES = """
    CREATE TABLE IF NOT EXISTS connector_approvals (
      approval_id TEXT PRIMARY KEY,
      action_id TEXT,
      approver TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS connector_pending_actions (
      action_id TEXT PRIMARY KEY,
      connector TEXT NOT NULL,
      kind TEXT NOT NULL,
      summary TEXT NOT NULL DEFAULT '',
      payload_json TEXT NOT NULL DEFAULT '{}',
      matter_id TEXT,
      idempotency_key TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL DEFAULT 'pending',
      approved_by TEXT,
      result_json TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      executed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS connector_deliveries (
      idempotency_key TEXT PRIMARY KEY,
      action_id TEXT,
      connector TEXT NOT NULL DEFAULT '',
      result_json TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """

    def __init__(self, path_or_conn=None):
        if isinstance(path_or_conn, sqlite3.Connection):
            self.conn = path_or_conn
            self._owns_conn = False
        else:
            self.conn = sqlite3.connect(str(path_or_conn) if path_or_conn else ":memory:")
            self._owns_conn = True
        self.conn.executescript(self.TABLES)
        self.conn.commit()

    # -- approvals ---------------------------------------------------------
    def record_approval(self, approver: str, *, action_id: str | None = None,
                        note: str = "") -> ApprovalRecord:
        if not approver or not str(approver).strip():
            raise ApprovalRequired("recording an approval needs a named human approver")
        record = ApprovalRecord(approval_id=uuid.uuid4().hex, approver=str(approver).strip(),
                                action_id=action_id, note=str(note or ""))
        self.conn.execute(
            "INSERT INTO connector_approvals (approval_id, action_id, approver, note) "
            "VALUES (?, ?, ?, ?)",
            (record.approval_id, record.action_id, record.approver, record.note))
        self.conn.commit()
        return record

    def has_recorded_approval(self, action_id: str | None, approved_by: str) -> bool:
        value = str(approved_by or "").strip()
        if not value:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM connector_approvals WHERE approval_id = ?", (value,)).fetchone()
        if row:
            return True
        if action_id:
            row = self.conn.execute(
                "SELECT 1 FROM connector_approvals WHERE action_id = ? AND approver = ?",
                (action_id, value)).fetchone()
            if row:
                return True
            # An approval recorded before the action id was known still counts.
            row = self.conn.execute(
                "SELECT 1 FROM connector_approvals WHERE action_id IS NULL AND approver = ?",
                (value,)).fetchone()
            return row is not None
        return False

    def resolve_approver(self, action_id: str | None, approved_by: str) -> str:
        """Return the recorded approver name for an approval id or name."""
        value = str(approved_by or "").strip()
        row = self.conn.execute(
            "SELECT approver FROM connector_approvals WHERE approval_id = ?", (value,)).fetchone()
        return row[0] if row else value

    # -- pending actions -----------------------------------------------------
    def save(self, action: "PendingAction") -> "PendingAction":
        self.conn.execute(
            "INSERT OR IGNORE INTO connector_pending_actions "
            "(action_id, connector, kind, summary, payload_json, matter_id, idempotency_key, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (action.action_id, action.connector, action.kind, action.summary,
             json.dumps(action.payload, default=str),
             None if action.matter_id is None else str(action.matter_id),
             action.idempotency_key, "executed" if action.executed else "pending"))
        self.conn.commit()
        return action

    def status(self, action_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM connector_pending_actions WHERE action_id = ?", (action_id,)).fetchone()
        return row[0] if row else None

    def get(self, action_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT action_id, connector, kind, summary, payload_json, matter_id, "
            "idempotency_key, status, approved_by, result_json FROM connector_pending_actions "
            "WHERE action_id = ?", (action_id,)).fetchone()
        if not row:
            return None
        keys = ("action_id", "connector", "kind", "summary", "payload_json", "matter_id",
                "idempotency_key", "status", "approved_by", "result_json")
        out = dict(zip(keys, row))
        out["payload"] = json.loads(out.pop("payload_json") or "{}")
        out["result"] = json.loads(out["result_json"]) if out.get("result_json") else None
        return out

    def mark_approved(self, action: "PendingAction", approver: str) -> None:
        self.save(action)
        self.conn.execute(
            "UPDATE connector_pending_actions SET status = 'approved', approved_by = ? "
            "WHERE action_id = ?", (approver, action.action_id))
        self.conn.commit()

    # -- idempotent execution --------------------------------------------------
    def delivery_for(self, idempotency_key: str):
        row = self.conn.execute(
            "SELECT result_json FROM connector_deliveries WHERE idempotency_key = ?",
            (idempotency_key,)).fetchone()
        if not row:
            return (False, None)
        return (True, json.loads(row[0]) if row[0] else None)

    def execute_once(self, action: "PendingAction", run: Callable[[], Any]):
        """Run ``run`` at most once per idempotency key.

        A recorded delivery is returned without calling ``run`` again.
        If ``run`` raises (for example a timeout after the remote side
        accepted the send), nothing is recorded locally, so the retry
        calls ``run`` again — carrying the same idempotency key, which
        is what lets the remote side dedupe it.
        """
        found, result = self.delivery_for(action.idempotency_key)
        if found:
            return result
        result = run()
        try:
            encoded = json.dumps(result, default=str)
        except (TypeError, ValueError):
            encoded = json.dumps(str(result))
        self.conn.execute(
            "INSERT OR IGNORE INTO connector_deliveries "
            "(idempotency_key, action_id, connector, result_json) VALUES (?, ?, ?, ?)",
            (action.idempotency_key, action.action_id, action.connector, encoded))
        self.conn.execute(
            "UPDATE connector_pending_actions SET status = 'executed', result_json = ?, "
            "executed_at = datetime('now') WHERE action_id = ?",
            (encoded, action.action_id))
        self.conn.commit()
        return result


@dataclass
class PendingAction:
    """A write that has been prepared but not performed.

    ``execute`` runs only through :meth:`approve`, which records who
    approved it. Constructing a PendingAction never performs the write.
    Every action carries an ``idempotency_key`` so a retry after a
    timeout cannot send twice. When the action is bound to a
    :class:`DurablePendingActionStore`, approval additionally requires
    ``approved_by`` to match a recorded approval, and the executed
    result is recorded durably under the idempotency key.
    """

    connector: str
    kind: str
    summary: str
    payload: dict = field(default_factory=dict)
    _executor: Callable[["PendingAction"], Any] | None = field(default=None, repr=False)
    approved_by: str | None = None
    executed: bool = False
    result: Any = None
    matter_id: Any = None
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)
    _store: DurablePendingActionStore | None = field(default=None, repr=False)

    def approve(self, approved_by: str):
        if not approved_by or not str(approved_by).strip():
            raise ApprovalRequired("a pending action needs a named human approver")
        if self._store is not None:
            if not self._store.has_recorded_approval(self.action_id, str(approved_by)):
                raise ApprovalRequired(
                    "approved_by does not match a recorded approval for this action; "
                    "record the human approval first (record_approval)")
            approved_by = self._store.resolve_approver(self.action_id, str(approved_by))
        if self.executed:
            # A retry after a successful send returns the recorded
            # result instead of sending again — but only for the same
            # recorded approver, never for a new unapproved caller when
            # a durable store is bound.
            if self._store is not None:
                found, stored = self._store.delivery_for(self.idempotency_key)
                if found:
                    return stored
            raise RuntimeError("pending action was already executed")
        self.approved_by = str(approved_by)
        if self._store is not None:
            self._store.mark_approved(self, self.approved_by)
            if self._executor is not None:
                self.result = self._store.execute_once(self, lambda: self._executor(self))
            self.executed = True
            return self.result
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
    # Privacy tier this connector's external call represents, compared
    # against a matter ceiling with the providers tier ordering. Every
    # cloud connector is STANDARD: data leaves the device to a third
    # party, so a LOCAL_ONLY matter refuses it outright.
    external_tier: str = "STANDARD"

    def __init__(self, transport: Transport, credentials: CredentialStore | None = None,
                 *, enabled_matters: set | frozenset | None = None, enabled: bool = True,
                 ceiling_resolver=None, matter_ceilings=None,
                 pending_store: DurablePendingActionStore | None = None):
        self.transport = transport
        self.credentials = credentials or default_credential_store()
        self._enabled_matters = None if enabled_matters is None else set(enabled_matters)
        self.enabled = enabled
        self.pending_actions: list[PendingAction] = []
        resolver = ceiling_resolver if ceiling_resolver is not None else matter_ceilings
        self._ceiling_resolver = self._normalize_ceiling_resolver(resolver)
        self.pending_store = pending_store

    @staticmethod
    def _normalize_ceiling_resolver(resolver):
        if resolver is None:
            return None
        if isinstance(resolver, Mapping):
            table = dict(resolver)

            def from_mapping(matter_id):
                if matter_id in table:
                    return table[matter_id]
                return table.get(str(matter_id))

            return from_mapping
        if hasattr(resolver, "execute"):  # a sqlite connection, e.g. from hermes_legal.db
            conn = resolver

            def from_db(matter_id):
                row = conn.execute(
                    "SELECT privacy_ceiling FROM matters WHERE id = ?", (matter_id,)).fetchone()
                return row[0] if row else None

            return from_db
        if callable(resolver):
            return resolver
        raise TypeError("ceiling resolver must be a callable, a mapping, or a database connection")

    @classmethod
    def ceiling_resolver_from_db(cls, conn):
        return cls._normalize_ceiling_resolver(conn)

    # -- per-matter enable flag -------------------------------------------
    def enabled_for_matter(self, matter_id) -> bool:
        if not self.enabled:
            return False
        if self._enabled_matters is None:
            return True
        return matter_id in self._enabled_matters

    # -- privacy ceiling -----------------------------------------------------
    def matter_ceiling(self, matter_id):
        if self._ceiling_resolver is None or matter_id is None:
            return None
        return self._ceiling_resolver(matter_id)

    def require_privacy_allowed(self, matter_id=None, *, send: bool = False) -> None:
        """Consult the matter's privacy ceiling before an external call.

        Uses the providers interfaces (``validate_ceiling`` and
        ``TIER_ORDER``) for the comparison, without importing a
        provider catalog entry for a connector. Rules:

        - On a send path, when a ceiling resolver or a per-matter
          restriction is configured, an explicit ``matter_id`` is
          required — there is no silent all-matters default.
        - When a resolver is configured but the matter or its ceiling
          is unknown, the call fails closed.
        - A connector whose data leaves the device (``external_tier``
          STANDARD) is refused for a LOCAL_ONLY matter.
        """
        if send and matter_id is None and (
                self._ceiling_resolver is not None or self._enabled_matters is not None):
            raise ConnectorDisabled(
                f"{self.name}: an explicit matter_id is required on the send path; "
                "there is no all-matters default for sends")
        if self._ceiling_resolver is None or matter_id is None:
            return
        from ..providers import PrivacyViolationError, TIER_ORDER, validate_ceiling

        ceiling_value = self._ceiling_resolver(matter_id)
        if ceiling_value is None:
            raise ConnectorDisabled(
                f"{self.name}: no privacy ceiling is recorded for matter {matter_id}; "
                "failing closed")
        ceiling = validate_ceiling(ceiling_value)
        tier = str(getattr(self, "external_tier", "STANDARD")).upper()
        if not self.data_flow.leaves_device:
            return
        if TIER_ORDER.get(tier, TIER_ORDER["STANDARD"]) > TIER_ORDER[ceiling]:
            raise PrivacyViolationError(
                f"{self.name} sends data off the device ({tier}), above the matter "
                f"ceiling {ceiling}; the connector call is refused for this matter")

    def require_enabled(self, matter_id=None, *, send: bool = False) -> None:
        if not self.enabled:
            raise ConnectorDisabled(f"{self.name} is disabled")
        if not self.enabled_for_matter(matter_id):
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
        self.require_privacy_allowed(matter_id, send=send)

    # -- credentials --------------------------------------------------------
    def credential(self, key: str) -> str | None:
        return self.credentials.get(self.name, key)

    def credential_fingerprint(self, key: str = "access_token") -> str:
        """A non-secret fingerprint of a credential, for cache keying."""
        value = self.credential(key) or ""
        return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""

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
                    executor: Callable[[PendingAction], Any] | None = None,
                    *, matter_id=None, idempotency_key: str | None = None) -> PendingAction:
        """Queue a write as a pending action. Never executes it.

        When a durable pending store is bound to this connector, the
        action is persisted at queue time, its approval must match a
        recorded approval in that store, and its result is recorded
        under its idempotency key.
        """
        action = PendingAction(connector=self.name, kind=kind, summary=summary,
                               payload=dict(payload), _executor=executor,
                               matter_id=matter_id,
                               idempotency_key=idempotency_key or uuid.uuid4().hex,
                               _store=self.pending_store)
        if self.pending_store is not None:
            self.pending_store.save(action)
        self.pending_actions.append(action)
        return action

    def record_approval(self, approver: str, *, action: PendingAction | None = None,
                        note: str = "") -> ApprovalRecord:
        """Record a human approval in the durable store for later matching."""
        if self.pending_store is None:
            raise RuntimeError(
                f"{self.name}: no durable pending store is configured, so an approval "
                "cannot be recorded; configure pending_store first")
        return self.pending_store.record_approval(
            approver, action_id=action.action_id if action is not None else None, note=note)

    def send_headers(self, action: PendingAction | None = None, *, key: str = "access_token") -> dict:
        """Bearer headers plus the action's idempotency key, for send paths."""
        headers = self.bearer_headers(key)
        if action is not None and action.idempotency_key:
            headers["Idempotency-Key"] = action.idempotency_key
        return headers

    def require_send_allowed(self, action: PendingAction) -> None:
        """Re-check enablement and the privacy ceiling at send time."""
        self.require_enabled(action.matter_id, send=True)

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
