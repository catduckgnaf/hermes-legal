"""Playbook review: parsing, clause splitting, rule checks, samples.

The demo contract and the sample playbooks are synthetic. No real
client data is used anywhere in this file.
"""
from pathlib import Path

import pytest

from hermes_legal.playbooks import (
    PlaybookError,
    find_playbooks,
    legal_playbook_review,
    load_playbook,
    parse_playbook,
    review_contract,
    split_clauses,
)

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS_DIR = ROOT / "playbooks"
DEMO_CONTRACT = PLAYBOOKS_DIR / "demo-contract.md"


def demo_text() -> str:
    return DEMO_CONTRACT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Clause splitting
# ---------------------------------------------------------------------------

def test_split_clauses_by_numbered_headings():
    clauses = split_clauses(demo_text())
    headings = [c.heading for c in clauses]
    assert len(clauses) >= 6
    assert any("Confidentiality" in h for h in headings)
    assert any("Governing Law" in h for h in headings)
    # Indices are stable and sequential, so a finding can cite a clause.
    assert [c.index for c in clauses] == list(range(len(clauses)))


def test_split_clauses_by_section_headings():
    text = (
        "Section 1. Purpose\nThe purpose is testing.\n\n"
        "Section 2. Payment\nPayment is due on receipt.\n\n"
        "Section 3. Term\nThe term is one year.\n"
    )
    clauses = split_clauses(text)
    assert len(clauses) == 3
    assert clauses[1].number == "2"
    assert "Payment" in clauses[1].text


def test_split_clauses_paragraph_fallback():
    text = "First paragraph about confidentiality.\n\nSecond paragraph about payment.\n"
    clauses = split_clauses(text)
    assert len(clauses) == 2


# ---------------------------------------------------------------------------
# Playbook parsing
# ---------------------------------------------------------------------------

def test_parse_minimal_playbook():
    pb = parse_playbook(
        "# Playbook: Tiny\n"
        "id: tiny\nname: Tiny\nversion: 1\n\n"
        "## Rules\n\n"
        "### need-term\n"
        "title: Term is required\nkind: required\nseverity: low\n"
        "topic: term\npatterns: term of this agreement\n"
        "rationale: A term is needed.\nfallback: The term is one year.\n"
    )
    assert pb.id == "tiny"
    assert len(pb.rules) == 1
    assert pb.rules[0].kind == "required"


def test_parse_rejects_missing_id():
    with pytest.raises(PlaybookError):
        parse_playbook("## Rules\n\n### r1\ntitle: X\nkind: required\n")


def test_parse_rejects_unknown_kind():
    with pytest.raises(PlaybookError):
        parse_playbook(
            "id: bad\n\n## Rules\n\n### r1\ntitle: X\nkind: mysterious\n"
        )


def test_sample_playbooks_parse_with_library():
    for name in ("nda", "msa", "employment"):
        pb = load_playbook(PLAYBOOKS_DIR / f"{name}.md")
        assert pb.id == name
        assert len(pb.rules) >= 4
        assert len(pb.library) >= 3
        assert all(c.language for c in pb.library)
        assert all(r.rationale for r in pb.rules)


def test_find_playbooks_excludes_demo_contract():
    found = {p.name for p in find_playbooks(PLAYBOOKS_DIR)}
    assert found == {"nda.md", "msa.md", "employment.md"}


# ---------------------------------------------------------------------------
# Rule checks against the demo contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["nda", "msa", "employment"])
def test_sample_playbooks_produce_findings_tied_to_clauses(name):
    pb = load_playbook(PLAYBOOKS_DIR / f"{name}.md")
    result = legal_playbook_review(demo_text(), pb)
    assert result.playbook_id == name
    assert result.clause_count >= 6
    assert result.rules_checked == len(pb.rules)
    assert result.findings, f"{name} produced no findings on the demo contract"
    tied = [f for f in result.findings if f.clause_index is not None]
    assert tied, f"{name} produced no finding tied to a clause"
    for finding in tied:
        assert finding.clause_heading
        assert 0 <= finding.clause_index < result.clause_count


