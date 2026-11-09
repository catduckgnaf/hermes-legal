"""DocuSign connector: envelope creation is a pending action only.

Building an envelope draft performs no network call and sends nothing.
Only approving the pending action POSTs the envelope, and the payload
is explicit about its status: this connector never sets a ``sent``
status silently — the human approval is the send decision.

Documenso and DocuSeal are the open, self-hostable alternatives named
in issue #8. They expose a different REST shape, so they are recorded
as known alternatives here rather than emulated through the DocuSign
client; a dedicated client is follow-up work.
"""
from __future__ import annotations

from .base import BaseConnector, DataFlowLabel
from .oauth import OAuthConfig

DOCUSIGN_DEMO_BASE = "https://demo.docusign.net/restapi/v2.1"
DOCUSIGN_PROD_BASE = "https://na4.docusign.net/restapi/v2.1"
OPEN_ALTERNATIVES = ("Documenso", "DocuSeal")


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


class DocuSignConnector(BaseConnector):
    name = "docusign"
    read_only = False  # Writes exist, but only as approved pending actions (see create_envelope).
    data_flow = DataFlowLabel(
        destination="DocuSign (docusign.net)",
        data_sent="envelope documents and signer names/email addresses, only after human approval",
        data_received="envelope status and completion metadata",
    )

    def __init__(self, transport, credentials=None, *, oauth: OAuthConfig | None = None,
                 account_id: str = "", base_url: str = DOCUSIGN_DEMO_BASE, **kwargs):
        super().__init__(transport, credentials, **kwargs)
        self.oauth = oauth
        self.account_id = account_id
        self.base_url = base_url.rstrip("/")

    def required_credentials(self):
        return ("access_token",)

    # -- reads --------------------------------------------------------------
    def list_envelopes(self, matter_id=None, **params):
        self.require_enabled(matter_id)
        if not self.account_id:
            raise RuntimeError("docusign: account_id is not configured")
        data = self._get_json(f"{self.base_url}/accounts/{self.account_id}/envelopes", params=params or None)
        return data.get("envelopes", []) if isinstance(data, dict) else (data or [])

    def get_envelope_status(self, envelope_id: str, matter_id=None):
        self.require_enabled(matter_id)
        data = self._get_json(f"{self.base_url}/accounts/{self.account_id}/envelopes/{envelope_id}")
        return data.get("status") if isinstance(data, dict) else None

    # -- writes: pending action only; creating the draft sends nothing -------
    def create_envelope(self, subject: str, signers: list[dict], documents: list[dict],
                        *, send: bool = True):
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
            if not self.account_id:
                raise RuntimeError("docusign: account_id is not configured")
            resp = self.transport.request(
                "POST", f"{self.base_url}/accounts/{self.account_id}/envelopes",
                headers=self.bearer_headers(), json_body=action.payload)
            if not resp.ok:
                raise RuntimeError(f"docusign: create envelope failed with HTTP {resp.status}")
            return resp.data

        summary = (f"Send DocuSign envelope '{subject}' to "
                   + ", ".join(s.get("email", "?") for s in signers)) if send else \
                  (f"Create DocuSign draft envelope '{subject}'")
        return self.queue_write("create_envelope", summary, payload, execute)
