// Client tests against the mock Hermes server (tests/mock-hermes.mjs),
// which implements the researched API-server protocol shapes.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";

import { HermesClient, HermesError, approvalsSupported } from "../dist/js/client.mjs";
import { startMockHermes, APPROVAL_TRIGGER } from "./mock-hermes.mjs";

let mock;
let client;

before(async () => {
  mock = await startMockHermes();
  client = new HermesClient(mock.config);
});

after(async () => {
  await mock.close();
});

test("health reports the Hermes liveness payload", async () => {
  const health = await client.health();
  assert.equal(health.status, "ok");
  assert.equal(health.platform, "hermes-agent");
});

test("a wrong token is refused with a 401 HermesError", async () => {
  const bad = new HermesClient({ ...mock.config, token: "wrong" });
  await assert.rejects(bad.listSessions(), (err) => {
    assert.ok(err instanceof HermesError);
    assert.equal(err.status, 401);
    assert.equal(err.code, "invalid_api_key");
    return true;
  });
});

test("capabilities advertise approval support on the mock", async () => {
  const caps = await client.capabilities();
  assert.equal(caps.platform, "hermes-agent");
  assert.equal(approvalsSupported(caps), true);
});

test("listSessions normalizes the real list shape", async () => {
  const sessions = await client.listSessions();
  assert.equal(sessions.length, 2);
  assert.equal(sessions[0].id, "sess_alpha");
  assert.equal(sessions[0].title, "Alpha matter");
  assert.equal(sessions[0].messageCount, 2);
  assert.equal(sessions[1].title, "");
});

test("createSession returns the created session and lists it", async () => {
  const created = await client.createSession({ title: "New matter" });
  assert.match(created.id, /^sess_mock_/);
  assert.equal(created.title, "New matter");
  const sessions = await client.listSessions();
  assert.equal(sessions[0].id, created.id);
});

test("listMessages returns the session history", async () => {
  const messages = await client.listMessages("sess_alpha");
  assert.equal(messages.length, 2);
  assert.deepEqual(
    messages.map((m) => m.role),
    ["user", "assistant"],
  );
  assert.equal(messages[1].content, "Hi there.");
});

test("listMessages on an unknown session surfaces the 404", async () => {
  await assert.rejects(client.listMessages("nope"), (err) => {
    assert.equal(err.status, 404);
    assert.equal(err.code, "session_not_found");
    return true;
  });
});

test("chatStream renders deltas incrementally and completes", async () => {
  const deltas = [];
  const events = [];
  const result = await client.chatStream("sess_alpha", "hello Hermes", {
    onDelta: (delta) => deltas.push(delta),
    onEvent: (name) => events.push(name),
  });
  assert.ok(deltas.length >= 2, "expected incremental deltas");
  assert.equal(deltas.join(""), "Echo: hello Hermes");
  assert.equal(result.content, "Echo: hello Hermes");
  assert.equal(result.status, "completed");
  assert.ok(result.runId);
  assert.deepEqual(events.slice(0, 2), ["run.started", "message.started"]);
  assert.equal(events.at(-1), "done");
  assert.ok(events.includes("assistant.completed"));
  assert.ok(events.includes("run.completed"));
});

test("chatStream surfaces an approval request and resolves it mid-stream", async () => {
  let approvalSeen = null;
  let resolveResult = null;
  const result = await client.chatStream(
    "sess_alpha",
    `please run the ${APPROVAL_TRIGGER} step`,
    {
      onEvent: (name, payload) => {
        if (name !== "approval.request") return;
        approvalSeen = payload;
        // Answer while the stream is still open, like the UI does.
        client
          .resolveApproval(payload.run_id, "once", {
            requestId: payload.request_id,
            executionGeneration: payload.execution_generation,
          })
          .then((r) => {
            resolveResult = r;
          });
      },
    },
  );
  assert.ok(approvalSeen, "expected an approval.request event");
  assert.deepEqual(approvalSeen.choices, ["once", "session", "always", "deny"]);
  assert.match(approvalSeen.command, /remove a generated file/);
  assert.equal(result.status, "completed");
  assert.match(result.content, /Approval granted \(once\)\./);
  // The floating resolve promise settles before or just after the stream;
  // wait a tick so the assertion reads the finished value.
  await new Promise((r) => setTimeout(r, 25));
  assert.equal(resolveResult?.choice, "once");
  assert.equal(mock.state.lastApproval.choice, "once");
  assert.equal(mock.state.lastApproval.request_id, approvalSeen.request_id);
  assert.equal(mock.state.lastApproval.execution_generation, 3);
});

test("resolving an approval with no pending request surfaces the 409", async () => {
  await assert.rejects(client.resolveApproval("run_missing", "once"), (err) => {
    assert.equal(err.status, 409);
    assert.equal(err.code, "approval_not_pending");
    return true;
  });
});

test("approvalsSupported is false when the server does not advertise it", async () => {
  const bare = await startMockHermes({
    features: { run_approval_response: false, approval_events: false },
  });
  try {
    const bareClient = new HermesClient(bare.config);
    const caps = await bareClient.capabilities();
    assert.equal(approvalsSupported(caps), false);
  } finally {
    await bare.close();
  }
  assert.equal(approvalsSupported(null), false);
  assert.equal(approvalsSupported({}), false);
});
