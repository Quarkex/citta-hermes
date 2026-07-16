"""Citta — the Hermes ⇆ Brain attention bridge.

Runs Brain's **Manasikara** attention pipeline alongside the agent, **one turn
behind**, via Hermes' native ``transform_context`` hook. The full pipeline
(recall, empathy, interoception, vigilance, whisper distillation) takes ~30–90s
— far too long to block an LLM call — so it runs asynchronously:

* every turn, the plugin reads the **previous** turn's completed attention
  (``GET /attend_latest``, a fast in-memory read) and injects it as a
  ``[Working context]`` system message before the last user turn;
* it then fires a fresh ``attend`` for the **current** context
  (``POST /attend`` → 202, returns immediately) whose result lands in the cache
  for the next turn.

The mind therefore thinks *concurrently* with the agent and its guidance arrives
a turn later — never blocking the response. On the very first turn (empty cache)
the context passes through unchanged.

This single hook supersedes the old ``memory/brain`` MemoryProvider prefetch and
the ``gateway/run.py`` interoception patch — Manasikara subsumes both, and does
it server-side. There is **no source patch** on modern Hermes.

Fail-open: any error, timeout, or unreachable Brain leaves the context untouched.

Config — ``~/.hermes/config.yaml``::

    plugins:
      enabled:  [citta]
      citta:
        url: https://brains.alchemist.ninja
        token: bt_xxx        # or discovered from mcp_servers.brain
        read_timeout: 5      # seconds — the fast latest-attention read
        fire_timeout: 10     # seconds — POST /attend (202 returns immediately)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

ATTEND = "/api/0.1.0/attend"
LATEST = "/api/0.1.0/attend_latest/"
DEFAULT_URL = "https://brains.alchemist.ninja"

# metadata Manasikara uses for routing (identify/address stages) + pressure
_FORWARD_META = (
    "session_id", "sender_id", "sender_name", "platform", "chat_type",
    "chat_id", "chat_name", "thread_id", "user_turn_count", "iteration",
    "context_window_tokens", "approx_input_tokens",
)


def _load_config() -> dict:
    """Read ``plugins.citta`` from config.yaml; fall back to the
    ``mcp_servers.brain`` bearer so one token configures both paths."""
    try:
        from hermes_constants import get_hermes_home
        import yaml

        path = get_hermes_home() / "config.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8-sig") as f:
            root = yaml.safe_load(f) or {}
    except Exception:
        return {}

    cfg = dict((root.get("plugins") or {}).get("citta") or {})
    if not cfg.get("token"):
        mcp = (root.get("mcp_servers") or {}).get("brain") or {}
        auth = (mcp.get("headers") or {}).get("Authorization", "") or ""
        cfg["token"] = auth[7:] if auth.startswith("Bearer ") else auth
    return cfg


class CittaBridge:
    """``transform_context`` hook: inject the previous turn's attention, fire the
    current turn's. The mind runs one turn behind, never blocking."""

    def __init__(self, config: dict | None = None):
        cfg = config if config is not None else _load_config()
        self.url = str(cfg.get("url") or DEFAULT_URL).rstrip("/")
        self.token = cfg.get("token") or ""
        self.read_timeout = float(cfg.get("read_timeout") or 5)
        self.fire_timeout = float(cfg.get("fire_timeout") or cfg.get("timeout") or 10)
        self.enabled = cfg.get("enabled", True) is not False

    # -- hook -----------------------------------------------------------------

    def transform_context(self, *, api_messages=None, metadata=None, **_kwargs):
        if not self.enabled or not isinstance(api_messages, list) or not api_messages:
            return None
        meta = metadata if isinstance(metadata, dict) else {}
        session = meta.get("session_id") or "default"

        working = self._read_latest(session)      # previous turn's attention
        self._fire_attend(api_messages, meta, session)  # this turn's, async

        if working:
            return self._inject(api_messages, working)
        return None

    # -- Brain calls ----------------------------------------------------------

    def _read_latest(self, session: str) -> str:
        try:
            data = self._request("GET", LATEST + urllib.request.quote(session, safe=""),
                                  timeout=self.read_timeout)
        except Exception as exc:
            logger.debug("citta: attend_latest read failed (pass-through): %s", exc)
            return ""
        if not data or not data.get("ready") or data.get("cancel"):
            return ""  # not ready yet, or a stale inhibit we must not apply now
        return (data.get("working_context") or "").strip()

    def _fire_attend(self, api_messages: list, meta: dict, session: str) -> None:
        payload = {
            "api_version": "0.1.0",
            "context_stream": api_messages,
            "metadata": {k: meta[k] for k in _FORWARD_META if k in meta} or {"session_id": session},
        }
        try:
            self._request("POST", ATTEND, body=payload, timeout=self.fire_timeout)
        except Exception as exc:
            logger.debug("citta: attend fire failed (fail-open): %s", exc)

    def _request(self, method: str, path: str, *, body=None, timeout: float):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    # -- injection ------------------------------------------------------------

    @staticmethod
    def _inject(api_messages: list, working: str) -> list:
        content = working if working.startswith("[") else "[Working context]\n" + working
        note = {"role": "system", "content": content}
        # place it right before the last user turn (Manasikara's own convention)
        last_user = next(
            (i for i in range(len(api_messages) - 1, -1, -1)
             if isinstance(api_messages[i], dict) and api_messages[i].get("role") == "user"),
            None,
        )
        if last_user is None:
            return api_messages + [note]
        return api_messages[:last_user] + [note] + api_messages[last_user:]


def register(ctx) -> None:
    """Plugin entry point — wire the attention bridge into Hermes."""
    bridge = CittaBridge()
    ctx.register_hook("transform_context", bridge.transform_context)
    logger.info("citta: attention bridge → %s (one turn behind)", bridge.url)
