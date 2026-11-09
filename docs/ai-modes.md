# AI modes

Three modes, one tool set, as in hermes-finance:

1. **Hermes plugin** — Hermes runs the model; the app never sees a model key; writes show Hermes's approval prompt in plain words; scheduled and unattended runs refuse writes.
2. **MCP server** — any MCP client; read-only by default; writes only as pending actions approved in Settings.
3. **API key / local endpoint** — any OpenAI-compatible endpoint, including a local Ollama or LM Studio server, subject to the matter's privacy ceiling.
4. **Off** — no Ask panel at all. Every deterministic feature (compare, citation extraction, deadline arithmetic, playbook structure checks) still works.

Modes 1 and 2 hand tool results to the agent's model, so returning a document is
sending it to that model. See [Agent tools](agent-tools.md) for how an operator
declares that model's privacy tier; until then no matter content is returned.
