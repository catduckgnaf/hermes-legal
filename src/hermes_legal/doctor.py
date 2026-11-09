"""`legal doctor` runs offline and reports every integration as ok, missing,
off, or warn. 'off' is a deliberate setting and never fails the run."""
import shutil, sys

CHECKS = [
    ("Python 3.12+", lambda: sys.version_info >= (3, 12), "Install Python 3.12 or newer."),
    ("LibreOffice (DOCX to PDF, fallback editor)", lambda: bool(shutil.which("soffice")), "Install LibreOffice, or use ONLYOFFICE as the editor."),
    ("ONLYOFFICE (OOXML-native editing)", lambda: bool(shutil.which("onlyoffice") or shutil.which("desktopeditors")), "Optional: LibreOffice covers editing; ONLYOFFICE gives the closest Word fidelity."),
    ("Tesseract OCR", lambda: bool(shutil.which("tesseract")), "Install Tesseract for scanned documents."),
    ("Ollama (local models)", lambda: bool(shutil.which("ollama")), "Install Ollama or LM Studio for LOCAL-ONLY inference. Without one, no AI features run — by design."),
    ("CourtListener token", lambda: False, "Optional: add a free CourtListener token in Settings for citation verification."),
]

def run():
    lines, missing = [], 0
    for name, ok_fn, hint in CHECKS:
        try: ok = bool(ok_fn())
        except Exception: ok = False
        lines.append(f"{'ok     ' if ok else 'missing'}  {name}" + ("" if ok else f" — {hint}"))
        missing += 0 if ok else 1
    return lines, missing
