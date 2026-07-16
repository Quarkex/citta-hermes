# citta-hermes

Give a [Hermes](https://github.com/NousResearch/hermes-agent) agent a **mind**.

`citta` routes the agent's full context through [Brain](https://brains.alchemist.ninja)'s
**Manasikara** attention pipeline before every LLM call. Manasikara resolves
speaker and addressee, feels emotion, recalls relevant memory, judges whether to
respond, enriches with deductions, runs metacognitive vigilance, and injects
*whispers* — then hands the enriched context back to the model.

It is a single plugin on Hermes' native `transform_context` hook. **No source
patch, no daemon, no sensor bank.** If Brain is slow or down, it fails open and
the agent runs unchanged.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Quarkex/citta-hermes/main/install.sh | bash -s -- --token bt_your_brain_token
```

That installs the plugin, wires `config.yaml`, and enables it. Restart Hermes.
If you already have a `mcp_servers.brain` bearer token in your config, you can
drop `--token` — the installer reuses it.

```bash
hermes plugins list | grep citta      # verify
```

## What it replaces

One `attend` call subsumes the older integration entirely:

| Old | Now |
|-----|-----|
| `memory/brain` MemoryProvider prefetch (search + probe) | Manasikara **recall** stage |
| `gateway/run.py` interoception patch + sensor bank (cold_start, fatigue, identity_drift, satiation…) | Manasikara **vigilance** + **interoception** stages |
| ~2000-line source patch that broke on every `hermes update` | native `transform_context` hook — nothing to re-apply |

The installer disables the superseded MemoryProvider and flags the old
interoception patch for removal.

## How it works

```
Hermes turn ── transform_context(api_messages) ──▶ POST /api/0.1.0/attend
                                                        │  (Manasikara: 12 stages)
       enriched context ◀── context_stream ────────────┘
```

`attend` returns the (possibly mutated, reduced, or emptied) message stream. An
empty stream means Manasikara's *inhibit* stage decided the agent should stay
silent, and the turn is cancelled.

## Config

```yaml
plugins:
  enabled:
    - citta
  citta:
    url: https://brains.alchemist.ninja
    token: bt_xxx        # per-brain token; or inherited from mcp_servers.brain
    timeout: 30          # seconds — fail-open past this
```

## Requirements

- Hermes with the `transform_context` hook (current upstream and the Quarkex
  fork have it). Older builds: see [`patches/`](patches/) for the minimal shim.
- A Brain instance and a per-brain token.

## Uninstall

Remove `~/.hermes/plugins/citta/`, drop `citta` from `plugins.enabled`, and
(optionally) restore `memory.provider` in `config.yaml`.
