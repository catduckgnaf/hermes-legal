// Browser wiring for the desktop client. All protocol logic lives in
// client.mjs / config.mjs / sse.mjs and is tested against a mock server;
// this file only connects that logic to the page.

import { HermesClient, approvalsSupported } from "./client.mjs";
import { loadConfig, saveConfig } from "./config.mjs";

const $ = (id) => document.getElementById(id);

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
  newSession: $("new-session"),
  sessions: $("session-list"),
  messages: $("messages"),
  composer: $("composer"),
  input: $("input"),
  send: $("send"),
  approval: $("approval"),
  approvalText: $("approval-text"),
  approvalChoices: $("approval-choices"),
  error: $("error"),
};

let client = null;
let capabilities = null;
let currentSessionId = null;
let pendingApproval = null;

function showError(message) {
  els.error.textContent = message || "";
  els.error.hidden = !message;
}

function setStatus(kind, text) {
  els.statusDot.dataset.state = kind;
  els.statusText.textContent = text;
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
    item.addEventListener("click", () => selectSession(session.id));
    els.sessions.append(item);
  }
  if (sessions.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No sessions yet. Start a new one.";
    els.sessions.append(empty);
  }
}

async function refreshSessions() {
  if (!client) return;
  renderSessions(await client.listSessions());
}

async function selectSession(sessionId) {
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
    config = saveConfig(window.localStorage, readForm());
  } catch (err) {
    setStatus("error", "Check the connection settings.");
    showError(err.message);
    return;
  }
  client = new HermesClient(config);
  setStatus("pending", "Connecting…");
  try {
    const health = await client.health();
    capabilities = await client.capabilities().catch(() => null);
    setStatus(
      "ok",
      `Connected — Hermes ${health.version ?? ""} at ${client.baseUrl}`.trim(),
    );
    if (capabilities && approvalsSupported(capabilities)) {
      els.approvalNote.textContent =
        "Approvals: this server advertises approval events and the run approval endpoint, so approval prompts are shown here.";
    } else {
      els.approvalNote.textContent =
        "Approvals: this server does not advertise approval support in /v1/capabilities, so no approval prompts will be shown. Runs that need approval will park on the server until another client answers.";
    }
    await refreshSessions();
    if (!currentSessionId) {
      const sessions = await client.listSessions();
      if (sessions.length > 0) await selectSession(sessions[0].id);
    }
  } catch (err) {
    client = null;
    setStatus("error", "Not connected.");
    showError(err.message);
  }
}

async function send(event) {
  event.preventDefault();
  const text = els.input.value.trim();
  if (!text || !client) return;
  showError("");
  if (!currentSessionId) {
    const created = await client.createSession({});
    currentSessionId = created.id;
    await refreshSessions();
  }
  els.input.value = "";
  addMessage("user", text);
  const body = addMessage("assistant", "");
  els.send.disabled = true;
  try {
    const result = await client.chatStream(currentSessionId, text, {
      onDelta: (_delta, full) => {
        body.textContent = full;
        els.messages.scrollTop = els.messages.scrollHeight;
      },
      onEvent: (name, payload) => {
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
    body.textContent = result.content;
    if (result.status !== "completed") {
      showError(`The run ended with status: ${result.status}`);
    }
  } catch (err) {
    showError(err.message);
  } finally {
    els.send.disabled = false;
    refreshSessions().catch(() => {});
  }
}

fillForm(loadConfig(window.localStorage));
els.connect.addEventListener("click", connect);
els.refreshSessions.addEventListener("click", () =>
  refreshSessions().catch((err) => showError(err.message)),
);
els.newSession.addEventListener("click", async () => {
  if (!client) return;
  const created = await client.createSession({});
  currentSessionId = created.id;
  els.messages.replaceChildren();
  await refreshSessions();
});
els.composer.addEventListener("submit", send);
