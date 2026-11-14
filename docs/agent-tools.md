# Agent tools

The `legal` CLI and the MCP server both call the same dispatcher, so they follow the same rules.

## Run the MCP server

```sh
export HERMES_LEGAL_AGENT_TIER=LOCAL_ONLY   # only if the client's model runs on this computer
uv run legal mcp serve
```

The server speaks newline-delimited JSON-RPC over stdio. Only tools that are built are listed. Five are not built yet: `legal_chronology`, `legal_transcribe`, `legal_intake_summary`, `legal_sync` and `legal_efile_bundle`.

## Declare the agent's privacy tier

In these modes the agent's model reads whatever a tool returns, so returning a document is sending it to that model. Hermes Legal cannot see which model the client uses, so the operator states it in `HERMES_LEGAL_AGENT_TIER`.

| Value | Meaning |
|---|---|
| Unset | Unknown. No matter content is returned, and matters are hidden from `legal_matter_list`. |
| `LOCAL_ONLY` | The model runs on this computer. All matters are available. |
| `ZERO_RETENTION` | Matters with a `ZERO_RETENTION` or `STANDARD` ceiling are available. |
| `STANDARD` | Only matters with a `STANDARD` ceiling are available. |

This value is a statement by the operator. It is not verified, so set it only when it is true.

## Approve a write

A write tool saves a pending action and changes nothing. Review and decide at an interactive terminal:

```sh
uv run legal actions list
uv run legal actions show 1
uv run legal actions approve 1 --by "A. Lawyer"
uv run legal actions reject 1 --by "A. Lawyer"
```

An action runs at most once. If it fails, propose it again. MCP clients cannot see write tools until a person runs `legal mcp allow-writes on`. Scheduled and unattended runs cannot propose writes at all.

## Ask with a local model

```sh
uv run legal ask 1 "When does the lease end?" --model qwen3:8b
```

Only a loopback address is accepted. The default is `http://127.0.0.1:11434/v1`; change it with `HERMES_LEGAL_LOCAL_BASE_URL`. Ollama model tags that run in its cloud are refused by name. Each call is logged with a hash of the exact prompt.

## Citation lookups

`legal_cite_check` only goes online when called with `lookup: true` and a `matter_id`. A `LOCAL_ONLY` matter is never looked up, because that would send its citations off the device, so those citations remain unverified and block the Verify-All gate.
