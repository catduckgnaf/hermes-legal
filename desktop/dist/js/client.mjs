// Hermes API server client.
//
// Built against the real protocol in NousResearch/hermes-agent,
// gateway/platforms/api_server.py (see desktop/PROTOCOL.md):
//
//   GET  /health                                  -> { status: "ok", platform, version }
//   GET  /v1/capabilities                         -> { features, endpoints, auth, ... }
//   GET  /api/sessions?limit&offset               -> { object: "list", data: [session, ...] }
//   POST /api/sessions                            -> 201 { object: "hermes.session", session }
//   GET  /api/sessions/{id}/messages              -> { object: "list", data: [message, ...] }
//   POST /api/sessions/{id}/chat/stream           -> SSE: run.started, message.started,
//          assistant.delta, assistant.commentary, tool.started/completed/failed,
//          approval.request, assistant.completed, run.completed|failed|cancelled, done
//   POST /v1/runs/{run_id}/approval               -> resolve a pending approval
//
// Every route except /health requires `Authorization: Bearer <API_SERVER_KEY>`.

import { baseUrl, normalizeConfig } from "./config.mjs";
import { SSEParser } from "./sse.mjs";

export class HermesError extends Error {
  constructor(message, { status = 0, code = "" } = {}) {
    super(message);
    this.name = "HermesError";
    this.status = status;
    this.code = code;
  }
}

function errorFromBody(status, body) {
  // The API server answers errors in the OpenAI shape
  // { error: { message, code, type } }; older/plain handlers may use
  // { error: "text" } or { message: "text" }.
  const err = body?.error;
  const message =
    (typeof err === "string" && err) ||
    err?.message ||
    body?.message ||
    `Hermes request failed with HTTP ${status}`;
  const code = (typeof err === "object" && err?.code) || body?.code || "";
  return new HermesError(message, { status, code });
}

export function approvalsSupported(capabilities) {
  // Approvals ride two advertised flags: the run stream emits
  // approval.request events (approval_events, approval.request on the
  // session stream) and POST /v1/runs/{id}/approval resolves them
  // (run_approval_response). Either missing means no prompt UI.
  const features = capabilities?.features ?? {};
  return Boolean(features.run_approval_response ?? features.run_approval) &&
    features.approval_events !== false;
}

export class HermesClient {
  constructor(config, { fetchImpl } = {}) {
    this.config = normalizeConfig(config);
    this.baseUrl = baseUrl(this.config);
    this.fetch = fetchImpl ?? globalThis.fetch;
    if (typeof this.fetch !== "function") {
      throw new TypeError("HermesClient needs a fetch implementation.");
    }
  }

