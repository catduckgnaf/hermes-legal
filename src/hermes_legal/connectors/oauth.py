"""OAuth 2.0 configuration shape shared by Clio and DocuSign.

Only the shape and the authorization URL builder live here. Token
exchange and refresh are ordinary POSTs through the injectable
transport; no connector in this package runs a browser or a callback
server, and no client secret is ever written to disk by this code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...] = ()
    redirect_uri: str = "http://127.0.0.1:8765/oauth/callback"
    extra_authorize_params: dict = field(default_factory=dict)

    def authorization_url(self, state: str) -> str:
        if not state:
            raise ValueError("OAuth state is required (CSRF protection)")
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        if self.scopes:
            params["scope"] = " ".join(self.scopes)
        params.update(self.extra_authorize_params)
        return f"{self.authorize_url}?{urlencode(params)}"

    def validate(self) -> list[str]:
        problems = []
        if not self.client_id:
            problems.append("client_id is empty")
        for label, url in (("authorize_url", self.authorize_url), ("token_url", self.token_url)):
            if not url.startswith("https://"):
                problems.append(f"{label} must be an https URL")
        return problems


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"

    @classmethod
    def from_response(cls, data: dict) -> "TokenSet":
        if not data or not data.get("access_token"):
            raise ValueError("token response carries no access_token")
        return cls(access_token=data["access_token"],
                   refresh_token=data.get("refresh_token"),
                   expires_in=data.get("expires_in"),
                   token_type=data.get("token_type", "Bearer"))