def test_nda_forbidden_perpetuity_is_tied_to_confidentiality_clause():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "nda.md"))
    hits = [f for f in result.findings if f.rule_id == "forbid-perpetual-confidentiality"]
    assert len(hits) == 1
    assert hits[0].status == "forbidden"
    assert "Confidentiality" in hits[0].clause_heading
    assert "perpetuity" in hits[0].excerpt.lower() or "perpetual" in hits[0].excerpt.lower()
    assert hits[0].fallback  # proposed language travels with the finding


def test_nda_missing_required_clause():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "nda.md"))
    missing = {f.rule_id for f in result.findings if f.status == "missing"}
    assert "require-return-of-materials" in missing


def test_nda_incomplete_required_clause_names_missing_element():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "nda.md"))
    hits = [f for f in result.findings if f.rule_id == "require-confidentiality-definition"]
    assert len(hits) == 1
    assert hits[0].status == "incomplete"
    assert hits[0].clause_index is not None
    assert "oral" in hits[0].message


def test_msa_forbidden_unlimited_liability_and_payment_deviation():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "msa.md"))
    by_rule = {f.rule_id: f for f in result.findings}
    assert by_rule["forbid-unlimited-liability"].status == "forbidden"
    assert "Liability" in by_rule["forbid-unlimited-liability"].clause_heading
    assert by_rule["payment-window-position"].status == "deviation"
    assert "Payment" in by_rule["payment-window-position"].clause_heading
    assert "Net 30" in by_rule["payment-window-position"].fallback


def test_employment_forbidden_noncompete_and_duration_deviation():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "employment.md"))
    by_rule = {f.rule_id: f for f in result.findings}
    assert by_rule["forbid-overbroad-noncompete-language"].status == "forbidden"
    assert by_rule["noncompete-duration-position"].status == "deviation"
    assert by_rule["require-at-will-statement"].status == "missing"


def test_fallback_acceptable_position_is_low_severity_finding():
    contract = (
        "## 1. Governing Law\n"
        "This Agreement is governed by the laws of the State of New York.\n\n"
        "## 2. Confidentiality\n"
        "Confidential Information disclosed in written or oral form must be "
        "protected, and all materials must allow return or destroy on request. "
        "The term of this agreement is two years.\n"
    )
    result = legal_playbook_review(contract, load_playbook(PLAYBOOKS_DIR / "nda.md"))
    hits = [f for f in result.findings if f.rule_id == "governing-law-position"]
    assert len(hits) == 1
    assert hits[0].status == "fallback_acceptable"
    assert hits[0].severity == "low"


def test_preferred_position_produces_no_fallback_finding():
    contract = (
        "## 1. Governing Law\n"
        "This Agreement is governed by the laws of the State of Delaware.\n"
    )
    pb = parse_playbook(
        "id: gov\nname: Gov\n\n## Rules\n\n"
        "### gov-position\ntitle: Governing law\nkind: fallback\nseverity: medium\n"
        "topic: governing law\npatterns: governed by\npreferred: Delaware\n"
        "acceptable: New York\nrationale: Delaware is preferred.\n"
        "fallback: Governed by Delaware law.\n"
    )
    result = review_contract(contract, pb)
    assert result.findings == ()


def test_result_to_dict_summary_counts():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "nda.md"))
    data = result.to_dict()
    assert data["summary"]["total"] == len(result.findings)
    assert data["summary"]["forbidden"] >= 1
    assert all("rule_id" in f and "clause_heading" in f for f in data["findings"])


# ---------------------------------------------------------------------------
# Editing a playbook file changes the review, with no code change
# ---------------------------------------------------------------------------

