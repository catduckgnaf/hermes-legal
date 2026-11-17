"""Acceptance tests for issue #6 (deadlines) and issue #5 (playbooks).

Each test maps onto one acceptance criterion or proposed-behavior bullet,
and each goes through the tool dispatcher (the surface an agent actually
calls) wherever a tool exists, so the criterion is pinned at the tool
boundary and not only inside the library modules.

Issue #6:
  AC1  worked example reproduces the hand calculation, rule shown
       -> test_issue6_ac1_*
  AC2  no deadline is created from extraction without human confirmation
       -> test_issue6_ac2_*
  B3   export to .ics; filing dates require dual entry
       -> test_issue6_ics_export_*, test_issue6_filing_dates_need_dual_entry
  B4   every computed deadline carries the verify-against-local-rules warning
       -> test_issue6_every_computed_deadline_carries_the_verify_warning

Issue #5:
  AC1  the three sample playbooks run against the demo contract and produce
       findings tied to clauses -> test_issue5_ac1_*
  AC2  editing a playbook file changes review output with no code change
       -> test_issue5_ac2_*
  B2   proposed language becomes a redline only through the approval-gated
       legal_doc_redline tool -> test_issue5_proposed_language_*

HAND CALCULATION A (used by test_issue6_ac1_*), Fed. R. Civ. P. 33(b)(2)
counted under Rule 6(a), with Rule 6(d) for service by mail:
  Interrogatories served by mail on Thursday, October 8, 2026.
  Rule 6(a)(1)(A): exclude October 8. Rule 6(a)(1)(B): count every day.
  October has 31 days, so October 9 is day 1 and October 31 is day 23;
  November 1 is day 24, and November 7 is day 30.
  November 7, 2026 is a Saturday. Rule 6(a)(1)(C): the period continues
  to the next day that is not a Saturday, Sunday, or legal holiday.
  November 8 is a Sunday; November 9 is a Monday and not a holiday.
  The period would otherwise expire Monday, November 9, 2026.
  Rule 6(d): 3 days are added after that: November 10, 11, 12.
  (November 11, Veterans Day, is an intermediate day and is counted.)
  November 12, 2026 is a Thursday, not a weekend or legal holiday.
  Hand result: due Thursday, November 12, 2026.

HAND CALCULATION B, Fed. R. Civ. P. 59(b), a filing deadline:
  Judgment entered Thursday, November 26, 2026. Exclude November 26.
  November 27 is day 1, November 30 is day 4, December 24 is day 28.
  December 24, 2026 is a Thursday and is not on the federal holiday list
  (Christmas Day is December 25). No roll. Rule 6(d) does not apply.
  Hand result: due Thursday, December 24, 2026.
"""
import datetime
from pathlib import Path

import pytest

from hermes_legal import db, deadlines, dispatch as runtime, docx_edit, matters, mcp_server

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS_DIR = ROOT / "playbooks"
SAMPLES = ("nda", "msa", "employment")

ORDER_TEXT = (
    "ORDERED that defendant shall file its opposition by March 16, 2026. "
    "Responses are due within 30 days after service."
)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_LEGAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv(runtime.AGENT_TIER_ENV, raising=False)
    monkeypatch.delenv(runtime.PLAYBOOK_DIR_ENV, raising=False)
    monkeypatch.delenv(mcp_server.UNATTENDED_ENV, raising=False)
    folder = tmp_path / "matter"
    folder.mkdir()
    demo = (PLAYBOOKS_DIR / "demo-contract.md").read_text(encoding="utf-8")
    (folder / "demo-contract.md").write_text(demo, encoding="utf-8")
    (folder / "contract.docx").write_bytes(
        docx_edit.make_docx(["Confidential Information must be protected in perpetuity."]))
    (folder / "order.txt").write_text(ORDER_TEXT, encoding="utf-8")
    conn = db.connect()
    mid = matters.open_folder_as_matter(conn, folder, "Synthetic Client")
    return conn, mid, folder


def agent():
    return runtime.Context.open("mcp", environ={runtime.AGENT_TIER_ENV: "LOCAL_ONLY"})


def call(tool, args):
    outcome = runtime.dispatch(tool, args, agent())
    assert outcome["ok"], outcome
    return outcome["result"]


def deadline_count(conn):
    deadlines.ensure_deadline_columns(conn)
    return conn.execute("SELECT COUNT(*) FROM deadlines").fetchone()[0]


