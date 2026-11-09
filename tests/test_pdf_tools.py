import pytest

from hermes_legal.pdf_tools import (BatesConfig, DocumentText, apply_redaction_to_text,
                                    extract_text_layer, format_bates_label, locate_redactions,
                                    plan_bates_stamps, verify_redaction)

SECRET = "Jane Roe, SSN 123-45-6789"


def _doc():
    return DocumentText.from_texts([
        "Public paragraph. " + SECRET + " appears here.",
        "Second page repeats " + SECRET + ".",
        "Nothing sensitive on this page.",
    ])


# --- Bates plan ---

def test_bates_labels_are_consecutive_and_padded():
    stamps = plan_bates_stamps(3, BatesConfig(prefix="ACME-", start=42))
    assert [s.label for s in stamps] == ["ACME-000042", "ACME-000043", "ACME-000044"]
    assert [s.page_number for s in stamps] == [1, 2, 3]


def test_bates_default_config():
    stamps = plan_bates_stamps(2)
    assert [s.label for s in stamps] == ["000001", "000002"]
    assert format_bates_label(7, BatesConfig(prefix="X/", suffix="/Y", digits=3)) == "X/007/Y"


def test_bates_plan_is_deterministic_and_unique():
    plan = plan_bates_stamps(50, BatesConfig(prefix="P-"))
    assert plan == plan_bates_stamps(50, BatesConfig(prefix="P-"))
    assert len({s.label for s in plan}) == 50


def test_bates_rejects_bad_config():
    with pytest.raises(ValueError):
        BatesConfig(start=-1)
    with pytest.raises(ValueError):
        plan_bates_stamps(-1)


# --- redaction: locate, remove, verify (the acceptance-criterion logic) ---

def test_locate_finds_every_occurrence_by_page():
    plan = locate_redactions(_doc(), [SECRET])
    assert plan.pages_affected == [1, 2]
    assert len(plan.hits) == 2


def test_redacted_text_contains_none_of_the_secret_on_reextraction():
    redacted = apply_redaction_to_text(_doc(), [SECRET])
    verification = verify_redaction(redacted, [SECRET])
    assert verification.passed
    assert SECRET not in redacted.full_text()
    assert "[REDACTED]" in redacted.full_text()


def test_unredacted_document_fails_verification():
    verification = verify_redaction(_doc(), [SECRET])
    assert not verification.passed
    assert verification.remaining


def test_verification_catches_case_variant_left_behind():
    doc = DocumentText.from_texts(["jane roe, ssn 123-45-6789 was lowercased."])
    verification = verify_redaction(doc, [SECRET])
    assert not verification.passed


def test_verification_catches_phrase_split_by_line_break():
    doc = DocumentText.from_texts(["Jane Roe, SSN\n123-45-6789 was split."])
    verification = verify_redaction(doc, [SECRET])
    assert not verification.passed
    assert SECRET in verification.normalized_remaining


def test_overlapping_phrases_leave_no_fragment():
    doc = DocumentText.from_texts(["The code is ABCDEFG today."])
    redacted = apply_redaction_to_text(doc, ["ABC", "ABCDEFG"])
    assert "ABCDEFG" not in redacted.full_text()
    assert "ABC" not in redacted.full_text()


def test_redaction_of_absent_phrase_is_a_noop_that_still_verifies():
    doc = DocumentText.from_texts(["Clean page."])
    redacted = apply_redaction_to_text(doc, ["not present"])
    assert redacted.full_text() == "Clean page."
    assert verify_redaction(redacted, ["not present"]).passed


# --- optional pypdf extraction ---

def test_extract_text_layer_without_pypdf_or_with_it():
    pypdf = pytest.importorskip("pypdf")
    import io
    writer = pypdf.PdfWriter()
    writer.add_blank_page(612, 792)
    buf = io.BytesIO()
    writer.write(buf)
    doc = extract_text_layer(buf.getvalue())
    assert doc.page_count == 1