def test_editing_playbook_file_changes_review_output(tmp_path):
    contract = (
        "## 1. Confidentiality\n"
        "Confidential Information must be protected in perpetuity.\n\n"
        "## 2. Payment\nInvoices are payable Net 30.\n"
    )
    playbook_file = tmp_path / "custom.md"
    playbook_file.write_text(
        "# Playbook: Custom\n"
        "id: custom\nname: Custom\nversion: 1\n\n"
        "## Rules\n\n"
        "### forbid-perpetuity\n"
        "title: No perpetual duties\nkind: forbidden\nseverity: high\n"
        "topic: confidentiality\npatterns: in perpetuity\n"
        "rationale: Perpetual duties are not approved.\n"
        "fallback: Duties survive for three years.\n",
        encoding="utf-8",
    )
    before = legal_playbook_review(contract, playbook_file)
    assert [f.rule_id for f in before.findings] == ["forbid-perpetuity"]

    # Edit only the file: forbid Net 30 instead of perpetuity.
    edited = playbook_file.read_text(encoding="utf-8").replace(
        "patterns: in perpetuity", "patterns: Net 30"
    ).replace("forbid-perpetuity", "forbid-net-30").replace(
        "title: No perpetual duties", "title: No Net 30 payment"
    )
    playbook_file.write_text(edited, encoding="utf-8")

    after = legal_playbook_review(contract, playbook_file)
    assert [f.rule_id for f in after.findings] == ["forbid-net-30"]
    assert after.findings[0].clause_heading != before.findings[0].clause_heading
    assert after.to_dict() != before.to_dict()


def test_adding_a_rule_to_a_playbook_file_adds_a_finding(tmp_path):
    source = (PLAYBOOKS_DIR / "nda.md").read_text(encoding="utf-8")
    playbook_file = tmp_path / "nda-copy.md"
    playbook_file.write_text(source, encoding="utf-8")
    before = legal_playbook_review(demo_text(), playbook_file)

    edited_source = source.replace(
        "## Clause library",
        "### forbid-texas-law\n"
        "title: Texas governing law is forbidden in this edited copy\n"
        "kind: forbidden\nseverity: high\ntopic: governing law\n"
        "patterns: State of Texas\n"
        "rationale: Added by editing the file in this test.\n"
        "fallback: This Agreement is governed by Delaware law.\n\n"
        "## Clause library",
        1,
    )
    playbook_file.write_text(edited_source, encoding="utf-8")
    after = legal_playbook_review(demo_text(), playbook_file)
    assert len(after.findings) == len(before.findings) + 1
    added = [f for f in after.findings if f.rule_id == "forbid-texas-law"]
    assert len(added) == 1
    assert "Governing Law" in added[0].clause_heading


def test_invalid_regex_is_a_parse_error_not_a_rule_that_never_fires():
    import pytest
    from hermes_legal.playbooks import PlaybookError, parse_playbook
    text = "id: x\n\n## Rules\n\n### r\nkind: forbidden\npatterns: /perpetu(al/\n"
    with pytest.raises(PlaybookError, match="invalid pattern"):
        parse_playbook(text)


# ---------------------------------------------------------------------------
# Negation-aware matching: a negated mention does not satisfy a rule
# ---------------------------------------------------------------------------

def _indemnification_playbook():
    return parse_playbook(
        "id: indemnity\nname: Indemnity\n\n## Rules\n\n"
        "### require-indemnification\n"
        "title: Indemnification is required\nkind: required\nseverity: high\n"
        "topic: indemnification\npatterns: indemnification; indemnify\n"
        "rationale: The agreement must allocate third-party claim risk.\n"
        "fallback: Provider will indemnify Client against third-party claims.\n"
    )


@pytest.mark.parametrize(
    "contract_body",
    [
        "There is no indemnification under this Agreement.",
        "The Provider shall not indemnify the Client for any claim.",
        "In no event will the Provider indemnify the Client.",
        "This Agreement provides no indemnify protection to either party.",
        "Indemnification is not provided under this Agreement.",
    ],
)
def test_negated_indemnification_does_not_satisfy_required_clause(contract_body):
    contract = f"## 1. Indemnification\n{contract_body}\n"
    result = review_contract(contract, _indemnification_playbook())
    hits = [f for f in result.findings if f.rule_id == "require-indemnification"]
    assert len(hits) == 1
    assert hits[0].status == "missing"
    # The finding is tied to the clause carrying the negated mention and
    # says plainly that the negated mention does not satisfy the rule.
    assert hits[0].clause_index is not None
    assert "Indemnification" in hits[0].clause_heading
    assert "negat" in hits[0].message.lower()
    assert hits[0].excerpt