# =========================================================== issue #6, AC1

def test_issue6_ac1_worked_example_reproduces_hand_calculation_with_rule_shown(world):
    result = call("legal_deadline_calc", {
        "rule_id": "frcp-33b2-interrogatory-answers",
        "trigger_date": "2026-10-08", "service_method": "mail"})
    assert result["due_date"] == "2026-11-12"  # hand calculation A
    assert datetime.date.fromisoformat(result["due_date"]).strftime("%A") == "Thursday"
    # The rule is shown: citation, source, and the version date of the data file.
    assert result["citation"] == "Fed. R. Civ. P. 33(b)(2)"
    assert "uscourts.gov" in result["rule_source"]
    assert "version date" in result["rule_source"]
    # The arithmetic is shown step by step, in the order of the hand calculation.
    steps = result["steps"]
    text = "\n".join(steps)
    markers = [
        "Fed. R. Civ. P. 33(b)(2)",        # the rule
        "Fed. R. Civ. P. 6(a)",            # the counting rule
        "exclude the trigger day, 2026-10-08 (Thursday)",
        "2026-10-08 + 30 days = 2026-11-07 (Saturday)",
        "2026-11-08 (Sunday)",             # the roll passes Sunday
        "would otherwise expire on 2026-11-09 (Monday)",
        "Fed. R. Civ. P. 6(d) adds 3 days because service was by mail",
        "2026-11-09 + 3 days = 2026-11-12 (Thursday)",
        "Result: due 2026-11-12 (Thursday)",
    ]
    positions = [text.find(marker) for marker in markers]
    assert all(pos >= 0 for pos in positions), dict(zip(markers, positions))
    assert positions == sorted(positions), "steps are not in hand-calculation order"


def test_issue6_ac1_hand_calculation_matches_an_independent_day_by_day_count():
    """Recount hand calculation A one day at a time, without the module's
    arithmetic, so the test does not just restate the implementation."""
    holidays = deadlines.federal_holidays(2026)
    day = datetime.date(2026, 10, 8)            # trigger day, excluded
    for _ in range(30):                          # count every day
        day += datetime.timedelta(days=1)
    while day.weekday() >= 5 or day in holidays:  # roll forward
        day += datetime.timedelta(days=1)
    assert day == datetime.date(2026, 11, 9)
    for _ in range(3):                           # Rule 6(d)
        day += datetime.timedelta(days=1)
    while day.weekday() >= 5 or day in holidays:
        day += datetime.timedelta(days=1)
    assert day == datetime.date(2026, 11, 12)
    calc = deadlines.calculate("frcp-33b2-interrogatory-answers", "2026-10-08", "mail")
    assert calc.due_date == day


def test_issue6_ac1_filing_worked_example_reproduces_hand_calculation(world):
    result = call("legal_deadline_calc", {"rule_id": "frcp-59b-new-trial-motion", "trigger_date": "2026-11-26"})
    assert result["due_date"] == "2026-12-24"  # hand calculation B
    assert result["citation"] == "Fed. R. Civ. P. 59(b)"
    assert result["is_filing"] is True
    assert any("2026-11-26 + 28 days = 2026-12-24 (Thursday)" in step for step in result["steps"])


# =========================================================== issue #6, AC2

def test_issue6_ac2_extraction_tool_creates_no_deadline_without_human_confirmation(world):
    conn, mid, _ = world
    before = deadline_count(conn)
    for args in ({"text": ORDER_TEXT}, {"matter_id": mid, "path": "order.txt"}):
        result = call("legal_deadline_extract", args)
        assert len(result["candidates"]) == 2
        assert all(c["confirmed"] is False for c in result["candidates"])
        assert "human must confirm" in result["note"]
    assert deadline_count(conn) == before == 0
    assert runtime.list_actions(conn) == [], "extraction must not even propose a write"
    assert call("legal_matter_get", {"matter_id": mid})["deadlines"] == []


def test_issue6_ac2_calculation_tool_creates_no_deadline_either(world):
    conn, mid, _ = world
    call("legal_deadline_calc", {"rule_id": "frcp-12a1ai-answer-after-service", "trigger_date": "2026-03-02"})
    assert deadline_count(conn) == 0
    assert call("legal_matter_get", {"matter_id": mid})["deadlines"] == []


