// Health monitor and backoff tests. Timers are injected, so nothing
// here waits on the clock.

import assert from "node:assert/strict";
import { test } from "node:test";

import { HealthMonitor, backoffDelay } from "../dist/js/health.mjs";

test("backoff doubles from the base and is capped", () => {
  const opts = { base: 1000, max: 30000, jitter: 0 };
  assert.deepEqual(
    [1, 2, 3, 4, 5, 6, 7, 50].map((n) => backoffDelay(n, opts)),
    [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000],
  );
});

test("backoff jitter only adds delay and never exceeds the cap", () => {
  assert.equal(backoffDelay(1, { base: 1000, max: 30000, jitter: 0.2, random: () => 1 }), 1200);
  assert.equal(backoffDelay(9, { base: 1000, max: 30000, jitter: 0.2, random: () => 1 }), 30000);
});

test("backoff tolerates nonsense attempt numbers", () => {
  for (const bad of [0, -3, NaN, undefined, "x"]) {
    assert.equal(backoffDelay(bad, { jitter: 0 }), 1000);
  }
});

function harness(results) {
  const timers = [];
  const changes = [];
  const client = {
    calls: 0,
    async health() {
      const next = results[Math.min(this.calls, results.length - 1)];
      this.calls += 1;
      if (next instanceof Error) throw next;
      return next;
    },
  };
  const monitor = new HealthMonitor(client, {
    onChange: (change) => changes.push(change),
    intervalMs: 15000,
    backoff: { base: 1000, max: 30000, jitter: 0 },
    setTimer: (fn, ms) => {
      timers.push({ fn, ms, cleared: false, fired: false });
      return timers.length - 1;
    },
    clearTimer: (id) => {
      timers[id].cleared = true;
    },
  });
  const pending = () => timers.filter((t) => !t.cleared && !t.fired);
  const fire = async () => {
    const timer = pending().at(-1);
    timer.fired = true;
    timer.fn();
    await new Promise((resolve) => setImmediate(resolve));
  };
  return { monitor, client, timers, changes, pending, fire };
}

test("a healthy server is polled on the steady interval with no change events", async () => {
  const h = harness([{ status: "ok" }]);
  h.monitor.start();
  assert.equal(h.pending().at(-1).ms, 15000);
  await h.fire();
  assert.equal(h.client.calls, 1);
  assert.equal(h.changes.length, 0);
  assert.equal(h.pending().at(-1).ms, 15000);
  h.monitor.stop();
});

test("failures report offline and back off, recovery reports ok once", async () => {
  const down = new Error("connection refused");
  const h = harness([down, down, down, { status: "ok" }, { status: "ok" }]);
  h.monitor.start();
  await h.fire();
  await h.fire();
  await h.fire();
  assert.deepEqual(
    h.changes.map((c) => [c.state, c.attempt, c.retryInMs]),
    [["offline", 1, 1000], ["offline", 2, 2000], ["offline", 3, 4000]],
  );
  assert.equal(h.changes[0].error, down);
  await h.fire();
  assert.equal(h.changes.at(-1).state, "ok");
  assert.equal(h.pending().at(-1).ms, 15000);
  await h.fire();
  assert.equal(h.changes.length, 4, "a steady ok does not repeat the change event");
  h.monitor.stop();
});

test("stop cancels the pending timer and silences a probe in flight", async () => {
  const h = harness([new Error("down")]);
  h.monitor.start();
  const inFlight = h.monitor.check();
  h.monitor.stop();
  await inFlight;
  assert.equal(h.changes.length, 0);
  assert.equal(h.pending().length, 0);
});

test("a 401 from the authenticated probe is token rejected, not offline", async () => {
  const rejected = Object.assign(new Error("Invalid API key"), { status: 401, code: "invalid_api_key" });
  const timers = [];
  const changes = [];
  let authCalls = 0;
  const client = {
    async health() {
      return { status: "ok", version: "mock-1" };
    },
    async probeAuth() {
      authCalls += 1;
      if (authCalls === 1) throw rejected;
      return { features: {} };
    },
  };
  const monitor = new HealthMonitor(client, {
    onChange: (change) => changes.push(change),
    intervalMs: 15000,
    backoff: { jitter: 0 },
    setTimer: (fn, ms) => {
      timers.push({ fn, ms, cleared: false, fired: false });
      return timers.length - 1;
    },
    clearTimer: (id) => {
      timers[id].cleared = true;
    },
  });
  monitor.start();
  const pending = () => timers.filter((timer) => !timer.cleared && !timer.fired);
  const fire = async () => {
    const timer = pending().at(-1);
    timer.fired = true;
    timer.fn();
    await new Promise((resolve) => setImmediate(resolve));
  };
  await fire();
  assert.equal(changes[0].state, "rejected");
  assert.equal(changes[0].error, rejected);
  assert.equal(pending().at(-1).ms, 15000);
  await fire();
  assert.equal(changes.at(-1).state, "ok");
  monitor.stop();
});
