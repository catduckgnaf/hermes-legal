from hermes_legal.tooldefs import TOOLS, TOOL_NAMES, WRITE_TOOLS, describe_write

def test_tool_names_unique():
    assert len(TOOL_NAMES) == len(set(TOOL_NAMES))

def test_every_tool_described():
    assert all(t.description for t in TOOLS)

def test_filing_is_a_write():
    assert "legal_efile_bundle" in WRITE_TOOLS

def test_reads_are_not_writes():
    assert "legal_cite_check" not in WRITE_TOOLS

def test_write_descriptions_never_empty():
    assert describe_write("legal_doc_redline", {"path": "a.docx"})