def test_issue6_ac2_only_a_named_human_turns_a_candidate_into_a_deadline(world):
    conn, mid, _ = world
    candidate = next(c for c in deadlines.extract_candidates("The hearing is set for March 16, 2026."))
    for nobody in ("", "   ", None):
        with pytest.raises(ValueError, match="named human confirmer"):
            deadlines.confirm_candidate(conn, mid, candidate, "Hearing", nobody)
    assert deadline_count(conn) == 0
    deadlines.confirm_candidate(conn, mid, candidate, "Hearing", "A. Lawyer")
    row, = call("legal_matter_get", {"matter_id": mid})["deadlines"]
    assert row["confirmed_by"] == "A. Lawyer" and row["status"] == "confirmed" and row["verified"] == 1


def test_issue6_no_agent_tool_can_create_or_confirm_a_deadline():
    """Confirmation has no agent tool at all, so an agent cannot confirm on
    a person's behalf. If a deadline write tool is added later it must be
    approval-gated (write=True), which this test then forces a decision on."""
    from hermes_legal import tooldefs
    deadline_tools = {name: tool for name, tool in runtime.TOOLS_BY_NAME.items() if "deadline" in name}
    assert set(deadline_tools) == {"legal_deadline_extract", "legal_deadline_calc"}
    assert not any(tool.write for tool in deadline_tools.values())
    assert tooldefs  # imported to keep the catalog the single source


# ================================================= issue #6, export bullet

def test_issue6_ics_export_has_confirmed_deadlines_only_and_valid_structure(world):
    conn, mid, _ = world
    calc = deadlines.calculate("frcp-33b2-interrogatory-answers", "2026-10-08", "mail")
    deadlines.confirm_calculation(conn, mid, calc, "Answer interrogatories; see order", "A. Lawyer")
    conn.execute("INSERT INTO deadlines (matter_id, due_at, title, verified, status) "
                 "VALUES (?, '2026-12-01', 'Unconfirmed candidate', 0, 'candidate')", (mid,))
    conn.commit()
    ics = deadlines.export_ics(conn, mid, now=datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc))
    lines = ics.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert "\n" not in ics.replace("\r\n", ""), "RFC 5545 lines end in CRLF"
    assert "VERSION:2.0" in lines and any(line.startswith("PRODID:") for line in lines)
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20261112" in lines
    assert "DTEND;VALUE=DATE:20261113" in lines      # all-day event, exclusive end
    assert "DTSTAMP:20260102T030405Z" in lines
    assert "SUMMARY:Answer interrogatories\\; see order" in lines  # text escaped
    assert "Unconfirmed candidate" not in ics
    description = next(line for line in lines if line.startswith("DESCRIPTION:"))
    assert "Fed. R. Civ. P. 33(b)(2)" in description
    assert "Verify against local rules" in description


# ================================================ issue #6, dual entry bullet

def test_issue6_filing_dates_need_dual_entry(world):
    conn, mid, _ = world
    # Path 1: a calculated filing deadline (the rule data marks Rule 59(b) as filing).
    calc = deadlines.calculate("frcp-59b-new-trial-motion", "2026-11-26")
    # Path 2: an extracted filing date ("shall file ... by").
    candidate = deadlines.extract_candidates(ORDER_TEXT)[0]
    assert calc.is_filing and candidate.is_filing

    def confirm_calc(first, second=None):
        return deadlines.confirm_calculation(conn, mid, calc, "Rule 59 motion", first, second)

    def confirm_cand(first, second=None):
        return deadlines.confirm_candidate(conn, mid, candidate, "Opposition", first, second)

    for confirm in (confirm_calc, confirm_cand):
        with pytest.raises(ValueError, match="dual entry"):
            confirm("A. Lawyer")                       # one person is not enough
        with pytest.raises(ValueError, match="must differ"):
            confirm("A. Lawyer", " A. Lawyer ")        # the same person twice is not two
        with pytest.raises(ValueError, match="dual entry"):
            confirm("A. Lawyer", "  ")                 # a blank second entry is not a person
    assert deadline_count(conn) == 0
    confirm_calc("A. Lawyer", "B. Paralegal")
    confirm_cand("A. Lawyer", "B. Paralegal")
    rows = deadlines.list_deadlines(conn, mid)
    assert [(r["confirmed_by"], r["second_confirmer"]) for r in rows] == [("A. Lawyer", "B. Paralegal")] * 2


# ================================================== issue #6, warning bullet

