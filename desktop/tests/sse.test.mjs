import { test } from "node:test";
import assert from "node:assert/strict";

import { SSEParser } from "../dist/js/sse.mjs";

test("parses a named event with a JSON payload", () => {
  const parser = new SSEParser();
  const events = parser.push('event: assistant.delta\ndata: {"delta":"hi"}\n\n');
  assert.equal(events.length, 1);
  assert.equal(events[0].event, "assistant.delta");
  assert.deepEqual(events[0].json, { delta: "hi" });
});

test("keepalive comment lines are skipped", () => {
  const parser = new SSEParser();
  const events = parser.push(": keepalive\n\nevent: done\ndata: {}\n\n");
  assert.equal(events.length, 1);
  assert.equal(events[0].event, "done");
});

test("frames split at arbitrary chunk boundaries still parse", () => {
  const parser = new SSEParser();
  const wire = 'event: assistant.delta\ndata: {"delta":"hello"}\n\n';
  let events = [];
  for (const ch of wire) events = events.concat(parser.push(ch));
  assert.equal(events.length, 1);
  assert.equal(events[0].json.delta, "hello");
});

test("multi-line data is joined and CRLF is tolerated", () => {
  const parser = new SSEParser();
  const events = parser.push('event: x\r\ndata: {"a":\r\ndata: 1}\r\n\r\n');
  assert.equal(events.length, 1);
  assert.deepEqual(events[0].json, { a: 1 });
});

test("the [DONE] sentinel is passed through unparsed", () => {
  const parser = new SSEParser();
  const events = parser.push("data: [DONE]\n\n");
  assert.equal(events.length, 1);
  assert.equal(events[0].data, "[DONE]");
  assert.equal(events[0].json, null);
});

test("end flushes a trailing frame without its blank line", () => {
  const parser = new SSEParser();
  assert.deepEqual(parser.push('event: run.completed\ndata: {"ok":true}\n'), []);
  const events = parser.end();
  assert.equal(events.length, 1);
  assert.equal(events[0].event, "run.completed");
});
