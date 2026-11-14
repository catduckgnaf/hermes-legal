// Incremental Server-Sent Events parser.
//
// The Hermes API server streams with standard SSE frames
// (`event: <name>` + `data: <json>` + blank line) and emits a
// `: keepalive` comment line whenever a stream is idle for about
// 10 seconds. Comment lines must be skipped, frames can split at any
// byte boundary, and `data:` can repeat inside one frame. This parser
// handles all three; it is deliberately transport-free so tests can
// feed it raw text in arbitrary chunks.

export class SSEParser {
  constructor() {
    this.buffer = "";
    this.eventName = "message";
    this.dataLines = [];
  }

  // Feed one text chunk; returns the events completed by it.
  push(chunk) {
    this.buffer += chunk;
    const events = [];
    let newline;
    while ((newline = this.buffer.indexOf("\n")) >= 0) {
      let line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      const event = this.#line(line);
      if (event) events.push(event);
    }
    return events;
  }

  // Flush a trailing frame that arrived without its final blank line.
  end() {
    const events = [];
    if (this.buffer.length > 0) {
      const event = this.#line(this.buffer.replace(/\r$/, ""));
      if (event) events.push(event);
      this.buffer = "";
    }
    const event = this.#dispatch();
    if (event) events.push(event);
    return events;
  }

  #line(line) {
    if (line === "") return this.#dispatch();
    if (line.startsWith(":")) return null; // comment / keepalive
    const colon = line.indexOf(":");
    const field = colon >= 0 ? line.slice(0, colon) : line;
    let value = colon >= 0 ? line.slice(colon + 1) : "";
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.eventName = value;
    else if (field === "data") this.dataLines.push(value);
    // `id:` and `retry:` carry no meaning for this client.
    return null;
  }

  #dispatch() {
    if (this.dataLines.length === 0) {
      this.eventName = "message";
      return null;
    }
    const rawData = this.dataLines.join("\n");
    const event = { event: this.eventName, data: rawData, json: null };
    if (rawData !== "[DONE]") {
      try {
        event.json = JSON.parse(rawData);
      } catch {
        event.json = null; // callers decide how to treat non-JSON data
      }
    }
    this.eventName = "message";
    this.dataLines = [];
    return event;
  }
}