@pytest.mark.parametrize("method", ["personal", "mail", "electronic", "leaving_with_clerk", "other_consented"])
def test_issue6_every_computed_deadline_carries_the_verify_warning(world, method):
    conn, mid, _ = world
    calculable = [rule_id for rule_id, rule in deadlines.load_rules().items() if rule.get("period_days")]
    assert len(calculable) >= 6
    for rule_id in calculable:
        result = call("legal_deadline_calc", {"rule_id": rule_id, "trigger_date": "2026-03-06", "service_method": method})
        assert result["warning"] == deadlines.VERIFY_WARNING, rule_id
        assert "local rules" in result["warning"]
        assert result["steps"][-1] == f"Warning: {deadlines.VERIFY_WARNING}", rule_id
    # The warning survives confirmation, storage, and both export forms.
    calc = deadlines.calculate(calculable[0], "2026-03-06", method)
    deadlines.confirm_calculation(conn, mid, calc, "Deadline", "A. Lawyer", "B. Paralegal")
    row, = deadlines.list_deadlines(conn, mid)
    assert deadlines.VERIFY_WARNING in row["calculation_json"]
    assert "Verify against local rules" in deadlines.export_ics(conn, mid)
    event, = deadlines.export_calendar_events(conn, mid)
    assert deadlines.VERIFY_WARNING in str(event)


# =========================================================== issue #5, AC1

@pytest.mark.parametrize("name", SAMPLES)
def test_issue5_ac1_sample_playbook_runs_against_demo_contract_with_findings_tied_to_clauses(world, name):
    _, mid, folder = world
    result = call("legal_playbook_review", {"matter_id": mid, "path": "demo-contract.md", "playbook": name})
    assert result["playbook_id"] == name
    assert result["clause_count"] >= 6 and result["rules_checked"] >= 3
    findings = result["findings"]
    assert findings, f"{name} produced no findings on the demo contract"
    demo_lines = (folder / "demo-contract.md").read_text(encoding="utf-8").splitlines()
    tied = [f for f in findings if f["clause_index"] is not None]
    assert len(tied) >= 2, f"{name}: fewer than two findings are tied to a clause"
    for finding in tied:
        assert 0 <= finding["clause_index"] < result["clause_count"]
        assert finding["clause_number"], finding
        # The heading the finding names is a real heading in the demo contract.
        assert any(finding["clause_heading"] in line for line in demo_lines), finding
        assert finding["excerpt"], finding
    for finding in findings:
        assert finding["rationale"], finding          # findings come with rationale
        if finding["clause_index"] is None:
            assert finding["status"] == "missing", finding  # only an absent clause is untied
    assert "not assurance" in result["note"]


def test_issue5_ac1_each_sample_playbook_ties_a_known_finding_to_the_right_clause(world):
    _, mid, _ = world
    expected = {
        "nda": ("forbid-perpetual-confidentiality", "forbidden", "1. Confidentiality"),
        "msa": ("forbid-unlimited-liability", "forbidden", "6. Liability"),
        "employment": ("noncompete-duration-position", "deviation", "5. Restrictive Covenants"),
    }
    for name, (rule_id, status, heading) in expected.items():
        result = call("legal_playbook_review", {"matter_id": mid, "path": "demo-contract.md", "playbook": name})
        finding = next(f for f in result["findings"] if f["rule_id"] == rule_id)
        assert (finding["status"], finding["clause_heading"]) == (status, heading)


# =========================================================== issue #5, AC2

