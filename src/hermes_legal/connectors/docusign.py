"""DocuSign connector: envelope creation is a pending action only.

Building an envelope draft performs no network call and sends nothing.
Only approving the pending action POSTs the envelope, and the payload
is explicit about its status: this connector never sets a ``sent``
status silently — the human approval is the send decision.

The API host is not hard-coded. :meth:`DocuSignConnector.discover_account`
calls the account (userinfo) endpoint for the current credential,
reads the default account's ``base_uri`` and ``account_id`` from the
response, and caches the result per credential. A configured
``base_url`` is only a fallback for an explicitly configured account
or a self-hosted, base-URL-configured compatible target.

Documenso and DocuSeal are the open, self-hostable alternatives named
in issue #8. A self-hosted target that accepts a DocuSign-shaped
envelope payload can be configured cheaply through
:meth:`DocuSignConnector.self_hosted`, which relabels the data flow
and doctor output for that target; a native Documenso or DocuSeal
client for their own REST shapes remains follow-up work.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .base import BaseConnector, DataFlowLabel, DoctorResult
from .oauth import OAuthConfig

DOCUSIGN_DEMO_BASE = "https://demo.docusign.net/restapi/v2.1"
DOCUSIGN_PROD_BASE = "https://na4.docusign.net/restapi/v2.1"
OPEN_ALTERNATIVES = ("Documenso", "DocuSeal")
SELF_HOSTED_PROVIDERS = ("Documenso", "DocuSeal", "compatible")


def docusign_oauth(client_id: str, redirect_uri: str = "http://127.0.0.1:8765/oauth/callback",
                   *, demo: bool = True) -> OAuthConfig:
    host = "account-d.docusign.com" if demo else "account.docusign.com"
    return OAuthConfig(
        client_id=client_id,
        authorize_url=f"https://{host}/oauth/auth",
        token_url=f"https://{host}/oauth/token",
        scopes=("signature",),
        redirect_uri=redirect_uri,
    )


@dataclass(frozen=True)
class DocuSignAccount:
    account_id: str
    base_url: str
    account_name: str = ""
    is_default: bool = False


def _api_base(base_uri: str) -> str:
    base = str(base_uri or "").rstrip("/")
    if not base:
        raise RuntimeError("docusign: account discovery returned no base_uri")
    if "/restapi" in base:
        return base
    return base + "/restapi/v2.1"


class DocuSignConnector(BaseConnector):
    name = "docusign"
    read_only = False  # Writes exist, but only as approved pending actions (see create_envelope).
    data_flow = DataFlowLabel(
        destination="DocuSign (docusign.net)",
        data_sent="envelope documents and signer names/email addresses, only after human approval",
        data_received="envelope status and completion metadata",
    )

    def __init__(self, transport, credentials=None, *, oauth: OAuthConfig | None = None,
                 account_id: str = "", base_url: str = DOCUSIGN_DEMO_BASE,
                 userinfo_url: str | None = None, self_hosted_provider: str | None = None,
                 **kwargs):
        super().__init__(transport, credentials, **kwargs)
        self.oauth = oauth
        self.account_id = account_id
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.userinfo_url = userinfo_url
        self.self_hosted_provider = self_hosted_provider
        self._account_cache: dict[str, DocuSignAccount] = {}
        self.account: DocuSignAccount | None = None
        if self_hosted_provider:
            self.data_flow = DataFlowLabel(
                destination=f"{self_hosted_provider} (self-hosted, at {self.base_url})",
                data_sent="envelope documents and signer names/email addresses, only after human approval, to the configured self-hosted target only",
                data_received="envelope status and completion metadata from the self-hosted target",
            )
            # A loopback self-hosted target does not leave the device;
            # a remote self-hosted target still does.
            from ..providers import is_local_endpoint
            self.external_tier = "LOCAL_ONLY" if is_local_endpoint(self.base_url) else "STANDARD"

    @classmethod
    def self_hosted(cls, transport, credentials=None, *, base_url: str,
                    provider: str = "DocuSeal", account_id: str = "self-hosted", **kwargs):
        """Configure a base-URL self-hosted signing target (Documenso/DocuSeal).

        The target is addressed purely by its configured ``base_url``;
        no DocuSign cloud host is contacted, and the doctor check and
        data-flow label name the self-hosted provider instead.
        """
        if provider not in SELF_HOSTED_PROVIDERS:
            raise ValueError(f"unknown self-hosted signing provider {provider!r}; "
                             f"expected one of {SELF_HOSTED_PROVIDERS}")
        if not base_url:
            raise ValueError("a self-hosted signing target needs an explicit base_url")
        return cls(transport, credentials, account_id=account_id, base_url=base_url,
                   self_hosted_provider=provider, **kwargs)

    def required_credentials(self):
        return ("access_token",)

    def doctor(self) -> DoctorResult:
        result = super().doctor()
        if self.self_hosted_provider and result.status == "ok":
            return DoctorResult(
                self.name, "ok",
                f"self-hosted {self.self_hosted_provider} target at {self.base_url}; "
                + self.data_flow.describe())
        return result

    # -- account discovery ----------------------------------------------------
    def _userinfo_url(self) -> str:
        if self.userinfo_url:
            return self.userinfo_url
        if self.oauth is not None:
            host = urlparse(self.oauth.authorize_url).hostname or "account.docusign.com"
            return f"https://{host}/oauth/userinfo"
        return "https://account.docusign.com/oauth/userinfo"

    def discover_account(self, *, force: bool = False, matter_id=None) -> DocuSignAccount:
        """Resolve account_id and API base URI from the account endpoint.

        The result is cached per credential (keyed by a fingerprint of
        the access token, never the token itself), so repeated calls
        for the same credential make one network request. The default
        account in the response wins; a demo/sandbox account resolves
        to its demo base URI exactly as a production account resolves
        to its own.
        """
        self.require_enabled(matter_id)
        self.require_privacy_allowed(matter_id)
        fingerprint = self.credential_fingerprint()
        if not force and fingerprint in self._account_cache:
            self.account = self._account_cache[fingerprint]
            self.account_id = self.account.account_id
            self.base_url = self.account.base_url
            return self.account
        resp = self.transport.request("GET", self._userinfo_url(), headers=self.bearer_headers())
        if not resp.ok:
            raise RuntimeError(f"docusign: account discovery failed with HTTP {resp.status}")
        data = resp.data if isinstance(resp.data, dict) else {}
        accounts = data.get("accounts") or []
        if not accounts:
            raise RuntimeError("docusign: account discovery returned no accounts")
        chosen = next((a for a in accounts if a.get("is_default")), accounts[0])
        account = DocuSignAccount(
            account_id=str(chosen.get("account_id") or ""),
            base_url=_api_base(str(chosen.get("base_uri") or "")),
            account_name=str(chosen.get("account_name") or ""),
            is_default=bool(chosen.get("is_default")),
        )
        if not account.account_id:
            raise RuntimeError("docusign: account discovery returned no account_id")
        self._account_cache[fingerprint] = account
        self.account = account
        self.account_id = account.account_id
        self.base_url = account.base_url
        return account

    def _require_account(self, matter_id=None) -> str:
        if not self.account_id:
            self.discover_account(matter_id=matter_id)
        if not self.account_id:
            raise RuntimeError("docusign: account_id is not configured and discovery found none")
        return self.account_id

    # -- reads --------------------------------------------------------------
    def list_envelopes(self, matter_id=None, **params):
        self.require_enabled(matter_id)
        account_id = self._require_account(matter_id)
        data = self._get_json(f"{self.base_url}/accounts/{account_id}/envelopes", params=params or None)
        return data.get("envelopes", []) if isinstance(data, dict) else (data or [])

    def get_envelope_status(self, envelope_id: str, matter_id=None):
        self.require_enabled(matter_id)
        account_id = self._require_account(matter_id)
        data = self._get_json(f"{self.base_url}/accounts/{account_id}/envelopes/{envelope_id}")
        return data.get("status") if isinstance(data, dict) else None

    # -- writes: pending action only; creating the draft sends nothing -------
    def create_envelope(self, subject: str, signers: list[dict], documents: list[dict],
                        *, send: bool = True, matter_id=None):
        """Return a PendingAction for an envelope. No network call happens here.

        ``signers`` items carry ``email``, ``name`` and ``recipientId``;
        ``documents`` items carry ``documentBase64``, ``name``,
        ``fileExtension`` and ``documentId``. Approving the returned
        action is the only path that POSTs, with envelope status
        ``sent`` when ``send`` is true or ``created`` (a draft) otherwise.
        """
        if not signers:
            raise ValueError("an envelope needs at least one signer")
        if not documents:
            raise ValueError("an envelope needs at least one document")
        payload = {
            "emailSubject": subject,
            "documents": documents,
            "recipients": {"signers": signers},
            "status": "sent" if send else "created",
        }

        def execute(action):
            self.require_send_allowed(action)
            account_id = self._require_account(action.matter_id)
            resp = self.transport.request(
                "POST", f"{self.base_url}/accounts/{account_id}/envelopes",
                headers=self.send_headers(action), json_body=action.payload)
            if not resp.ok:
                raise RuntimeError(f"docusign: create envelope failed with HTTP {resp.status}")
            return resp.data

        summary = (f"Send DocuSign envelope '{subject}' to "
                   + ", ".join(s.get("email", "?") for s in signers)) if send else \
                  (f"Create DocuSign draft envelope '{subject}'")
        return self.queue_write("create_envelope", summary, payload, execute, matter_id=matter_id)
