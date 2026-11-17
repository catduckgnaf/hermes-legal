// Packaging and permission consistency for the thin client (issues #26
// and #34). These read the config files only; no build is needed.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const json = (path) => JSON.parse(read(path));

const tauri = json("src-tauri/tauri.conf.json");

test("the webview capability grants core access only, no shell permission", () => {
  const capability = json("src-tauri/capabilities/default.json");
  assert.deepEqual(capability.windows, ["main"]);
  assert.deepEqual(capability.permissions, ["core:default"]);
  assert.doesNotMatch(JSON.stringify(capability.permissions), /shell:|fs:|http:/);
});

test("the shell bundles and spawns no sidecar", () => {
  assert.equal(tauri.bundle.externalBin, undefined);
  const lib = read("src-tauri/src/lib.rs");
  assert.doesNotMatch(lib, /tauri_plugin_shell|\.sidecar\(|\.spawn\(/);
  assert.doesNotMatch(read("src-tauri/Cargo.toml"), /tauri-plugin-shell/);
});

test("Tauri and Flatpak use one app identifier", () => {
  const id = tauri.identifier;
  assert.equal(id, "com.catduckgnaf.hermes-legal");
  assert.ok(existsSync(new URL(`flatpak/${id}.json`, root)));
  assert.ok(existsSync(new URL(`flatpak/${id}.desktop`, root)));
  const manifest = json(`flatpak/${id}.json`);
  assert.equal(manifest["app-id"], id);
  const entry = read(`flatpak/${id}.desktop`).split(/\r?\n/);
  assert.ok(entry.includes(`Icon=${id}`));
  assert.ok(entry.includes(`StartupWMClass=${id}`));
  for (const command of manifest.modules[0]["build-commands"]) {
    assert.doesNotMatch(command, /hermeslegal/);
    assert.doesNotMatch(command, /sidecar/);
  }
});

test("the Flatpak sandbox has network access and no filesystem grant", () => {
  const manifest = json(`flatpak/${tauri.identifier}.json`);
  const args = manifest["finish-args"];
  assert.ok(args.includes("--share=network"));
  assert.deepEqual(args.filter((arg) => arg.startsWith("--filesystem")), []);
});

test("Windows bundle targets and the CSP stay as the client needs them", () => {
  assert.ok(tauri.bundle.targets.includes("nsis"));
  assert.ok(tauri.bundle.targets.includes("msi"));
  const csp = tauri.app.security.csp;
  assert.ok(csp.includes("default-src 'self'"));
  assert.ok(csp.includes("script-src 'self';"));
  assert.doesNotMatch(csp, /script-src[^;]*unsafe/);
});
