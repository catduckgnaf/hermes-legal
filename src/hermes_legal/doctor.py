"""`legal doctor` runs offline and reports every integration as ok, missing,
off, or warn. 'off' is a deliberate setting and never fails the run.

Doctor also carries the privacy warnings: a cloud provider whose
terms-checked date is stale, and a STANDARD-tier provider selected for a
matter whose ceiling is LOCAL_ONLY. Warnings are reported as ``warn`` lines
and never counted as missing integrations.
"""
import shutil, sys
from datetime import date

from . import providers as providers_module

CHECKS = [
    ("Python 3.12+", lambda: sys.version_info >= (3, 12), "Install Python 3.12 or newer."),
    ("LibreOffice (DOCX to PDF, fallback editor)", lambda: bool(shutil.which("soffice")), "Install LibreOffice, or use ONLYOFFICE as the editor."),
    ("ONLYOFFICE (OOXML-native editing)", lambda: bool(shutil.which("onlyoffice") or shutil.which("desktopeditors")), "Optional: LibreOffice covers editing; ONLYOFFICE gives the closest Word fidelity."),
    ("Tesseract OCR", lambda: bool(shutil.which("tesseract")), "Install Tesseract for scanned documents."),
    ("Ollama (local models)", lambda: bool(shutil.which("ollama")), "Install Ollama or LM Studio for LOCAL-ONLY inference. Without one, no AI features run — by design."),
    ("CourtListener token", lambda: False, "Optional: add a free CourtListener token in Settings for citation verification."),
]


def privacy_warnings(today=None, *, selected_provider=None, matter_ceiling=None,
                       catalog=None, stale_after_days=providers_module.STALE_AFTER_DAYS):
    """Privacy warnings for doctor: stale terms and ceiling conflicts.

    - Every cloud provider whose terms-checked date is older than
      ``stale_after_days`` earns a warning naming the provider, the date,
      and its age in days.
    - A STANDARD-tier provider selected for a LOCAL_ONLY-ceiling matter
      earns a warning: the router will refuse that call, and on a
      privileged matter the selection itself is the thing to fix.
    - A BLOCKED-tier selection warns at every ceiling.
    """
    today = today or date.today()
    warnings = []
    for provider in providers_module.stale_providers(
        today, stale_after_days=stale_after_days, providers=catalog
    ):
        age = providers_module.terms_age_days(provider, today)
        warnings.append(
            f"Privacy terms for {provider.name} were last checked "
            f"{provider.terms_checked} ({age} days ago, limit "
            f"{stale_after_days}); re-verify the terms before relying on "
            f"this {provider.tier} provider."
        )
    if selected_provider is not None and matter_ceiling is not None:
        provider = providers_module.find_provider(selected_provider)
        ceiling = providers_module.validate_ceiling(matter_ceiling)
        if provider.tier == "BLOCKED" or provider.trains_on_data:
            warnings.append(
                f"{provider.name} is in the BLOCKED tier and cannot be used "
                f"for client work; the router refuses it at every ceiling, "
                f"including this matter's {ceiling} ceiling."
            )
        elif provider.tier == "STANDARD" and ceiling == "LOCAL_ONLY":
            warnings.append(
                f"{provider.name} is a STANDARD-tier provider selected for "
                "a LOCAL_ONLY matter; the router will refuse it — use a "
                "local provider or raise the matter ceiling with informed "
                "client consent first."
            )
        elif not providers_module.allowed(provider, ceiling):
            warnings.append(
                f"{provider.name} is {provider.tier}, above the matter "
                f"ceiling {ceiling}; the router will refuse it."
            )
    return warnings


def run(today=None, *, selected_provider=None, matter_ceiling=None, catalog=None):
    lines, missing = [], 0
    for name, ok_fn, hint in CHECKS:
        try: ok = bool(ok_fn())
        except Exception: ok = False
        lines.append(f"{'ok     ' if ok else 'missing'}  {name}" + ("" if ok else f" — {hint}"))
        missing += 0 if ok else 1
    for warning in privacy_warnings(
        today, selected_provider=selected_provider,
        matter_ceiling=matter_ceiling, catalog=catalog,
    ):
        lines.append(f"warn     {warning}")
    return lines, missing
