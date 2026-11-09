"""Connector framework and the P1 connectors from issue #8.

Every connector follows the same contract: a doctor check, a
data-flow label, a per-matter enable flag, credentials only through a
credential store (OS keychain first, environment fallback for tests),
read-only by default, and writes as pending actions that a named
human must approve. All HTTP goes through an injectable transport.
"""
from .base import (
    ApprovalRequired,
    BaseConnector,
    ChainCredentialStore,
    ConnectorDisabled,
    CredentialStore,
    DataFlowLabel,
    DoctorResult,
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
    DocuSignConnector,
    docusign_oauth,
)
from .oauth import OAuthConfig, TokenSet
from .pacer import (
    CostEstimate,
    CourtListenerConnector,
    LookupResult,
    PacerConnector,
)

ALL_CONNECTORS = (ClioConnector, DocuSignConnector, CourtListenerConnector, PacerConnector)

__all__ = [
    "ALL_CONNECTORS", "ApprovalRequired", "BaseConnector", "CLIO_BASE",
    "ChainCredentialStore", "ClioConnector", "ConnectorDisabled", "CostEstimate",
    "CourtListenerConnector", "CredentialStore", "DataFlowLabel", "DOCUSIGN_DEMO_BASE",
    "DoctorResult", "DocuSignConnector", "EnvCredentialStore", "FakeTransport",
    "KeychainCredentialStore", "LookupResult", "MemoryCredentialStore", "OAuthConfig",
    "OPEN_ALTERNATIVES", "PacerConnector", "PendingAction", "TokenSet", "Transport",
    "TransportResponse", "UrllibTransport", "clio_oauth", "default_credential_store",
    "docusign_oauth",
]
