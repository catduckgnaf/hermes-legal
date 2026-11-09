from hermes_legal.citations import extract_all

def test_extracts_federal_cite():
    assert extract_all("See Mata v. Avianca, 678 F. Supp. 3d 443 (S.D.N.Y. 2023).")

def test_no_cite_no_match():
    assert extract_all("No authority cited here.") == []
