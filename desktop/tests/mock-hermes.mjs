// Mock Hermes API server for the desktop client tests.
//
// Implements the researched real protocol (desktop/PROTOCOL.md;
// NousResearch/hermes-agent gateway/platforms/api_server.py) with Node's
// standard library only:
//
//   GET  /health                        public, { status: "ok", platform, version }
//   GET  /v1/capabilities               bearer auth, features + endpoints
//   GET  /api/sessions                  bearer auth, { object: "list", data: [...] }
//   POST /api/sessions                  bearer auth, 201 { object: "hermes.session", session }
//   GET  /api/sessions/{id}/messages    bearer auth, { object: "list", data: [...] }
//   POST /api/sessions/{id}/chat/stream bearer auth, SSE frames with
//        run.started / message.started / assistant.delta /
//        approval.request (for the approval trigger message) /
//        assistant.completed / run.completed / done, plus
//        `: keepalive` comment lines like the real server
//   POST /v1/runs/{run_id}/approval     bearer auth, resolves the pending
//        approval for that run, or 409 approval_not_pending
//
// A chat message containing the trigger word below parks mid-stream on
// an approval.request until the client resolves it, mirroring how the
// real server parks a run in waiting_for_approval.

import { createServer } from "node:http";

export const MOCK_TOKEN = "test-api-server-key";
export const APPROVAL_TRIGGER = "needs-approval";

let seq = 0;

function sseFrame(event, payload) {
  seq += 1;
  return `event: ${event}\ndata: ${JSON.stringify({ event, seq, ...payload })}\n\n`;
}

