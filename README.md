# citta-hermes

A [Hermes](https://github.com/NousResearch/hermes-agent) plugin that connects an
agent to a [Brain](https://brains.alchemist.ninja) **attention** endpoint.

Before each LLM call, `citta` injects the Brain's current attention into the
context and posts the current context back for the Brain to attend to. It uses
Hermes' native `transform_context` hook — **no source patch** — and fails open:
if the Brain is slow or unreachable, the agent runs unchanged.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Quarkex/citta-hermes/main/install.sh | bash -s -- --token bt_your_brain_token
```

Installs the plugin, wires `config.yaml`, and enables it. Restart Hermes. If you
already have a `mcp_servers.brain` bearer token in your config, drop `--token` —
the installer reuses it.

```bash
hermes plugins list | grep citta      # verify
```

## How it works

The Brain's attention endpoint is asynchronous, so the plugin never blocks on
it. Each turn, `transform_context`:

```
1. GET  /api/0.1.0/attention   → inject the Brain's current attention
                                  ([Working context]) before the last user turn
2. POST /api/0.1.0/attend      → post this context for the Brain to attend to
                                  (returns at once; the Brain works in the background)
```

The plugin injects whatever attention is currently available, so guidance
arrives a turn later and the agent is never blocked. Before the Brain has
produced any attention, the context passes through unchanged.

## Config

```yaml
plugins:
  enabled:
    - citta
  citta:
    url: https://brains.alchemist.ninja
    token: bt_xxx          # per-brain token; or inherited from mcp_servers.brain
    read_timeout: 5        # GET /attention — the fast read
    fire_timeout: 10       # POST /attend — returns at once
```

## Requirements

- Hermes with the `transform_context` hook (current upstream has it). Older
  builds: see [`patches/`](patches/) for the minimal shim.
- A Brain instance and a per-brain token.

## Uninstall

Remove `~/.hermes/plugins/citta/`, drop `citta` from `plugins.enabled`.
