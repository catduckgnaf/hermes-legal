//! Tauri 2 shell for the hermes-legal desktop client.
//!
//! The frontend in `desktop/dist` is the whole client: it connects from
//! the WebView to the Hermes API server the user configured (see
//! `desktop/PROTOCOL.md`), which is why the content security policy in
//! `tauri.conf.json` allows outbound http/https connections instead of
//! pinning one loopback origin.
//!
//! The shell is a thin client host. It opens the window and nothing
//! else: no sidecar, no child process, no shell plugin, no commands.
//! Because nothing is spawned, there is nothing to stop on exit. See
//! `docs/desktop-groundwork.md` for the security model and the plan to
//! add two narrow token-storage commands later.
//!
//! The signed updater plugin is deliberately not registered yet. It
//! lands with the first signed release build (see `desktop/packaging.md`).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the hermes-legal desktop shell");
}
