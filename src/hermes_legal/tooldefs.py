"""The legal_* agent tools: one definition each, one implementation path.
A read tool returns exactly what the matching `legal <command> --json` prints.
Writes describe themselves in plain words for an approval card, change nothing
until approved, and are refused in scheduled or unattended runs — the
hermes-finance contract, applied to legal work where a 'write' can mean filing
or sending something that cannot be unsent."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    write: bool = False
    action: bool = False   # changes nothing the user entered (e.g. a sync pull)

TOOLS = [
    Tool("legal_matter_list", "Matters: name, folder, privacy ceiling, status."),
    Tool("legal_matter_get", "One matter: metadata, documents, open deadlines, unverified citations."),
    Tool("legal_doc_search", "Search a matter's documents (local full-text and vector index). Nothing leaves the device."),
    Tool("legal_doc_read", "Read a document or page range from a matter, with page and span references."),
    Tool("legal_doc_compare", "Compare two document versions deterministically; returns the change list."),
    Tool("legal_cite_extract", "Extract citations from text or a document (eyecite-style parsing)."),
    Tool("legal_cite_check", "Verify citations against CourtListener / Caselaw Access Project / govinfo: exists, quote verified, history unknown."),
    Tool("legal_cite_format", "Format citations to Bluebook (current edition) deterministically.", write=True),
    Tool("legal_playbook_review", "Review a contract clause by clause against a playbook; returns findings, changes nothing."),
    Tool("legal_doc_redline", "Propose a redline as real Word track changes (w:ins / w:del), attributed to the AI and unverified until a human accepts them.", write=True),
    Tool("legal_chronology", "Build a dated chronology from a matter's documents, each entry cited to its source page."),
    Tool("legal_deadline_extract", "Extract dates and deadlines from orders and documents; returns candidates, computes nothing silently."),
    Tool("legal_deadline_calc", "Compute a deadline from a court rule data file, showing the rule and the arithmetic."),
    Tool("legal_transcribe", "Transcribe audio locally (Whisper on-device). Audio never leaves the device."),
    Tool("legal_intake_summary", "Summarize an intake form or folder into a matter summary."),
    Tool("legal_time_log", "Add a time entry for a matter.", write=True),
    Tool("legal_sync", "Pull new material from a connected source (CourtListener, Clio, a document store). Changes nothing the user entered.", action=True),
    Tool("legal_efile_bundle", "Prepare (never file) an e-filing bundle: ordered, paginated, format-checked, ready for a human to file.", write=True),
]

TOOL_NAMES = [t.name for t in TOOLS]
READ_TOOLS = [t.name for t in TOOLS if not t.write]
WRITE_TOOLS = [t.name for t in TOOLS if t.write]

def describe_write(name: str, args: dict) -> str:
    """The plain-words summary an approval card shows. Never empty."""
    return f"{name}: {args!r} — nothing changes until this is approved."
