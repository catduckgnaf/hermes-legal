"""Public claims in the README and docs must match the code (issue #26)."""
import json
import pathlib
import re

import pytest

from hermes_legal import cli, dispatch, tooldefs

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _row(prefix):
    return next(line for line in README.splitlines() if line.startswith(prefix))


def test_readme_tool_counts_match_the_code():
    spine = _row("| Spine:")
    assert f"({len(tooldefs.TOOLS)} `legal_*` definitions)" in spine
    assert f"{len(dispatch.IMPLS)} of the {len(tooldefs.TOOLS)} tools have implementations" in spine


def test_readme_lists_built_and_unbuilt_tools_exactly():
    row = _row("| Agent tools (`legal_*`)")
    built_text, unbuilt_text = row.split("Defined but not built yet")
    names = {tool.name for tool in tooldefs.TOOLS}
    assert set(re.findall(r"`(legal_\w+)`", built_text)) == set(dispatch.IMPLS)
    assert set(re.findall(r"`(legal_\w+)`", unbuilt_text)) == names - set(dispatch.IMPLS)


def test_agent_tools_doc_names_the_unbuilt_tools_exactly():
    text = (ROOT / "docs" / "agent-tools.md").read_text(encoding="utf-8")
    sentence = re.search(r"(?:are|is) not built yet: ([^\n.]*)\.", text)
    assert sentence, "docs/agent-tools.md should say which tools are not built"
    unbuilt = {tool.name for tool in tooldefs.TOOLS} - set(dispatch.IMPLS)
    assert set(re.findall(r"`(legal_\w+)`", sentence.group(1))) == unbuilt


def test_readme_cli_row_names_only_real_commands(capsys):
    row = _row("| `legal` CLI (")
    listed = set(re.findall(r"`([a-z-]+)`", row.split("(", 1)[1].split(")")[0]))
    assert listed
    for command in sorted(listed):
        with pytest.raises(SystemExit) as exit_info:
            cli.main([command, "--help"])
        assert exit_info.value.code == 0, command
    capsys.readouterr()


def test_readme_desktop_connector_and_deadline_rows_match_the_tree():
    desktop = _row("| Desktop app")
    targets = json.loads(
        (ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )["bundle"]["targets"]
    assert targets == ["nsis", "msi", "appimage", "deb"]
    for label in ("NSIS", "MSI", "deb", "AppImage"):
        assert label in desktop
    assert "not a signed release" in desktop
    assert "live Hermes" in desktop

    connectors = _row("| Connectors")
    for name in ("Clio", "DocuSign", "CourtListener", "PACER"):
        assert name in connectors
    assert "Document download is refused" in connectors

    deadlines = _row("| Deadlines")
    assert "12(a)(1)(A)(ii)" in deadlines
    rules = json.loads(
        (ROOT / "src/hermes_legal/data/rules/frcp-service-response.json").read_text(encoding="utf-8")
    )
    ids = {rule["id"] for rule in rules["rules"]}
    assert "frcp-12a1aii-answer-after-waiver" in ids
    assert "frcp-12a1b-answer-after-waiver" not in ids


def test_templates_carry_no_other_project_text():
    leftovers = re.compile(r"print-handy|slicer|bed bounds|printer|filament|physical operation", re.I)
    paths = [ROOT / "CONTRIBUTING.md", *sorted((ROOT / ".github").glob("*.md")),
             *sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*"))]
    hits = [path.relative_to(ROOT).as_posix() for path in paths
            if leftovers.search(path.read_text(encoding="utf-8"))]
    assert hits == []
