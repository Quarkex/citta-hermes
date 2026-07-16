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

Each turn, `transform_context` asks the Brain to attend to the current context
and **waits for it to finish**, then injects the result:

```
1. POST /api/0.1.0/attend      → ask the Brain to attend to this context
2. GET  /api/0.1.0/attention   → poll until it is done (the Brain takes its time)
3. inject [Working context]    → before the last user turn, then the agent answers
```

The Brain's attention is deep, so a turn takes as long as the Brain needs. That
is the point: the Brain does cognitive work that would otherwise cost the agent
many LLM roundtrips. If the Brain is unreachable, or does not finish within
`attend_deadline`, or decides not to respond, the turn is cancelled — no action
without a Brain.

`require_brain: false` in the config downgrades to fail-open (act even when the
Brain is down) — but that defeats the purpose and is off by default.

## Config

```yaml
plugins:
  enabled:
    - citta
  citta:
    url: https://brains.alchemist.ninja
    token: bt_xxx           # per-brain token; or inherited from mcp_servers.brain
    attend_deadline: 180    # seconds — max wait for the Brain to attend
    poll_interval: 2        # seconds — how often to check while it thinks
    http_timeout: 10        # seconds — per request
```

## Requirements

- Hermes with the `transform_context` hook (current upstream has it). Older
  builds: see [`patches/`](patches/) for the minimal shim.
- A Brain instance and a per-brain token.

## Uninstall

Remove `~/.hermes/plugins/citta/`, drop `citta` from `plugins.enabled`.
