fn main() {
    // App commands are not granted unless they are listed here. Tauri then
    // writes allow-token-get and allow-token-set, which capabilities/default.json
    // references.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["token_get", "token_set"]),
        ),
    )
    .expect("failed to run tauri-build");
}
