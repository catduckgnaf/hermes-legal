"""Config validation for the desktop packaging scaffold (issue #7).

These tests parse the Tauri configuration and the packaging manifests
with the standard library only and pin the packaging facts the rest of
the product relies on: bundle targets for both platforms, the Python
sidecar, the Flatpak network permission, the winget installer set, and
a desktop workflow that can never gate a pull request. They also pin
the signing posture: signing is documented as required secrets, and no
certificate or key material is committed anywhere in the scaffold.
"""
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
SRC_TAURI = DESKTOP / "src-tauri"


def tauri_config():
    return json.loads((SRC_TAURI / "tauri.conf.json").read_text())


def project_version():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def test_tauri_config_identity_and_version():
    config = tauri_config()
    assert config["productName"] == "hermes-legal"
    assert config["identifier"] == "com.catduckgnaf.hermes-legal"
    # The bundle version tracks the Python package version.
    assert config["version"] == project_version()


def test_bundle_targets_cover_windows_and_linux_installers():
    targets = set(tauri_config()["bundle"]["targets"])
    # Windows: NSIS and MSI. Linux: AppImage and deb.
    assert {"nsis", "msi", "appimage", "deb"} <= targets


def test_python_sidecar_is_the_only_external_binary():
    bundle = tauri_config()["bundle"]
    assert bundle["externalBin"] == ["binaries/hermes-legal-sidecar"]
    lib = (SRC_TAURI / "src" / "lib.rs").read_text()
    assert "hermes-legal-sidecar" in lib
    assert '"serve"' in lib and "8770" in lib


def test_shell_may_execute_only_the_sidecar():
    capability = json.loads((SRC_TAURI / "capabilities" / "default.json").read_text())
    assert capability["windows"] == ["main"]
    names = [
        entry["name"]
        for permission in capability["permissions"]
        if isinstance(permission, dict)
        for entry in permission.get("allow", [])
    ]
    assert names and set(names) == {"binaries/hermes-legal-sidecar"}


def test_cargo_manifest_is_tauri_2():
    cargo = tomllib.loads((SRC_TAURI / "Cargo.toml").read_text())
    assert cargo["package"]["name"] == "hermes-legal-desktop"
    assert cargo["dependencies"]["tauri"]["version"] == "2"
    assert cargo["build-dependencies"]["tauri-build"]["version"] == "2"


def test_file_associations_for_docx_and_pdf():
    associations = tauri_config()["bundle"]["fileAssociations"]
    extensions = {ext for entry in associations for ext in entry["ext"]}
    assert {"docx", "pdf"} <= extensions


def test_updater_endpoint_points_at_github_releases():
    updater = tauri_config()["plugins"]["updater"]
    assert updater["active"] is True
    assert any(
        endpoint.startswith("https://github.com/catduckgnaf/hermes-legal/releases/")
        for endpoint in updater["endpoints"]
    )


def test_windows_signing_is_configured_not_faked():
    windows = tauri_config()["bundle"]["windows"]
    # The certificate thumbprint stays unset in the repository; signing
    # material arrives through CI secrets at release time.
    assert windows["certificateThumbprint"] is None
    assert windows["digestAlgorithm"] == "sha256"


def test_flatpak_manifest_declares_justified_network_permission():
    manifest = json.loads((DESKTOP / "flatpak" / "com.catduckgnaf.hermeslegal.json").read_text())
    assert manifest["app-id"] == "com.catduckgnaf.hermeslegal"
    assert manifest["command"] == "hermes-legal"
    finish_args = manifest["finish-args"]
    # Network (local model servers and opt-in connectors) and home
    # (matters are ordinary folders) are the load-bearing permissions;
    # both are justified in the Flatpak README for Flathub review.
    assert "--share=network" in finish_args
    assert "--filesystem=home" in finish_args
    readme = (DESKTOP / "flatpak" / "README.md").read_text()
    assert "--share=network" in readme and "LOCAL-ONLY" in readme


def winget_text(name):
    return (DESKTOP / "winget" / name).read_text()


def test_winget_manifest_set_is_consistent():
    version = winget_text("Catduck.HermesLegal.yaml")
    installer = winget_text("Catduck.HermesLegal.installer.yaml")
    locale = winget_text("Catduck.HermesLegal.locale.en-US.yaml")
    for text in (version, installer, locale):
        assert "PackageIdentifier: Catduck.HermesLegal" in text
        assert f"PackageVersion: {project_version()}" in text
        assert "ManifestVersion: 1.6.0" in text
    assert "ManifestType: version" in version
    assert "ManifestType: installer" in installer
    assert "ManifestType: defaultLocale" in locale


def test_winget_installers_are_the_signed_nsis_and_msi():
    installer = winget_text("Catduck.HermesLegal.installer.yaml")
    assert "InstallerType: nullsoft" in installer
    assert "InstallerType: msi" in installer
    # No hash value is committed ahead of a real signed artifact; the
    # publish step computes it. A fabricated hash would fail every
    # install. (The field name appears in an explanatory comment only.)
    assert not re.search(r"^\s+InstallerSha256:", installer, re.M)


def test_desktop_workflow_is_manual_only_and_builds_both_platforms():
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text()
    assert re.search(r"^on:\s*\n\s+workflow_dispatch:", workflow, re.M)
    # The workflow must never gate a pull request.
    assert "pull_request" not in workflow
    assert "windows-latest" in workflow
    assert "ubuntu-latest" in workflow
    # Signing material is referenced as secrets, never as literal values.
    assert "secrets.TAURI_SIGNING_PRIVATE_KEY" in workflow
    assert "secrets.WINDOWS_CERTIFICATE" in workflow


def test_no_signing_material_is_committed():
    checked_suffixes = {".json", ".toml", ".rs", ".yml", ".yaml", ".md", ".html"}
    offenders = []
    for base in (DESKTOP, ROOT / ".github" / "workflows"):
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in checked_suffixes:
                text = path.read_text(errors="ignore")
                if "BEGIN PRIVATE KEY" in text or "BEGIN CERTIFICATE" in text:
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_signing_secrets_are_documented_in_packaging_doc():
    packaging = (DESKTOP / "packaging.md").read_text()
    for secret in (
        "TAURI_SIGNING_PRIVATE_KEY",
        "WINDOWS_CERTIFICATE",
        "AZURE_TRUSTED_SIGNING_ENDPOINT",
    ):
        assert secret in packaging
    assert "never published" in packaging


def test_frontend_placeholder_exists_where_config_expects_it():
    config = tauri_config()
    frontend = (SRC_TAURI / config["build"]["frontendDist"]).resolve()
    index = frontend / "index.html"
    assert index.is_file()
    assert "hermes-legal" in index.read_text()