def test_issue5_ac2_editing_a_playbook_file_changes_tool_output_with_no_code_change(world, tmp_path, monkeypatch):
    _, mid, _ = world
    firm = tmp_path / "firm-playbooks"
    firm.mkdir()
    playbook_file = firm / "nda.md"
    playbook_file.write_text((PLAYBOOKS_DIR / "nda.md").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(runtime.PLAYBOOK_DIR_ENV, str(firm))
    args = {"matter_id": mid, "path": "demo-contract.md", "playbook": "nda"}

    before = call("legal_playbook_review", args)
    before_ids = [f["rule_id"] for f in before["findings"]]
    assert "forbid-short-termination-notice-test" not in before_ids

    # Edit only the file: add one rule to its Rules section. No module is
    # reloaded or patched.
    new_rule = (
        "### forbid-short-termination-notice-test\n"
        "title: No ten day termination notice\nkind: forbidden\nseverity: high\n"
        "topic: term\npatterns: ten days written notice\n"
        "rationale: Ten days of notice is not an approved position.\n"
        "fallback: Either party may terminate on sixty days written notice.\n\n")
    text = playbook_file.read_text(encoding="utf-8")
    assert text.count("## Clause library") == 1
    playbook_file.write_text(text.replace("## Clause library", new_rule + "## Clause library"), encoding="utf-8")
    after = call("legal_playbook_review", args)
    after_ids = [f["rule_id"] for f in after["findings"]]
    added = next(f for f in after["findings"] if f["rule_id"] == "forbid-short-termination-notice-test")
    assert set(after_ids) - set(before_ids) == {"forbid-short-termination-notice-test"}
    assert added["clause_heading"] == "3. Term and Termination" and added["status"] == "forbidden"
    assert after["rules_checked"] == before["rules_checked"] + 1

    # Editing the rationale text changes the output text as well.
    playbook_file.write_text(playbook_file.read_text(encoding="utf-8").replace(
        "Ten days of notice is not an approved position.", "The firm requires at least sixty days of notice."), encoding="utf-8")
    again = call("legal_playbook_review", args)
    assert next(f for f in again["findings"] if f["rule_id"] == "forbid-short-termination-notice-test")["rationale"] \
        == "The firm requires at least sixty days of notice."


# ================================================= issue #5, redline bullet

def test_issue5_proposed_language_becomes_a_redline_only_through_the_approval_gate(world):
    conn, mid, folder = world
    before_files = sorted(p.name for p in folder.iterdir())
    original_bytes = (folder / "contract.docx").read_bytes()

    # 1. Review proposes language (the fallback) but writes and proposes nothing.
    review = call("legal_playbook_review", {"matter_id": mid, "path": "contract.docx", "playbook": "nda"})
    finding = next(f for f in review["findings"] if f["rule_id"] == "forbid-perpetual-confidentiality")
    proposed = finding["fallback"]
    assert proposed
    assert runtime.TOOLS_BY_NAME["legal_playbook_review"].write is False
    assert sorted(p.name for p in folder.iterdir()) == before_files
    assert (folder / "contract.docx").read_bytes() == original_bytes
    assert runtime.list_actions(conn) == []

    # 2. The only tool that turns language into a redline is a gated write.
    assert runtime.TOOLS_BY_NAME["legal_doc_redline"].write is True
    redline = {"matter_id": mid, "original": "contract.docx", "output": "contract-redline.docx",
               "paragraphs": [proposed]}
    proposal = call("legal_doc_redline", redline)
    assert proposal["status"] == "pending_approval"
    assert not (folder / "contract-redline.docx").exists(), "nothing is written before approval"

    # 3. An unattended run cannot even propose it, and approval needs a named person.
    unattended = runtime.dispatch("legal_doc_redline", {**redline, "output": "other.docx"},
                                  runtime.Context.open("mcp", environ={runtime.AGENT_TIER_ENV: "LOCAL_ONLY"},
                                                       unattended=True))
    assert unattended["error"]["code"] == "refused_unattended"
    with pytest.raises(runtime.ToolError):
        runtime.approve(conn, proposal["action_id"], "  ")
    assert not (folder / "contract-redline.docx").exists()

    # 4. After a named person approves, the proposed language exists as tracked changes.
    assert runtime.approve(conn, proposal["action_id"], "A. Lawyer")["status"] == "executed"
    out = (folder / "contract-redline.docx").read_bytes()
    assert docx_edit.has_track_changes(out)
    assert docx_edit.accept_all_text(out)[0] == proposed
    assert docx_edit.reject_all_text(out)[0] == "Confidential Information must be protected in perpetuity."
    assert (folder / "contract.docx").read_bytes() == original_bytes, "the original is never modified"


def test_issue5_rejected_redline_never_writes_the_proposed_language(world):
    conn, mid, folder = world
    proposal = call("legal_doc_redline", {"matter_id": mid, "original": "contract.docx",
                                          "output": "contract-redline.docx", "paragraphs": ["Three years."]})
    assert runtime.reject(conn, proposal["action_id"], "A. Lawyer")["status"] == "rejected"
    with pytest.raises(runtime.ToolError, match="already"):
        runtime.approve(conn, proposal["action_id"], "A. Lawyer")
    assert not (folder / "contract-redline.docx").exists()
