"""Connector framework and the P1 connectors from issue #8.

Every connector follows the same contract: a doctor check, a
data-flow label, a per-matter enable flag, credentials only through a
credential store (OS keychain first, environment fallback for tests),
read-only by default, and writes as pending actions that a named
human must approve. All HTTP goes through an injectable transport.
"""
from .base import (
    ApprovalRecord,
    ApprovalRequired,
    BaseConnector,
    ChainCredentialStore,
    ConnectorDisabled,
    CredentialStore,
    CtypesWin32CredBackend,
    DataFlowLabel,
    DoctorResult,
    DurablePendingActionStore,
    EnvCredentialStore,
    FakeTransport,
    KeychainCredentialStore,
    MemoryCredentialStore,
    PendingAction,
    Transport,
    TransportResponse,
    UrllibTransport,
    default_credential_store,
)
from .clio import CLIO_BASE, ClioConnector, clio_oauth
from .docusign import (
    DOCUSIGN_DEMO_BASE,
    OPEN_ALTERNATIVES,
    SELF_HOSTED_PROVIDERS,
    DocuSignAccount,
    DocuSignConnector,
    docusign_oauth,
)
from .oauth import (
    OAuthClient,
    OAuthConfig,
    OAuthError,
    TokenSet,
    code_challenge_s256,
    generate_code_verifier,
)
from .pacer import (
    PACER_AUTH_URL,
    PACER_CASE_LOCATOR_BASE,
    CostEstimate,
    CourtListenerConnector,
    LookupResult,
    PacerAuthError,
    PacerConnector,
    RecapCheckRequired,
)

ALL_CONNECTORS = (ClioConnector, DocuSignConnector, CourtListenerConnector, PacerConnector)

__all__ = [
    "ALL_CONNECTORS", "ApprovalRecord", "ApprovalRequired", "BaseConnector", "CLIO_BASE",
    "ChainCredentialStore", "ClioConnector", "ConnectorDisabled", "CostEstimate",
    "CourtListenerConnector", "CredentialStore", "CtypesWin32CredBackend", "DataFlowLabel",
    "DOCUSIGN_DEMO_BASE", "DocuSignAccount",
    "DoctorResult", "DocuSignConnector", "DurablePendingActionStore", "EnvCredentialStore",
    "FakeTransport",
    "KeychainCredentialStore", "LookupResult", "MemoryCredentialStore", "OAuthClient",
    "OAuthConfig", "OAuthError",
    "OPEN_ALTERNATIVES", "PACER_AUTH_URL", "PACER_CASE_LOCATOR_BASE", "PacerAuthError",
    "PacerConnector", "PendingAction", "RecapCheckRequired", "SELF_HOSTED_PROVIDERS",
    "TokenSet", "Transport",
    "TransportResponse", "UrllibTransport", "clio_oauth", "code_challenge_s256",
    "default_credential_store",
    "docusign_oauth", "generate_code_verifier",
]