export function createMockHermes({ token = MOCK_TOKEN, features = {} } = {}) {
  const state = {
    token,
    sessions: [
      {
        id: "sess_alpha",
        title: "Alpha matter",
        source: "api_server",
        model: "hermes-agent",
        message_count: 2,
        last_active: 1731500000,
        preview: "First session",
      },
      {
        id: "sess_beta",
        title: "",
        source: "desktop",
        model: "hermes-agent",
        message_count: 0,
        last_active: 1731500100,
        preview: "",
      },
    ],
    messages: {
      sess_alpha: [
        { id: 1, session_id: "sess_alpha", role: "user", content: "Hello", timestamp: 1731500000 },
        { id: 2, session_id: "sess_alpha", role: "assistant", content: "Hi there.", timestamp: 1731500001 },
      ],
    },
    pendingApprovals: new Map(), // runId -> { resolve, request }
    lastApproval: null,
    createdCount: 0,
  };

  const capabilities = {
    object: "hermes.api_server.capabilities",
    platform: "hermes-agent",
    model: "hermes-agent",
    auth: { type: "bearer", required: true },
    features: {
      chat_completions: true,
      chat_completions_streaming: true,
      run_status: true,
      run_events_sse: true,
      run_approval_response: true,
      approval_events: true,
      session_resources: true,
      session_chat: true,
      session_chat_streaming: true,
      ...features,
    },
    endpoints: {
      health: { method: "GET", path: "/health" },
      sessions: { method: "GET", path: "/api/sessions" },
      session_chat_stream: { method: "POST", path: "/api/sessions/{session_id}/chat/stream" },
      run_approval: { method: "POST", path: "/v1/runs/{run_id}/approval" },
    },
  };

  function sendJson(res, status, body) {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  }

  function sendError(res, status, message, code) {
    sendJson(res, status, { error: { message, code, type: "mock_error" } });
  }

  function authorized(req) {
    return req.headers.authorization === `Bearer ${token}`;
  }

  async function readBody(req) {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const text = Buffer.concat(chunks).toString("utf8");
    return text ? JSON.parse(text) : {};
  }

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://mock.invalid");
    const path = url.pathname;

    if (req.method === "GET" && path === "/health") {
      return sendJson(res, 200, { status: "ok", platform: "hermes-agent", version: "mock-1" });
    }
    if (!authorized(req)) {
      return sendError(res, 401, "Invalid API key", "invalid_api_key");
    }
    if (req.method === "GET" && path === "/v1/capabilities") {
      return sendJson(res, 200, capabilities);
    }
    if (req.method === "GET" && path === "/api/sessions") {
      const limit = Number(url.searchParams.get("limit") ?? 50);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const data = state.sessions.slice(offset, offset + limit);
      return sendJson(res, 200, {
        object: "list",
        data,
        limit,
        offset,
        has_more: offset + data.length < state.sessions.length,
      });
    }
    if (req.method === "POST" && path === "/api/sessions") {
      const body = await readBody(req);
      state.createdCount += 1;
      const session = {
        id: `sess_mock_${state.createdCount}`,
        title: body.title ?? "",
        source: body.source ?? "api_server",
        model: "hermes-agent",
        message_count: 0,
        last_active: 1731500200,
        preview: "",
      };
      state.sessions.unshift(session);
      state.messages[session.id] = [];
      return sendJson(res, 201, { object: "hermes.session", session });
    }

    const messagesMatch = path.match(/^\/api\/sessions\/([^/]+)\/messages$/);
    if (req.method === "GET" && messagesMatch) {
      const id = decodeURIComponent(messagesMatch[1]);
      if (!state.messages[id]) return sendError(res, 404, `Session not found: ${id}`, "session_not_found");
      return sendJson(res, 200, {
        object: "list",
        session_id: id,
        data: state.messages[id],
        pagination: { limit: 500, offset: 0, order: "latest", returned: state.messages[id].length },
      });
    }

    const streamMatch = path.match(/^\/api\/sessions\/([^/]+)\/chat\/stream$/);
    if (req.method === "POST" && streamMatch) {
      const id = decodeURIComponent(streamMatch[1]);
      if (!state.messages[id]) return sendError(res, 404, `Session not found: ${id}`, "session_not_found");
      const body = await readBody(req);
      const text = body.message ?? body.input ?? "";
      const runId = `run_mock_${state.createdCount + 1}_${state.sessions.length}`;
      const messageId = `msg_mock_${runId}`;
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });
      const write = (chunk) => res.write(chunk);
      write(": keepalive\n\n");
      write(sseFrame("run.started", { run_id: runId, session_id: id }));
      write(sseFrame("message.started", { run_id: runId, session_id: id, message: { id: messageId, role: "assistant" } }));

      let suffix = "";
      if (String(text).includes(APPROVAL_TRIGGER)) {
        const request = {
          event: "approval.request",
          run_id: runId,
          session_id: id,
          message_id: messageId,
          command: "remove a generated file",
          description: "The agent wants to run a command that needs approval.",
          choices: ["once", "session", "always", "deny"],
          request_id: `prompt_${runId}`,
          execution_generation: 3,
        };
        write(sseFrame("approval.request", request));
        const decision = await new Promise((resolve) => {
          state.pendingApprovals.set(runId, { resolve, request });
        });
        suffix = decision === "deny" ? " Approval denied; skipped." : ` Approval granted (${decision}).`;
      }

      const reply = `Echo: ${text}${suffix}`;
      const third = Math.ceil(reply.length / 3);
      for (let i = 0; i < reply.length; i += third) {
        write(sseFrame("assistant.delta", {
          run_id: runId,
          session_id: id,
          message_id: messageId,
          delta: reply.slice(i, i + third),
        }));
      }
      write(sseFrame("assistant.completed", {
        run_id: runId,
        session_id: id,
        message_id: messageId,
        content: reply,
        completed: true,
      }));
      write(sseFrame("run.completed", {
        run_id: runId,
        session_id: id,
        message_id: messageId,
        completed: true,
        usage: { input_tokens: 5, output_tokens: 7, total_tokens: 12 },
      }));
      write(sseFrame("done", { run_id: runId, session_id: id }));
      (state.messages[id] ??= []).push(
        { id: Date.now(), session_id: id, role: "user", content: String(text), timestamp: 1731500300 },
        { id: Date.now() + 1, session_id: id, role: "assistant", content: reply, timestamp: 1731500301 },
      );
      return res.end();
    }

    const approvalMatch = path.match(/^\/v1\/runs\/([^/]+)\/approval$/);
    if (req.method === "POST" && approvalMatch) {
      const runId = decodeURIComponent(approvalMatch[1]);
      const body = await readBody(req);
      const pending = state.pendingApprovals.get(runId);
      if (!pending) {
        return sendError(res, 409, `Run has no pending approval: ${runId}`, "approval_not_pending");
      }
      const allowed = pending.request.choices;
      if (!allowed.includes(body.choice)) {
        return sendError(res, 400, `Invalid approval choice; expected one of: ${allowed.join(", ")}`, "invalid_approval_choice");
      }
      if (body.request_id && body.request_id !== pending.request.request_id) {
        return sendError(res, 409, "Approval request_id is stale.", "approval_conflict");
      }
      state.pendingApprovals.delete(runId);
      state.lastApproval = { runId, ...body };
      pending.resolve(body.choice);
      return sendJson(res, 200, {
        object: "hermes.run.approval_response",
        run_id: runId,
        choice: body.choice,
        ...(body.request_id ? { request_id: body.request_id } : {}),
        resolved: 1,
      });
    }

    return sendError(res, 404, `No mock route for ${req.method} ${path}`, "not_found");
  });

  return { server, state, capabilities };
}

// Start on an ephemeral loopback port; resolves with the base URL.
export async function startMockHermes(options = {}) {
  const mock = createMockHermes(options);
  await new Promise((resolve) => mock.server.listen(0, "127.0.0.1", resolve));
  const { port } = mock.server.address();
  return {
    ...mock,
    port,
    config: { scheme: "http", host: "127.0.0.1", port, token: options.token ?? MOCK_TOKEN },
    close: () => new Promise((resolve) => mock.server.close(resolve)),
  };
}
