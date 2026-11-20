// Browser wiring for the desktop client. All protocol logic lives in
// client.mjs / config.mjs / sse.mjs and is tested against a mock server;
// this file only connects that logic to the page.

import { HermesClient, approvalsSupported } from "./client.mjs";
import { configWarnings, loadConnection, saveConnection } from "./config.mjs";
import { HealthMonitor } from "./health.mjs";

const $ = (id) => document.getElementById(id);
const SESSION_PAGE = 50;

const els = {
  scheme: $("scheme"),
  host: $("host"),
  port: $("port"),
  token: $("token"),
  connect: $("connect"),
  statusDot: $("status-dot"),
  statusText: $("status-text"),
  approvalNote: $("approval-note"),
  refreshSessions: $("refresh-sessions"),
  loadMore: $("load-more"),
  newSession: $("new-session"),
  sessions: $("session-list"),
  messages: $("messages"),
  composer: $("composer"),
  input: $("input"),
  send: $("send"),
  stop: $("stop"),
  approval: $("approval"),
  approvalText: $("approval-text"),
  approvalChoices: $("approval-choices"),
  error: $("error"),
};

let client = null;
let capabilities = null;
let currentSessionId = null;
let pendingApproval = null;
let monitor = null;
let loadedSessions = [];
let sessionOffset = 0;
let streaming = false;
let activeRunId = null;
let streamAbort = null;

function detectTokenStore() {
  const invoke = globalThis.__TAURI__?.core?.invoke;
  if (typeof invoke !== "function") return null;
  return {
    async getToken() {
      const value = await invoke("token_get");
      return typeof value === "string" ? value : "";
    },
    async setToken(token) {
      await invoke("token_set", { token });
    },
  };
}

const tokenStore = detectTokenStore();

function showError(message) {
  els.error.textContent = message || "";
  els.error.hidden = !message;
}

function setStatus(kind, text) {
  els.statusDot.dataset.state = kind;
  els.statusText.textContent = text;
}

function setComposerEnabled(on) {
  const locked = streaming || !on;
  els.input.disabled = locked;
  els.send.disabled = locked;
  els.stop.disabled = !streaming;
}

function readForm() {
  return {
    scheme: els.scheme.value,
    host: els.host.value,
    port: Number(els.port.value),
    token: els.token.value,
  };
}

function fillForm(config) {
  els.scheme.value = config.scheme;
  els.host.value = config.host;
  els.port.value = String(config.port);
  els.token.value = config.token;
}

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `message ${role}`;
  const label = document.createElement("div");
  label.className = "message-role";
  label.textContent = role === "user" ? "You" : role === "tool" ? "Tool" : "Hermes";
  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;
  row.append(label, body);
  els.messages.append(row);
  els.messages.scrollTop = els.messages.scrollHeight;
  return body;
}

function renderSessions(sessions) {
  els.sessions.replaceChildren();
  for (const session of sessions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "session";
    if (session.id === currentSessionId) item.classList.add("active");
    const title = document.createElement("span");
    title.className = "session-title";
    title.textContent = session.title || session.preview || session.id;
    const meta = document.createElement("span");
    meta.className = "session-meta";
    meta.textContent = `${session.messageCount} messages`;
    item.append(title, meta);
    item.addEventListener("click", () => {
      selectSession(session.id).catch((err) => showError(err.message));
    });
    els.sessions.append(item);
  }
  if (sessions.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No sessions yet. Start a new one.";
    els.sessions.append(empty);
  }
}

function watchHealth(activeClient) {
  monitor?.stop();
  monitor = new HealthMonitor(activeClient, {
    onChange: ({ state, retryInMs, health }) => {
      if (client !== activeClient) return;
      if (state === "ok") {
        setStatus("ok", `Connected. Hermes ${health?.version ?? ""} at ${activeClient.baseUrl}`.trim());
        if (!streaming) setComposerEnabled(true);
      } else if (state === "rejected") {
        setStatus("rejected", "Token rejected. The server is up, but this API key was refused.");
        setComposerEnabled(false);
      } else {
        setStatus(
          "error",
          `Connection lost. Retrying in ${Math.max(1, Math.round(retryInMs / 1000))} s.`,
        );
        setComposerEnabled(false);
      }
    },
  });
  monitor.start();
}

async function refreshSessions({ append = false } = {}) {
  if (!client) return;
  if (!append) {
    sessionOffset = 0;
    loadedSessions = [];
  }
  const page = await client.listSessionsPage({ limit: SESSION_PAGE, offset: sessionOffset });
  loadedSessions = append ? loadedSessions.concat(page.sessions) : page.sessions;
  sessionOffset = loadedSessions.length;
  renderSessions(loadedSessions);
  els.loadMore.hidden = !page.hasMore;
}

async function selectSession(sessionId) {
  if (!client) return;
  showError("");
  try {
    currentSessionId = sessionId;
    els.messages.replaceChildren();
    hideApproval();
    const messages = await client.listMessages(sessionId);
    for (const message of messages) {
      if (message.role === "user" || message.role === "assistant") {
        addMessage(message.role, message.content);
      }
    }
    await refreshSessions();
  } catch (err) {
    showError(err.message);
  }
}

