"""Tests for legal_chronology and legal_intake_summary through dispatch."""
from __future__ import annotations

import pytest

from hermes_legal import db, dispatch, matters


@pytest.fixture
def matter_env(tmp_path):
    folder = tmp_path / "matter"
    folder.mkdir()
    (folder / "01_intake.txt").write_text(
        "Client: Jane Doe\n"
        "Opposing Party: Acme Corp.\n"
        "Claim: Breach of contract\n"
        "On January 15, 2026, the parties signed the agreement for $50,000.\n"
        "See Mata v. Avianca, Inc., 678 F. Supp. 3d 443 (S.D.N.Y. 2023).\n",
        encoding="utf-8",
    )
    (folder / "02_order.md").write_text(
        "Court entered scheduling order on 2025-11-02.\n"
        "Initial demand sent 03/01/2026 for $12,500.00.\n",
        encoding="utf-8",
    )
    (folder / "scan.bin").write_bytes(b"\x00\x01\x02\x03")

    db_path = tmp_path / "app.db"
    conn = db.connect(db_path)
    matter_id = matters.open_folder_as_matter(conn, folder, name="Doe v. Acme", privacy_ceiling="LOCAL_ONLY")
    try:
        yield conn, db_path, matter_id
    finally:
        conn.close()


def test_chronology_sorts_across_documents_and_cites_sources(matter_env):
    conn, db_path, matter_id = matter_env
    ctx = dispatch.Context(conn=conn, surface="cli", db_path=db_path)
    out = dispatch.dispatch("legal_chronology", {"matter_id": matter_id}, ctx)
    assert out["ok"] is True
    res = out["result"]
    dates = [e["date"] for e in res["entries"]]
    assert dates == ["2025-11-02", "2026-01-15", "2026-03-01"]
    assert res["total_found"] == 3
    assert res["entries"][0]["source"] == "02_order.md"
    assert res["entries"][0]["citation"] == "02_order.md (line 1)"
    assert res["entries"][1]["source"] == "01_intake.txt"
    assert "scan.bin" in res["unreadable_files"]


def test_chronology_respects_path_limit_and_traversal(matter_env):
    conn, db_path, matter_id = matter_env
    ctx = dispatch.Context(conn=conn, surface="cli", db_path=db_path)

    limited = dispatch.dispatch("legal_chronology", {"matter_id": matter_id, "limit": 1}, ctx)
    assert limited["ok"] is True
    assert len(limited["result"]["entries"]) == 1
    assert limited["result"]["total_found"] == 3

    single = dispatch.dispatch("legal_chronology", {"matter_id": matter_id, "path": "01_intake.txt"}, ctx)
    assert single["ok"] is True
    assert [e["date"] for e in single["result"]["entries"]] == ["2026-01-15"]

    escape = dispatch.dispatch("legal_chronology", {"matter_id": matter_id, "path": "../outside.txt"}, ctx)
    assert escape["ok"] is False
    assert escape["error"]["code"] == "path_outside_matter"


def test_intake_summary_extracts_fields_amounts_dates_and_missing(matter_env):
    conn, db_path, matter_id = matter_env
    ctx = dispatch.Context(conn=conn, surface="cli", db_path=db_path)
    out = dispatch.dispatch("legal_intake_summary", {"matter_id": matter_id}, ctx)
    assert out["ok"] is True
    res = out["result"]
    assert res["matter"]["name"] == "Doe v. Acme"
    assert res["fields"]["client"]["value"] == "Jane Doe"
    assert res["fields"]["opposing_party"]["value"] == "Acme Corp."
    assert res["fields"]["claim"]["value"] == "Breach of contract"
    assert [a["amount"] for a in res["amounts"]] == ["$50,000", "$12,500.00"]
    assert [d["date"] for d in res["dates"]] == ["2025-11-02", "2026-01-15", "2026-03-01"]
    assert res["citations_found"] >= 1
    assert res["missing_intake_fields"] == ["jurisdiction"]
    assert "scan.bin" in res["unreadable_files"]


@pytest.mark.parametrize("tool_name", ["legal_chronology", "legal_intake_summary"])
def test_chronology_and_intake_enforce_privacy_ceiling_on_mcp(matter_env, tool_name):
    conn, db_path, matter_id = matter_env

    undeclared = dispatch.Context(conn=conn, surface="mcp", agent_tier=None, db_path=db_path)
    assert dispatch.dispatch(tool_name, {"matter_id": matter_id}, undeclared)["error"]["code"] == "agent_tier_undeclared"

    cloud = dispatch.Context(conn=conn, surface="mcp", agent_tier="STANDARD", db_path=db_path)
    assert dispatch.dispatch(tool_name, {"matter_id": matter_id}, cloud)["error"]["code"] == "privacy_ceiling"

    local = dispatch.Context(conn=conn, surface="mcp", agent_tier="LOCAL_ONLY", db_path=db_path)
    assert dispatch.dispatch(tool_name, {"matter_id": matter_id}, local)["ok"] is True
