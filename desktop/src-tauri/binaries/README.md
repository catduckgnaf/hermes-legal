# Sidecar binaries

Tauri places the Python sidecar next to the shell binary at bundle time.
The file name in this directory at build time must carry the target triple,
for example:

- `hermes-legal-sidecar-x86_64-pc-windows-msvc.exe` (Windows)
- `hermes-legal-sidecar-x86_64-unknown-linux-gnu` (Linux)
- `hermes-legal-sidecar-aarch64-unknown-linux-gnu` (Linux, ARM64)

The sidecar is the Python core packaged as one executable that provides
the `legal` command line; the shell starts it as `legal serve --port 8770`.
No sidecar binary is committed to this repository: the desktop workflow
creates the per-target file during the build, and `tauri.conf.json`
refers to it as `binaries/hermes-legal-sidecar` under `bundle.externalBin`.

The `.gitkeep` file keeps this directory present in a fresh checkout so
the configuration validates before any build has run.