function showApproval(payload) {
  pendingApproval = payload;
  els.approval.hidden = false;
  const parts = [payload.description, payload.command].filter(Boolean);
  els.approvalText.textContent =
    parts.join("\n") || "Hermes is waiting for an approval decision.";
  els.approvalChoices.replaceChildren();
  for (const choice of payload.choices ?? ["once", "deny"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = choice;
    button.className = choice === "deny" ? "danger" : "";
    button.addEventListener("click", () => answerApproval(choice));
    els.approvalChoices.append(button);
  }
}

function hideApproval() {
  pendingApproval = null;
  els.approval.hidden = true;
  els.approvalChoices.replaceChildren();
}

async function answerApproval(choice) {
  if (!client || !pendingApproval) return;
  const payload = pendingApproval;
  hideApproval();
  try {
    await client.resolveApproval(payload.run_id, choice, {
      requestId: payload.request_id ?? payload.prompt_id,
      executionGeneration: payload.execution_generation,
    });
  } catch (err) {
    showError(`Approval answer failed: ${err.message}`);
  }
}

async function connect() {
  showError("");
  let config;
  try {
    config = await saveConnection(window.localStorage, tokenStore, readForm());
  } catch (err) {
    setStatus("error", "Check the connection settings.");
    showError(err.message);
    return;
  }
  monitor?.stop();
  client = new HermesClient(config);
  setStatus("pending", "Connecting…");
  setComposerEnabled(false);
  try {
    const health = await client.health();
    try {
      capabilities = await client.probeAuth();
    } catch (err) {
      if (err.status === 401) {
        setStatus("rejected", "Token rejected. The server is up, but this API key was refused.");
        showError(err.message);
        setComposerEnabled(false);
        watchHealth(client);
        return;
      }
      throw err;
    }
    setStatus(
      "ok",
      `Connected — Hermes ${health.version ?? ""} at ${client.baseUrl}`.trim(),
    );
    setComposerEnabled(true);
    if (capabilities && approvalsSupported(capabilities)) {
      els.approvalNote.textContent =
        "Approvals: this server advertises approval events and the run approval endpoint, so approval prompts are shown here.";
    } else {
      els.approvalNote.textContent =
        "Approvals: this server does not advertise approval support in /v1/capabilities, so no approval prompts will be shown. Runs that need approval will park on the server until another client answers.";
    }
    const warnings = configWarnings(config);
    if (warnings.length > 0) {
      els.approvalNote.textContent += ` Warning: ${warnings.join(" ")}`;
    }
    watchHealth(client);
    await refreshSessions();
    if (!currentSessionId && loadedSessions.length > 0) {
      await selectSession(loadedSessions[0].id);
    }
  } catch (err) {
    monitor?.stop();
    client = null;
    setStatus("error", "Not connected.");
    setComposerEnabled(false);
    showError(err.message);
  }
}

async function stopStream() {
  streamAbort?.abort();
  if (client && activeRunId) {
    try {
      await client.stopRun(activeRunId);
    } catch (err) {
      showError(`Stop failed: ${err.message}`);
    }
  }
}

async function send(event) {
  event.preventDefault();
  const text = els.input.value.trim();
  if (!text || !client || streaming) return;
  showError("");
  try {
    if (!currentSessionId) {
      const created = await client.createSession({});
      currentSessionId = created.id;
      await refreshSessions();
    }
  } catch (err) {
    showError(err.message);
    return;
  }
  els.input.value = "";
  const body = addMessage("user", text);
  const assistant = addMessage("assistant", "");
  void body;
  streaming = true;
  activeRunId = null;
  streamAbort = new AbortController();
  setComposerEnabled(false);
  try {
    const result = await client.chatStream(currentSessionId, text, {
      signal: streamAbort.signal,
      onDelta: (_delta, full) => {
        assistant.textContent = full;
        els.messages.scrollTop = els.messages.scrollHeight;
      },
      onEvent: (name, payload) => {
        if (payload?.run_id) activeRunId = payload.run_id;
        if (name === "approval.request") {
          setStatus("pending", "Waiting for your approval decision…");
          showApproval(payload);
        } else if (name === "request.cancel") {
          hideApproval();
        } else if (name.startsWith("tool.")) {
          addMessage("tool", `${name}: ${payload.tool_name ?? payload.tool ?? ""}`.trim());
        } else if (name === "run.completed") {
          setStatus("ok", `Connected — Hermes at ${client.baseUrl}`);
        }
      },
    });
    assistant.textContent = result.content;
    if (result.status === "interrupted") {
      showError("The reply was interrupted before Hermes finished. Reloading the session.");
      await selectSession(currentSessionId);
    } else if (result.status !== "completed") {
      showError(`The run ended with status: ${result.status}`);
    }
  } catch (err) {
    if (err?.name === "AbortError") {
      showError("Stopped.");
      if (currentSessionId) await selectSession(currentSessionId);
    } else {
      showError(err.message);
    }
  } finally {
    streaming = false;
    activeRunId = null;
    streamAbort = null;
    setComposerEnabled(els.statusDot.dataset.state === "ok");
    refreshSessions().catch((err) => showError(err.message));
  }
}

loadConnection(window.localStorage, tokenStore).then((config) => {
  fillForm(config);
  setComposerEnabled(false);
});
els.connect.addEventListener("click", () => {
  connect().catch((err) => showError(err.message));
});
els.refreshSessions.addEventListener("click", () =>
  refreshSessions().catch((err) => showError(err.message)),
);
els.loadMore.addEventListener("click", () =>
  refreshSessions({ append: true }).catch((err) => showError(err.message)),
);
els.newSession.addEventListener("click", async () => {
  if (!client) return;
  showError("");
  try {
    const created = await client.createSession({});
    currentSessionId = created.id;
    els.messages.replaceChildren();
    await refreshSessions();
  } catch (err) {
    showError(err.message);
  }
});
els.composer.addEventListener("submit", (event) => {
  send(event).catch((err) => showError(err.message));
});
els.stop.addEventListener("click", () => {
  stopStream().catch((err) => showError(err.message));
});
