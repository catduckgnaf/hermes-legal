// Connection health monitoring with reconnect backoff.
//
// GET /health is the public liveness probe (see desktop/PROTOCOL.md).
// HealthMonitor polls it on a steady interval while the server answers
// and backs off exponentially while it does not, so the status
// indicator follows the real connection instead of the state at
// connect time. Timers are injected so tests run without waiting.

export const HEALTH_INTERVAL_MS = 15000;
export const BACKOFF_BASE_MS = 1000;
export const BACKOFF_MAX_MS = 30000;

// Delay before retry number `attempt` (1-based): base * 2^(attempt-1),
// capped at max, plus up to `jitter` (a 0..1 fraction) of extra delay
// so many clients do not retry in step. `random` is injectable.
export function backoffDelay(
  attempt,
  { base = BACKOFF_BASE_MS, max = BACKOFF_MAX_MS, jitter = 0.2, random = Math.random } = {},
) {
  const n = Math.max(1, Math.floor(Number(attempt) || 1));
  const raw = Math.min(max, base * 2 ** Math.min(n - 1, 30));
  return Math.min(max, Math.round(raw * (1 + jitter * random())));
}

// Polls client.health(). Calls onChange({ state, attempt, retryInMs,
// health, error }) when the state changes and on every failed attempt:
//   state "ok"        the last probe succeeded and the token was accepted
//   state "rejected" the server is up but the token was refused (HTTP 401)
//   state "offline"  the last probe failed; retryInMs is the wait
export class HealthMonitor {
  constructor(client, {
    onChange,
    intervalMs = HEALTH_INTERVAL_MS,
    backoff = {},
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (id) => clearTimeout(id),
  } = {}) {
    this.client = client;
    this.onChange = onChange ?? (() => {});
    this.intervalMs = intervalMs;
    this.backoff = backoff;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.state = "idle";
    this.failures = 0;
    this.timer = null;
    this.running = false;
  }

  // Begin polling. The caller has usually just completed a successful
  // health call, so the first probe is scheduled, not immediate.
  start({ assumeOk = true } = {}) {
    this.stop();
    this.running = true;
    this.failures = 0;
    this.state = assumeOk ? "ok" : "idle";
    this.#schedule(assumeOk ? this.intervalMs : 0);
  }

  stop() {
    this.running = false;
    if (this.timer !== null) this.clearTimer(this.timer);
    this.timer = null;
  }

  // One probe. Exposed for tests and for a manual "retry now".
  async check() {
    let health = null;
    let error = null;
    let authRejected = null;
    try {
      health = await this.client.health();
    } catch (err) {
      error = err;
    }
    if (error === null && typeof this.client.probeAuth === "function") {
      try {
        await this.client.probeAuth();
      } catch (err) {
        if (err?.status === 401 || err?.code === "invalid_api_key") authRejected = err;
        else error = err;
      }
    }
    if (!this.running) return this.state;
    if (authRejected) {
      const changed = this.state !== "rejected";
      this.failures = 0;
      this.state = "rejected";
      if (changed) {
        this.onChange({
          state: "rejected",
          attempt: 0,
          retryInMs: this.intervalMs,
          health,
          error: authRejected,
        });
      }
      this.#schedule(this.intervalMs);
    } else if (error === null) {
      const changed = this.state !== "ok";
      this.failures = 0;
      this.state = "ok";
      if (changed) this.onChange({ state: "ok", attempt: 0, retryInMs: 0, health, error: null });
      this.#schedule(this.intervalMs);
    } else {
      this.failures += 1;
      this.state = "offline";
      const retryInMs = backoffDelay(this.failures, this.backoff);
      this.onChange({ state: "offline", attempt: this.failures, retryInMs, health: null, error });
      this.#schedule(retryInMs);
    }
    return this.state;
  }

  #schedule(ms) {
    if (!this.running) return;
    if (this.timer !== null) this.clearTimer(this.timer);
    this.timer = this.setTimer(() => {
      this.timer = null;
      this.check();
    }, ms);
  }
}
