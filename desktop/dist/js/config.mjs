// Connection configuration for the Hermes API server.
//
// Protocol facts (see desktop/PROTOCOL.md): the Hermes agent's API server
// (gateway/platforms/api_server.py in NousResearch/hermes-agent) listens on
// 127.0.0.1:8642 by default, is enabled with API_SERVER_ENABLED=true, and
// authenticates with a bearer token taken from API_SERVER_KEY. Android
// clients point at the same host/port/token triple, so this client does too.

export const CONFIG_STORAGE_KEY = "hermes-legal-desktop.connection.v1";

export const DEFAULT_CONFIG = Object.freeze({
  scheme: "http",
  host: "127.0.0.1",
  port: 8642,
  token: "",
});

// Accept a bare host, a host:port pair, or a pasted URL and return a clean
// { scheme, host, port, token }. Throws TypeError on anything unusable so
// the UI can show the problem instead of failing on the first request.
export function normalizeConfig(input = {}) {
  let { scheme, host, port, token } = { ...DEFAULT_CONFIG, ...input };

  if (typeof host === "string") {
    host = host.trim();
    if (host.includes("://")) {
      const url = new URL(host);
      scheme = url.protocol.replace(":", "");
      host = url.hostname;
      if (url.port) port = Number(url.port);
    } else {
      // Strip any path/query a pasted value carried.
      host = host.split("/")[0].split("?")[0];
      const ipv4WithPort = host.match(/^([^:\]]+):(\d+)$/);
      if (ipv4WithPort) {
        host = ipv4WithPort[1];
        port = Number(ipv4WithPort[2]);
      }
    }
  }
  if (typeof host !== "string" || host.length === 0) {
    throw new TypeError("Host is required (for example 127.0.0.1 or a Tailscale name).");
  }
  if (/[\s]/.test(host)) {
    throw new TypeError("Host must not contain spaces.");
  }
  scheme = String(scheme || "http").toLowerCase();
  if (scheme !== "http" && scheme !== "https") {
    throw new TypeError("Scheme must be http or https.");
  }
  port = Number(port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new TypeError("Port must be an integer between 1 and 65535.");
  }
  token = typeof token === "string" ? token.trim() : "";
  return { scheme, host, port, token };
}

export function baseUrl(config) {
  const { scheme, host, port } = normalizeConfig(config);
  const printableHost = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
  return `${scheme}://${printableHost}:${port}`;
}

// Storage is injected so tests can use an in-memory stand-in and the app
// can pass window.localStorage. A missing or corrupt saved value falls
// back to the defaults rather than breaking startup.
export function loadConfig(storage, key = CONFIG_STORAGE_KEY) {
  try {
    const raw = storage?.getItem?.(key);
    if (!raw) return { ...DEFAULT_CONFIG };
    return normalizeConfig(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(storage, config, key = CONFIG_STORAGE_KEY) {
  const clean = normalizeConfig(config);
  storage?.setItem?.(key, JSON.stringify(clean));
  return clean;
}
