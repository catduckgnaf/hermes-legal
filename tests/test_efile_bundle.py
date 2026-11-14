"""Tests for legal_efile_bundle (write-gated, Verify-All gated, paginated PDF bundle)."""
from __future__ import annotations

import io
import json
import pathlib

import pytest

from hermes_legal import citations, db, dispatch, matters, pdf_tools


@pytest.fixture
def efile_env(tmp_path):
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "motion.pdf").write_bytes(
        pdf_tools.build_text_pdf(["Motion for Summary Judgment.", "Second page of motion."])
    )
    (folder / "exhibit_a.pdf").write_bytes(
        pdf_tools.build_text_pdf(["Exhibit A: Contract excerpt."])
    )
    (folder / "uncited_brief.pdf").write_bytes(
        pdf_tools.build_text_pdf(["See Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023)."])
    )
    (folder / "notes.txt").write_text("Not a PDF", encoding="utf-8")

    db_path = tmp_path / "app.db"
    conn = db.connect(db_path)
    matter_id = matters.open_folder_as_matter(conn, folder, name="Bundle Matter", privacy_ceiling="LOCAL_ONLY")
    try:
        yield conn, db_path, folder, matter_id
    finally:
        conn.close()


def test_efile_bundle_validation_without_pypdf(efile_env):
    conn, db_path, _, matter_id = efile_env
    ctx = dispatch.Context(conn=conn, surface="cli", db_path=db_path)

    empty = dispatch.dispatch("legal_efile_bundle", {"matter_id": matter_id, "documents": [], "output": "bundle.pdf"}, ctx)
    assert empty["error"]["code"] == "invalid_arguments"

    non_pdf = dispatch.dispatch("legal_efile_bundle", {"matter_id": matter_id, "documents": ["notes.txt"], "output": "bundle.pdf"}, ctx)
    assert non_pdf["error"]["code"] == "invalid_arguments"

    bad_out = dispatch.dispatch("legal_efile_bundle", {"matter_id": matter_id, "documents": ["motion.pdf"], "output": "bundle.txt"}, ctx)
    assert bad_out["error"]["code"] == "invalid_arguments"

    escape = dispatch.dispatch("legal_efile_bundle", {"matter_id": matter_id, "documents": ["../outside.pdf"], "output": "bundle.pdf"}, ctx)
    assert escape["error"]["code"] == "path_outside_matter"


def test_efile_bundle_unattended_refusal(efile_env):
    pytest.importorskip("pypdf")
    conn, db_path, _, matter_id = efile_env
    unattended = dispatch.Context(conn=conn, surface="cli", unattended=True, db_path=db_path)
    refused = dispatch.dispatch("legal_efile_bundle", {"matter_id": matter_id, "documents": ["motion.pdf"], "output": "bundle.pdf"}, unattended)
    assert refused["error"]["code"] == "refused_unattended"


def test_efile_bundle_blocks_on_unverified_citations_and_builds_on_approval(efile_env):
    pypdf = pytest.importorskip("pypdf")
    conn, db_path, folder, matter_id = efile_env
    ctx = dispatch.Context(conn=conn, surface="cli", db_path=db_path)

    blocked = dispatch.dispatch(
        "legal_efile_bundle",
        {"matter_id": matter_id, "documents": ["uncited_brief.pdf"], "output": "blocked.pdf"},
        ctx,
    )
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "citation_gate_blocked"
    assert not (folder / "blocked.pdf").exists()

    # Propose a clean bundle (no unverified citations): nothing is written until approved.
    proposed = dispatch.dispatch(
        "legal_efile_bundle",
        {"matter_id": matter_id, "documents": ["motion.pdf", "exhibit_a.pdf"], "output": "filing_bundle.pdf"},
        ctx,
    )
    assert proposed["ok"] is True
    assert proposed["result"]["status"] == "pending_approval"
    assert not (folder / "filing_bundle.pdf").exists()

    action_id = proposed["result"]["action_id"]
    approved = dispatch.approve(conn, action_id, "Alice Counsel")
    assert approved["status"] == "executed"
    res = approved["result"]
    assert res["filed"] is False
    assert res["total_pages"] == 3
    assert [d["start_page"] for d in res["documents"]] == [1, 3]
    assert [d["end_page"] for d in res["documents"]] == [2, 3]

    bundle_path = folder / "filing_bundle.pdf"
    manifest_path = folder / "filing_bundle.manifest.json"
    assert bundle_path.is_file()
    assert manifest_path.is_file()
    reader = pypdf.PdfReader(io.BytesIO(bundle_path.read_bytes()))
    assert len(reader.pages) == 3
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["filed"] is False
    assert manifest["total_pages"] == 3

    # Never overwrites existing output.
    second = dispatch.dispatch(
        "legal_efile_bundle",
        {"matter_id": matter_id, "documents": ["motion.pdf"], "output": "filing_bundle.pdf"},
        ctx,
    )
    assert second["error"]["code"] == "output_exists"


def test_efile_bundle_passes_with_verified_citation(efile_env):
    pytest.importorskip("pypdf")
    conn, db_path, folder, matter_id = efile_env
    resolver = citations.OfflineResolver({
        "678 F. Supp. 3d 443": {"status": "exists", "matched_name": "Mata v. Avianca, Inc."}
    })
    ctx = dispatch.Context(conn=conn, surface="cli", db_path=db_path, resolver=resolver)
    proposed = dispatch.dispatch(
        "legal_efile_bundle",
        {"matter_id": matter_id, "documents": ["uncited_brief.pdf"], "output": "verified_bundle.pdf"},
        ctx,
    )
    assert proposed["ok"] is True
    assert proposed["result"]["status"] == "pending_approval"
