# AI modes

Three modes, one tool set, as in hermes-finance:

1. **MCP server** — any MCP client; read-only by default; writes only as pending actions approved in Settings.
2. **API key / local endpoint** — any OpenAI-compatible endpoint, including a local Ollama or LM Studio server, subject to the matter's privacy ceiling.
3. **Off** — no Ask panel at all. Every deterministic feature (compare, citation extraction, deadline arithmetic, playbook structure checks) still works.

There is no Hermes plugin: Hermes Legal is a standalone desktop client, built from the ground up.

The MCP mode hands tool results to the agent's model, so returning a document is
sending it to that model. See [Agent tools](agent-tools.md) for how an operator
declares that model's privacy tier; until then no matter content is returned.

In mode 3, a send that goes through the provider router is preceded by a
pre-send preview and recorded in the matter's AI log with a hash of the
exact payload sent, tied to the fingerprint of the approved preview, so
what was sent can be audited against what was approved. See
[Models and privacy tiers](models.md) for the sent-payload log.
