//! Tauri 2 shell for hermes-legal.
//!
//! The frontend in `desktop/dist` is the desktop client: it connects
//! from the WebView to the Hermes API server the user configured (see
//! `desktop/PROTOCOL.md`), which is why the content security policy in
//! `tauri.conf.json` allows outbound http/https/ws/wss connections
//! instead of pinning one loopback origin. The shell itself stays
//! minimal and owns no client or legal logic.
//!
//! The shell also starts the Python core as a sidecar process
//! (`legal serve`, which binds 127.0.0.1:8770 only). This provides the
//! local dashboard independently of the Hermes client UI. If the
//! sidecar cannot start, the shell still opens and says so: the Hermes
//! connection and a separately started `legal serve` remain usable.
//!
//! The signed updater plugin is deliberately not registered yet. Tauri's
//! updater verifies every update against a public key held in
//! `tauri.conf.json`; that key is only real once the release signing key
//! exists as a CI secret (see `desktop/packaging.md`). Registering the
//! updater against an empty key would either fail or, worse, train a
//! failure path nobody tests. Registration lands with the first signed
//! release build, together with the `TAURI_SIGNING_PRIVATE_KEY` secret.

use tauri_plugin_shell::ShellExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Spawn the Python sidecar. The binary name matches
            // `bundle.externalBin` in tauri.conf.json; Tauri resolves the
            // target-triple-suffixed file placed next to the shell binary.
            // The desktop workflow packages the real Python core with
            // PyInstaller before this build.
            match app
                .shell()
                .sidecar("hermes-legal-sidecar")
            {
                Ok(command) => {
                    let command = command.args(["serve", "--port", "8770"]);
                    if let Err(err) = command.spawn() {
                        eprintln!(
                            "hermes-legal: Python sidecar failed to start ({err}); \
                             the local dashboard is unavailable in this window, but the \
                             Hermes client and a separately started `legal serve` \
                             are unaffected."
                        );
                    }
                }
                Err(err) => {
                    eprintln!(
                        "hermes-legal: Python sidecar is not bundled in this build \
                         ({err}); see desktop/packaging.md for the packaging steps."
                    );
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the hermes-legal desktop shell");
}
