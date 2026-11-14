"""OAuth 2.0 for the connectors: config, PKCE, exchange, and refresh.

The authorization URL builder, the code exchange, and the refresh
grant all live here and all run through an injectable transport, so
tests exercise the full flow offline against fixtures and no code in
this package runs a browser or a callback server. No client secret or
token is ever written to disk by this code; a caller may hand the
returned :class:`TokenSet` to a credential store explicitly.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlencode


class OAuthError(RuntimeError):
    """A token endpoint returned an OAuth error response."""

    def __init__(self, error: str, description: str = "", status: int | None = None):
        self.error = error
        self.description = description
        self.status = status
        message = f"OAuth error: {error}"
        if description:
            message += f" — {description}"
        if status is not None:
            message += f" (HTTP {status})"
        super().__init__(message)


def generate_code_verifier(length: int = 64) -> str:
    """A fresh PKCE code verifier (RFC 7636, 43–128 characters)."""
    if not 43 <= length <= 128:
        raise ValueError("a PKCE code verifier must be 43 to 128 characters")
    return secrets.token_urlsafe(length)[:length].ljust(43, "x")[:length]


def code_challenge_s256(verifier: str) -> str:
    """The S256 code challenge for ``verifier``: base64url(sha256) without padding."""
    if not verifier:
        raise ValueError("a PKCE code verifier is required")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...] = ()
    redirect_uri: str = "http://127.0.0.1:8765/oauth/callback"
    extra_authorize_params: dict = field(default_factory=dict)

    def authorization_url(self, state: str, *, code_challenge: str | None = None,
                          code_verifier: str | None = None) -> str:
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
        challenge = code_challenge
        if challenge is None and code_verifier is not None:
            challenge = code_challenge_s256(code_verifier)
        if challenge:
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
        params.update(self.extra_authorize_params)
        return f"{self.authorize_url}?{urlencode(params)}"

    def pkce_pair(self) -> tuple[str, str]:
        """A fresh ``(code_verifier, code_challenge)`` pair for one flow."""
        verifier = generate_code_verifier()
        return verifier, code_challenge_s256(verifier)

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
    scope: str | None = None

    @classmethod
    def from_response(cls, data: dict) -> "TokenSet":
        if not data or not data.get("access_token"):
            raise ValueError("token response carries no access_token")
        return cls(access_token=data["access_token"],
                   refresh_token=data.get("refresh_token"),
                   expires_in=data.get("expires_in"),
                   token_type=data.get("token_type", "Bearer"),
                   scope=data.get("scope"))


class OAuthClient:
    """Token exchange and refresh through an injectable transport.

    ``client_secret`` is optional: public clients using PKCE omit it.
    When a credential store is supplied, exchanged tokens are stored
    under the given service name (``access_token`` / ``refresh_token``
    keys) through the store's own ``set`` method; stores without one
    are skipped rather than written to disk.
    """

    def __init__(self, config: OAuthConfig, transport, *, client_secret: str | None = None,
                 credential_store=None, service: str | None = None):
        problems = config.validate()
        if problems:
            raise ValueError("invalid OAuth config: " + "; ".join(problems))
        self.config = config
        self.transport = transport
        self.client_secret = client_secret
        self.credential_store = credential_store
        self.service = service

    # -- grants ------------------------------------------------------------
    def exchange_code(self, code: str, *, code_verifier: str | None = None,
                      redirect_uri: str | None = None) -> TokenSet:
        """Exchange an authorization code for tokens (PKCE when given)."""
        if not code:
            raise ValueError("an authorization code is required")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or self.config.redirect_uri,
            "client_id": self.config.client_id,
        }
        if code_verifier:
            form["code_verifier"] = code_verifier
        if self.client_secret:
            form["client_secret"] = self.client_secret
        tokens = self._token_request(form)
        self._store_tokens(tokens)
        return tokens

    def refresh(self, refresh_token: str | TokenSet) -> TokenSet:
        """Refresh a token set; rotation keeps a new refresh token.

        When the response carries a new ``refresh_token`` it replaces
        the old one (rotation). When it carries none, the previous
        refresh token remains valid and is kept on the returned set.
        """
        old_refresh = refresh_token.refresh_token if isinstance(refresh_token, TokenSet) else refresh_token
        if not old_refresh:
            raise ValueError("a refresh token is required")
        form = {
            "grant_type": "refresh_token",
            "refresh_token": old_refresh,
            "client_id": self.config.client_id,
        }
        if self.client_secret:
            form["client_secret"] = self.client_secret
        tokens = self._token_request(form)
        if not tokens.refresh_token:
            tokens = TokenSet(access_token=tokens.access_token, refresh_token=old_refresh,
                              expires_in=tokens.expires_in, token_type=tokens.token_type,
                              scope=tokens.scope)
        self._store_tokens(tokens)
        return tokens

    # -- internals -----------------------------------------------------------
    def _token_request(self, form: dict) -> TokenSet:
        resp = self.transport.request(
            "POST", self.config.token_url,
            headers={"Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"},
            form_body=form)
        data = resp.data if isinstance(resp.data, dict) else {}
        if not resp.ok or data.get("error"):
            raise OAuthError(str(data.get("error") or "token_request_failed"),
                             str(data.get("error_description") or resp.text or ""),
                             status=resp.status)
        return TokenSet.from_response(data)

    def _store_tokens(self, tokens: TokenSet) -> None:
        store = self.credential_store
        setter = getattr(store, "set", None) if store is not None else None
        if setter is None or not self.service:
            return
        setter(self.service, "access_token", tokens.access_token)
        if tokens.refresh_token:
            setter(self.service, "refresh_token", tokens.refresh_token)
