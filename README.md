# citta-hermes

A [Hermes](https://github.com/NousResearch/hermes-agent) plugin that **binds an
agent to a [Brain](https://brains.alchemist.ninja).** Once bound, the agent is
the Brain's voice: **no action without a Brain.**

Before each LLM call, `citta` reaches the Brain to read its current attention
and register the context. If the Brain is unavailable, the turn is cancelled —
no LLM call, no tools, no reply. Otherwise it injects the Brain's current
attention and proceeds. It uses Hermes' native `transform_context` hook — **no
source patch**.

This is fail-*closed* by design. The Brain is not an enhancement to the agent;
it is the condition for the agent to act at all.

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

The Brain's attention arrives a turn later, so reaching it is fast — a status
read plus a fire-and-forget post. The gate is **availability**, not a wait: if
the read fails, the turn is cancelled; if it succeeds, the agent acts on
whatever guidance is ready (none, on the very first turn). If the Brain decides
not to respond, the turn is cancelled too.

`require_brain: false` in the config downgrades to fail-open (act even when the
Brain is down) — but that defeats the purpose and is off by default.

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