  #headers(extra = {}) {
    const headers = { Accept: "application/json", ...extra };
    if (this.config.token) headers.Authorization = `Bearer ${this.config.token}`;
    return headers;
  }

  async #json(path, options = {}) {
    let response;
    try {
      response = await this.fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers: this.#headers(options.headers),
      });
    } catch (cause) {
      throw new HermesError(`Could not reach Hermes at ${this.baseUrl}: ${cause.message}`, {
        code: "network_error",
      });
    }
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = null;
    }
    if (!response.ok) throw errorFromBody(response.status, body);
    return body;
  }

  // GET /health is the public liveness probe: { status: "ok", ... }.
  async health() {
    return this.#json("/health");
  }

  async capabilities() {
    return this.#json("/v1/capabilities");
  }

  async listSessions({ limit = 50, offset = 0 } = {}) {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    const body = await this.#json(`/api/sessions?${query}`);
    const data = Array.isArray(body) ? body : body?.data ?? [];
    return data.map(normalizeSession);
  }

  async createSession({ title } = {}) {
    const body = await this.#json("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...(title ? { title } : {}), source: "desktop" }),
    });
    return normalizeSession(body?.session ?? body);
  }

  async listMessages(sessionId) {
    const body = await this.#json(
      `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    );
    const data = Array.isArray(body) ? body : body?.data ?? [];
    return data.map((m) => ({
      id: m.id ?? null,
      role: m.role ?? "",
      content: typeof m.content === "string" ? m.content : "",
      timestamp: m.timestamp ?? null,
    }));
  }

  // Resolve one pending approval for a run. The legacy API-server shape
  // is { choice }; a canonical gateway owner also requires the exact
  // request_id (the prompt_id) and execution_generation the approval
  // event / run status carried, so send them when the event gave them.
  async resolveApproval(runId, choice, { requestId, executionGeneration } = {}) {
    const payload = { choice };
    if (requestId) payload.request_id = requestId;
    if (Number.isInteger(executionGeneration)) {
      payload.execution_generation = executionGeneration;
    }
    return this.#json(`/v1/runs/${encodeURIComponent(runId)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  // Stream one turn on a session. Callbacks:
  //   onDelta(text)          incremental assistant text (assistant.delta)
  //   onEvent(name, payload) every SSE event, including approval.request,
  //                          tool.*, assistant.commentary and the terminal
  //                          run.* event; approval answers go through
  //                          resolveApproval() while the stream stays open.
  // Resolves with { content, runId, status } from the terminal event,
  // where status is "completed", "failed" or "cancelled". Comment
  // keepalive lines are consumed by the parser and never surface.
  async chatStream(sessionId, text, { onDelta, onEvent, signal } = {}) {
    let response;
    try {
      response = await this.fetch(
        `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/chat/stream`,
        {
          method: "POST",
          headers: this.#headers({
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          }),
          body: JSON.stringify({ message: text }),
          signal,
        },
      );
    } catch (cause) {
      if (cause?.name === "AbortError") throw cause;
      throw new HermesError(`Could not reach Hermes at ${this.baseUrl}: ${cause.message}`, {
        code: "network_error",
      });
    }
    if (!response.ok) {
      const bodyText = await response.text().catch(() => "");
      let body = null;
      try {
        body = JSON.parse(bodyText);
      } catch {
        body = null;
      }
      throw errorFromBody(response.status, body);
    }
    if (!response.body) throw new HermesError("Streaming response had no body.");

    const parser = new SSEParser();
    const decoder = new TextDecoder();
    const reader = response.body.getReader();
    let content = "";
    let completedContent = null;
    let runId = null;
    let status = null;

    const handle = (events) => {
      for (const evt of events) {
        if (evt.data === "[DONE]") continue;
        const payload = evt.json ?? {};
        const name = payload.event ?? evt.event;
        if (payload.run_id) runId = payload.run_id;
        onEvent?.(name, payload);
        if (name === "assistant.delta" && typeof payload.delta === "string") {
          content += payload.delta;
          onDelta?.(payload.delta, content);
        } else if (name === "assistant.completed" && typeof payload.content === "string") {
          completedContent = payload.content;
        } else if (
          name === "run.completed" ||
          name === "run.failed" ||
          name === "run.cancelled"
        ) {
          status = name.slice("run.".length);
        } else if (name === "error") {
          throw new HermesError(payload.message || "Hermes reported a stream error.", {
            code: "stream_error",
          });
        }
      }
    };

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      handle(parser.push(decoder.decode(value, { stream: true })));
    }
    handle(parser.end());
    // assistant.completed carries the authoritative final text; deltas
    // are the incremental rendering of the same text.
    if (completedContent !== null) content = completedContent;
    return { content, runId, status: status ?? (content ? "completed" : "failed") };
  }
}

export function normalizeSession(raw = {}) {
  return {
    id: raw.id ?? "",
    title: raw.title ?? "",
    source: raw.source ?? "",
    model: raw.model ?? "",
    messageCount: raw.message_count ?? 0,
    lastActive: raw.last_active ?? raw.ended_at ?? raw.started_at ?? null,
    preview: raw.preview ?? "",
  };
}
