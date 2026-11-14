import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_CONFIG,
  baseUrl,
  loadConfig,
  normalizeConfig,
  saveConfig,
} from "../dist/js/config.mjs";

function memoryStorage() {
  const map = new Map();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => map.set(k, v),
  };
}

test("defaults point at the API server default port 8642", () => {
  assert.deepEqual(normalizeConfig({}), { ...DEFAULT_CONFIG });
  assert.equal(baseUrl(DEFAULT_CONFIG), "http://127.0.0.1:8642");
});

test("a pasted URL is split into scheme, host and port", () => {
  const config = normalizeConfig({ host: "https://hermes.example.test:9443/v1" });
  assert.deepEqual(config, {
    scheme: "https",
    host: "hermes.example.test",
    port: 9443,
    token: "",
  });
  assert.equal(baseUrl(config), "https://hermes.example.test:9443");
});

test("a host:port pair is split", () => {
  const config = normalizeConfig({ host: "100.64.0.5:8642" });
  assert.equal(config.host, "100.64.0.5");
  assert.equal(config.port, 8642);
});

test("invalid ports and schemes are rejected", () => {
  assert.throws(() => normalizeConfig({ port: 0 }), TypeError);
  assert.throws(() => normalizeConfig({ port: 70000 }), TypeError);
  assert.throws(() => normalizeConfig({ port: "abc" }), TypeError);
  assert.throws(() => normalizeConfig({ scheme: "ftp" }), TypeError);
  assert.throws(() => normalizeConfig({ host: " " }), TypeError);
});

test("IPv6 hosts are bracketed in the base URL", () => {
  assert.equal(baseUrl({ host: "::1", port: 8642 }), "http://[::1]:8642");
});

test("save and load round-trip through injected storage", () => {
  const storage = memoryStorage();
  const saved = saveConfig(storage, {
    scheme: "http",
    host: "my-tailscale-host",
    port: 8642,
    token: "secret-key",
  });
  assert.deepEqual(loadConfig(storage), saved);
  assert.equal(loadConfig(storage).token, "secret-key");
});

test("corrupt saved config falls back to the defaults", () => {
  const storage = memoryStorage();
  storage.setItem("hermes-legal-desktop.connection.v1", "{not json");
  assert.deepEqual(loadConfig(storage), { ...DEFAULT_CONFIG });
});
