//! Tauri 2 shell for the hermes-legal desktop client.
//!
//! The frontend in `desktop/dist` is the whole client: it connects from
//! the WebView to the Hermes API server the user configured (see
//! `desktop/PROTOCOL.md`). The shell opens the window and stores the
//! API token. It starts no sidecar and grants no shell permission.
//!
//! `token_get` and `token_set` are the only commands. On Windows they
//! use Credential Manager. On Linux they use a mode-0600 file. See
//! `credentials.rs`.

mod credentials;

#[tauri::command]
fn token_get() -> Result<String, String> {
    credentials::token_get_from(&*credentials::platform_store())
}

#[tauri::command]
fn token_set(token: String) -> Result<(), String> {
    credentials::token_set_on(&*credentials::platform_store(), &token)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![token_get, token_set])
        .run(tauri::generate_context!())
        .expect("error while running the hermes-legal desktop shell");
}
