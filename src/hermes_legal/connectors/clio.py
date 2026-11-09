"""Clio connector: public REST API v4, OAuth 2.0, read-first.

Reads (matters, contacts, calendar entries, bills) run directly.
Every write is queued as a pending action; approving the action is
what performs the POST, and nothing here sends on its own.
"""
from __future__ import annotations

from .base import BaseConnector, DataFlowLabel
from .oauth import OAuthConfig

CLIO_BASE = "https://app.clio.com/api/v4"
CLIO_SANDBOX_BASE = "https://app.clio.com/api/v4"  # Clio uses a developer/sandbox account on the same host.


def clio_oauth(client_id: str, redirect_uri: str = "http://127.0.0.1:8765/oauth/callback") -> OAuthConfig:
    return OAuthConfig(
        client_id=client_id,
        authorize_url="https://app.clio.com/oauth/authorize",
        token_url="https://app.clio.com/oauth/token",
        scopes=(),
        redirect_uri=redirect_uri,
    )


class ClioConnector(BaseConnector):
    name = "clio"
    data_flow = DataFlowLabel(
        destination="Clio (app.clio.com)",
        data_sent="matter, contact, calendar, and billing queries for enabled matters",
        data_received="matter, contact, calendar, and billing records",
    )

    def __init__(self, transport, credentials=None, *, oauth: OAuthConfig | None = None,
                 base_url: str = CLIO_BASE, **kwargs):
        super().__init__(transport, credentials, **kwargs)
        self.oauth = oauth
        self.base_url = base_url.rstrip("/")

    # -- reads --------------------------------------------------------------
    def _list(self, path: str, matter_id=None, **params):
        self.require_enabled(matter_id)
        data = self._get_json(f"{self.base_url}/{path}", params=params or None)
        if isinstance(data, dict):
            return data.get("data", [])
        return data or []

    def list_matters(self, matter_id=None, **params):
        return self._list("matters.json", matter_id=matter_id, **params)

    def get_matter(self, clio_matter_id, matter_id=None):
        self.require_enabled(matter_id)
        data = self._get_json(f"{self.base_url}/matters/{clio_matter_id}.json")
        return data.get("data", data) if isinstance(data, dict) else data

    def list_contacts(self, matter_id=None, **params):
        return self._list("contacts.json", matter_id=matter_id, **params)

    def list_calendar_entries(self, matter_id=None, **params):
        return self._list("calendar_entries.json", matter_id=matter_id, **params)

    def list_bills(self, matter_id=None, **params):
        return self._list("bills.json", matter_id=matter_id, **params)

    # -- writes: pending actions only -----------------------------------------
    def create_matter(self, description: str, **fields):
        payload = {"data": {"description": description, **fields}}

        def execute(action):
            resp = self.transport.request("POST", f"{self.base_url}/matters.json",
                                          headers=self.bearer_headers(), json_body=action.payload)
            if not resp.ok:
                raise RuntimeError(f"clio: create matter failed with HTTP {resp.status}")
            return resp.data

        return self.queue_write("create_matter", f"Create Clio matter: {description}", payload, execute)

    def create_contact(self, first_name: str, last_name: str, **fields):
        payload = {"data": {"first_name": first_name, "last_name": last_name, "type": "Person", **fields}}

        def execute(action):
            resp = self.transport.request("POST", f"{self.base_url}/contacts.json",
                                          headers=self.bearer_headers(), json_body=action.payload)
            if not resp.ok:
                raise RuntimeError(f"clio: create contact failed with HTTP {resp.status}")
            return resp.data

        return self.queue_write("create_contact", f"Create Clio contact: {first_name} {last_name}", payload, execute)
