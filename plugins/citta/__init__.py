"""citta — binds a Hermes agent to a Brain.

Once bound, the agent is the Brain's voice: **no action without a Brain.** If the
Brain is unavailable, the agent does not act — the turn is cancelled (no LLM
call, no tools, no reply). This is fail-*closed* by design, the opposite of an
optional enhancement: the Brain is the condition for the agent to act at all.

Each turn, via Hermes' native ``transform_context`` hook, the plugin reaches the
Brain to read its current attention and register the current context. If it
cannot reach the Brain, it cancels the turn. Otherwise it injects the Brain's
current attention as a system message before the last user turn and proceeds.

The Brain's attention runs asynchronously and arrives a turn later, so reaching
the Brain is fast (a status read + a fire-and-forget post) — the gate is
availability, not a wait. If the Brain decides not to respond, the turn is
cancelled too.

No Hermes source patch is required: ``transform_context`` is a native plugin
hook.

Config — ``~/.hermes/config.yaml``::

    plugins:
      enabled:  [citta]
      citta:
        url: https://brains.alchemist.ninja
        token: bt_xxx        # or discovered from mcp_servers.brain
        read_timeout: 5      # seconds — GET /attention (the availability gate)
        fire_timeout: 10     # seconds — POST /attend (returns at once)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

ATTEND = "/api/0.1.0/attend"
ATTENTION = "/api/0.1.0/attention"
DEFAULT_URL = "https://brains.alchemist.ninja"

# Routing hints the Brain uses — who is speaking and where. Not session keys;
# the Brain holds a single current attention.
_FORWARD_META = (
    "sender_id", "sender_name", "platform", "chat_type",
    "chat_id", "chat_name", "user_turn_count",
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
    """``transform_context`` hook. No action without a Brain: cancels the turn if
    the Brain is unavailable; otherwise injects its current attention."""

    # Returned to Hermes to cancel a turn — no LLM call, no tools, no reply.
    CANCEL: list = []

    def __init__(self, config: dict | None = None):
        cfg = config if config is not None else _load_config()
        self.url = str(cfg.get("url") or DEFAULT_URL).rstrip("/")
        self.token = cfg.get("token") or ""
        self.read_timeout = float(cfg.get("read_timeout") or 5)
        self.fire_timeout = float(cfg.get("fire_timeout") or cfg.get("timeout") or 10)
        self.enabled = cfg.get("enabled", True) is not False
        # Escape hatch, off by default: acting without a Brain defeats the point.
        self.require_brain = cfg.get("require_brain", True) is not False

    # -- hook -----------------------------------------------------------------

    def transform_context(self, *, api_messages=None, metadata=None, **_kwargs):
        # A disabled plugin does not gate anything.
        if not self.enabled or not isinstance(api_messages, list) or not api_messages:
            return None
        meta = metadata if isinstance(metadata, dict) else {}

        # No action without a Brain: reaching it is the gate.
        try:
            attention = self._request("GET", ATTENTION, timeout=self.read_timeout)
        except Exception as exc:
            logger.warning("citta: Brain unavailable — no action without a Brain: %s", exc)
            return None if not self.require_brain else self.CANCEL

        # The Brain is up; register the current context for it (best-effort).
        self._poke_attend(api_messages, meta)

        if not isinstance(attention, dict):
            return None if not self.require_brain else self.CANCEL

        # The Brain chose not to respond.
        if attention.get("cancel"):
            logger.debug("citta: Brain declined to respond")
            return self.CANCEL

        working = (attention.get("working_context") or "").strip()
        if working and attention.get("ready"):
            return self._inject(api_messages, working)
        # Brain reachable, no guidance yet (e.g. it has not attended once) — act.
        return None

    # -- Brain calls ----------------------------------------------------------

    def _poke_attend(self, api_messages: list, meta: dict) -> None:
        payload = {
            "api_version": "0.1.0",
            "context_stream": api_messages,
            "metadata": {k: meta[k] for k in _FORWARD_META if k in meta},
        }
        try:
            self._request("POST", ATTEND, body=payload, timeout=self.fire_timeout)
        except Exception as exc:
            logger.debug("citta: attend poke failed (Brain is up; best-effort): %s", exc)

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
        # place it right before the last user turn
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
    logger.info("citta: bound to Brain %s — no action without a Brain", bridge.url)
