"""Config validation for the desktop packaging scaffold (issue #7).

These tests parse the Tauri configuration and the packaging manifests
with the standard library only and pin the packaging facts the rest of
the product relies on: bundle targets for both platforms, no bundled
sidecar and no shell permission, the Flatpak permissions, the winget installer set, and
the desktop workflow (dispatch full build plus the pull-request
Windows smoke build and mock-server client tests). They also pin
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


def test_thin_client_bundles_no_sidecar():
    # Issue #34: the desktop app is a thin client for a running Hermes
    # agent. It bundles and starts no other program (issue #26: a
    # spawned sidecar was never stopped on exit).
    bundle = tauri_config()["bundle"]
    assert "externalBin" not in bundle
    lib = (SRC_TAURI / "src" / "lib.rs").read_text()
    assert "tauri_plugin_shell" not in lib
    assert ".sidecar(" not in lib and ".spawn(" not in lib
    cargo = tomllib.loads((SRC_TAURI / "Cargo.toml").read_text())
    assert "tauri-plugin-shell" not in cargo["dependencies"]


def test_webview_has_no_shell_permission():
    capability = json.loads((SRC_TAURI / "capabilities" / "default.json").read_text())
    assert capability["windows"] == ["main"]
    assert capability["permissions"] == ["core:default", "allow-token-get", "allow-token-set"]


def test_cargo_manifest_is_tauri_2():
    cargo = tomllib.loads((SRC_TAURI / "Cargo.toml").read_text())
    assert cargo["package"]["name"] == "hermes-legal-desktop"
    assert cargo["dependencies"]["tauri"]["version"] == "2"
    assert cargo["build-dependencies"]["tauri-build"]["version"] == "2"


def test_thin_client_has_no_file_associations_or_updater():
    # Issue #86: both were leftovers from the local-first desktop.
    # The thin client does not open local documents, and the updater
    # stays out until a signed release has a real public key.
    bundle = tauri_config()["bundle"]
    assert "fileAssociations" not in bundle
    assert "updater" not in tauri_config().get("plugins", {})
    lib = (SRC_TAURI / "src" / "lib.rs").read_text()
    assert "fn token_get" in lib and "fn token_set" in lib
    assert "plugin_updater" not in lib


def test_windows_signing_is_configured_not_faked():
    windows = tauri_config()["bundle"]["windows"]
    # The certificate thumbprint stays unset in the repository; signing
    # material arrives through CI secrets at release time.
    assert windows["certificateThumbprint"] is None
    assert windows["digestAlgorithm"] == "sha256"


def test_flatpak_manifest_matches_tauri_identifier_and_stays_narrow():
    identifier = tauri_config()["identifier"]
    manifest = json.loads((DESKTOP / "flatpak" / f"{identifier}.json").read_text())
    # One app identifier across Tauri and Flatpak (issue #26).
    assert manifest["app-id"] == identifier
    assert (DESKTOP / "flatpak" / f"{identifier}.desktop").is_file()
    assert manifest["command"] == "hermes-legal"
    finish_args = manifest["finish-args"]
    # Network reaches the Hermes agent the user configured. The thin
    # client touches no user files, so no filesystem grant is allowed.
    assert "--share=network" in finish_args
    assert not [arg for arg in finish_args if arg.startswith("--filesystem")]
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


def test_desktop_workflow_dispatch_and_pr_windows_build():
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text()
    assert re.search(r"^on:\s*\n\s+workflow_dispatch:", workflow, re.M)
    # Pull requests that touch desktop/** run the client tests and an
    # unsigned Windows build (the desktop client direction, issue #34);
    # the dispatched full build keeps both platforms.
    assert "pull_request:" in workflow
    assert '"desktop/**"' in workflow
    assert "build-windows-pr" in workflow
    assert "build-linux-pr" in workflow
    assert "cargo tauri build --bundles nsis,msi" in workflow
    assert "cargo tauri build --bundles deb,appimage" in workflow
    assert "npm test" in workflow
    assert "windows-latest" in workflow
    assert "ubuntu-latest" in workflow
    assert "Swatinem/rust-cache" in workflow
    assert "Silent NSIS install" in workflow
    # Signing material is referenced as secrets, never as literal values.
    assert "secrets.TAURI_SIGNING_PRIVATE_KEY" in workflow
    assert "secrets.WINDOWS_CERTIFICATE" in workflow


def test_desktop_client_frontend_and_tests_exist():
    dist = DESKTOP / "dist"
    index = (dist / "index.html").read_text()
    assert "js/app.mjs" in index
    for module in ("config.mjs", "sse.mjs", "client.mjs", "app.mjs"):
        assert (dist / "js" / module).is_file()
    # The client speaks the researched Hermes API server protocol.
    client = (dist / "js" / "client.mjs").read_text()
    for route in ("/health", "/v1/capabilities", "/api/sessions", "/chat/stream", "/approval"):
        assert route in client
    mock = (DESKTOP / "tests" / "mock-hermes.mjs").read_text()
    assert "approval.request" in mock and "assistant.delta" in mock
    package = json.loads((DESKTOP / "package.json").read_text())
    assert "node --test" in package["scripts"]["test"]


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
