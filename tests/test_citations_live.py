"""Live CourtListener checks. Excluded by default (pyproject addopts runs
-m 'not live'); run explicitly with a token set:

    COURTLISTENER_API_TOKEN=... python -m pytest -m live tests/test_citations_live.py

These are the only tests in the suite allowed to make a real network call.
"""
import pytest

from hermes_legal.citations import CourtListenerClient

pytestmark = pytest.mark.live


def test_live_known_good_citation_verifies():
    client = CourtListenerClient()
    result = client.verify("678 F. Supp. 3d 443")
    assert result.status in ("exists", "quote_verified")


def test_live_invented_citation_not_found():
    client = CourtListenerClient()
    result = client.verify("999 F.3d 9999")
    assert result.status in ("not_found", "unverified")