@pytest.mark.parametrize(
    "contract_body",
    [
        "The Provider will indemnify the Client against third-party claims.",
        "Indemnification: the Provider indemnifies the Client for claims.",
        # A negated sentence followed by a positive sentence in the same
        # clause: the positive mention satisfies the rule.
        "There is no indemnification for indirect damages. "
        "The Provider will indemnify the Client for direct claims.",
    ],
)
def test_positive_indemnification_satisfies_required_clause(contract_body):
    contract = f"## 1. Indemnification\n{contract_body}\n"
    result = review_contract(contract, _indemnification_playbook())
    assert [f for f in result.findings if f.rule_id == "require-indemnification"] == []


def test_negated_must_contain_element_is_incomplete():
    pb = parse_playbook(
        "id: conf\nname: Conf\n\n## Rules\n\n"
        "### require-definition\n"
        "title: Definition is required\nkind: required\nseverity: high\n"
        "topic: confidentiality\npatterns: confidential information\n"
        "must_contain: written; oral\n"
        "rationale: The definition must cover written and oral disclosures.\n"
        "fallback: Confidential Information covers written and oral disclosures.\n"
    )
    contract = (
        "## 1. Confidentiality\n"
        "Confidential Information means written information only; "
        "it does not cover oral disclosures.\n"
    )
    result = review_contract(contract, pb)
    hits = [f for f in result.findings if f.rule_id == "require-definition"]
    assert len(hits) == 1
    assert hits[0].status == "incomplete"
    assert "oral" in hits[0].message


def test_negated_forbidden_language_does_not_fire():
    pb = parse_playbook(
        "id: perp\nname: Perp\n\n## Rules\n\n"
        "### forbid-perpetual\n"
        "title: Confidentiality must not be perpetual\nkind: forbidden\n"
        "severity: high\ntopic: confidentiality\npatterns: perpetual\n"
        "rationale: Perpetual duties are outside the approved position.\n"
        "fallback: Duties survive for three years.\n"
    )
    negated = review_contract(
        "## 1. Confidentiality\nConfidentiality shall not be perpetual; "
        "the duty survives for three years.\n",
        pb,
    )
    assert negated.findings == ()
    positive = review_contract(
        "## 1. Confidentiality\nThe confidentiality duty is perpetual.\n", pb
    )
    assert len(positive.findings) == 1
    assert positive.findings[0].status == "forbidden"


def test_negated_preferred_position_is_a_deviation_not_a_match():
    pb = parse_playbook(
        "id: gov2\nname: Gov2\n\n## Rules\n\n"
        "### gov-position\ntitle: Governing law\nkind: fallback\nseverity: medium\n"
        "topic: governing law\npatterns: governed by; governing law\n"
        "preferred: Delaware\nacceptable: New York\n"
        "rationale: Delaware is preferred.\nfallback: Governed by Delaware law.\n"
    )
    contract = (
        "## 1. Governing Law\n"
        "This Agreement is not governed by the laws of the State of Delaware.\n"
    )
    result = review_contract(contract, pb)
    hits = [f for f in result.findings if f.rule_id == "gov-position"]
    assert len(hits) == 1
    assert hits[0].status == "deviation"


# ---------------------------------------------------------------------------
# Fallback-position surfacing in findings
# ---------------------------------------------------------------------------

def test_fallback_acceptable_finding_names_preferred_miss_and_matched_fallback():
    contract = (
        "## 1. Governing Law\n"
        "This Agreement is governed by the laws of the State of New York.\n"
    )
    result = legal_playbook_review(contract, load_playbook(PLAYBOOKS_DIR / "nda.md"))
    hits = [f for f in result.findings if f.rule_id == "governing-law-position"]
    assert len(hits) == 1
    assert hits[0].status == "fallback_acceptable"
    # The finding says the preferred position was missed, names the
    # fallback term that matched, and calls it a fallback position.
    assert "Delaware" in hits[0].message
    assert "New York" in hits[0].message
    assert "fallback" in hits[0].message.lower()
    assert result.to_dict()["summary"]["fallback_acceptable"] == 1


def test_deviation_finding_says_neither_preferred_nor_acceptable_matched():
    result = legal_playbook_review(demo_text(), load_playbook(PLAYBOOKS_DIR / "nda.md"))
    hits = [f for f in result.findings if f.rule_id == "governing-law-position"]
    assert len(hits) == 1
    assert hits[0].status == "deviation"
    assert "Delaware" in hits[0].message
    assert "neither" in hits[0].message.lower() or "no preferred" in hits[0].message.lower()
