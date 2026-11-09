"""Citation extraction and verification. The model never asserts that a
citation is real: a resolver does. Statuses are deliberately modest —
'exists' and 'quote_verified' say what was checked; subsequent history is
reported as unknown because Hermes Legal has no Shepard's or KeyCite."""
import re

CITE_RE = re.compile(r"\b\d{1,4}\s+(?:U\.S\.|F\.\s?\dd|F\. Supp\. \dd|S\. Ct\.|L\. Ed\. \dd|[A-Z][A-Za-z.]+ \dd?)\s+\d{1,5}\b")

def extract(text: str):
    return CITE_RE.findall(text) if hasattr(CITE_RE, "findall") else []

def extract_all(text: str):
    return [m.group(0) for m in CITE_RE.finditer(text)]

STATUSES = ("unverified", "exists", "quote_verified", "not_found", "history_unknown")
