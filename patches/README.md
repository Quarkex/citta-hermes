# patches — the fallback, not the norm

citta rides Hermes' **native `transform_context` hook**. On any Hermes that has
it (the Quarkex fork and current upstream do), citta needs **zero source
changes** — it is a pure plugin.

`apply_shim.py` exists only for older Hermes builds that predate the hook. It is
the whole "patch mode," and by design it is minimal: it adds `transform_context`
to `VALID_HOOKS` and (if missing) points you at the ~12-line invocation block to
place before the LLM call. It never rewrites large spans of `run.py` the way the
old gateway context patch did — that patch is **deprecated**: the Brain's
attention endpoint does that work server-side now.

## Is the hook present?

```bash
grep -q '"transform_context"' ~/.hermes/hermes-agent/hermes_cli/plugins.py \
  && grep -q transform_context ~/.hermes/hermes-agent/agent/conversation_loop.py \
  && echo "native hook present — no patch needed" || echo "shim required"
```

## The hook contract

`transform_context` is invoked in `agent/conversation_loop.py` right before the
LLM call:

```python
_ctx_results = _invoke_hook("transform_context", api_messages=api_messages, metadata=_ctx_metadata)
```

A callback returns a `list` to replace the message array, `[]` to cancel the
turn, or `None` to pass through. citta returns Brain's `attend` output — that's
the entire integration.
