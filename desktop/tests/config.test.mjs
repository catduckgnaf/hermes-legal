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

test("loopback hosts are recognized", async () => {
  const { isLoopbackHost } = await import("../dist/js/config.mjs");
  for (const host of ["127.0.0.1", "localhost", "LOCALHOST", "::1", "127.8.9.10"]) {
    assert.equal(isLoopbackHost(host), true, host);
  }
  for (const host of ["example.test", "203.0.113.5", "127.example.test", ""]) {
    assert.equal(isLoopbackHost(host), false, host);
  }
});

test("config warnings flag a missing token and clear-text remote http", async () => {
  const { configWarnings } = await import("../dist/js/config.mjs");
  assert.deepEqual(configWarnings({ host: "127.0.0.1", token: "k" }), []);
  assert.deepEqual(configWarnings({ scheme: "https", host: "example.test", token: "k" }), []);
  const missing = configWarnings({ host: "127.0.0.1", token: "  " });
  assert.equal(missing.length, 1);
  assert.match(missing[0], /No token set/);
  const remote = configWarnings({ scheme: "http", host: "example.test", token: "k" });
  assert.equal(remote.length, 1);
  assert.match(remote[0], /unencrypted/);
  assert.throws(() => configWarnings({ host: "", token: "k" }), TypeError);
});
