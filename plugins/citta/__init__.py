"""citta — binds a Hermes agent to a Brain.

Once bound, the agent is the Brain's voice: **no action without a Brain.** Each
turn, via Hermes' native ``transform_context`` hook, the agent asks the Brain to
attend to the current context and **waits for it to finish**, then answers with
the Brain's guidance injected. The Brain takes its time — its attention runs
deep — and the agent does not act until it is done.

If the Brain is unavailable (unreachable, or it does not finish within the
deadline), the agent does not act: the turn is cancelled (no LLM call, no tools,
no reply). This is fail-*closed* by design: the Brain is not an optional
enhancement, it is the condition for the agent to act at all. If the Brain
decides not to respond, the turn is cancelled too.

No Hermes source patch is required: ``transform_context`` is a native plugin
hook.

Config — ``~/.hermes/config.yaml``::

    plugins:
      enabled:  [citta]
      citta:
        url: https://brains.alchemist.ninja
        token: bt_xxx           # or discovered from mcp_servers.brain
        attend_deadline: 180    # seconds — max wait for the Brain to attend
        poll_interval: 2        # seconds — how often to check while it thinks
        http_timeout: 10        # seconds — per request
"""

from __future__ import annotations

import json
import logging
import time
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
    """``transform_context`` hook. No action without a Brain: asks the Brain to
    attend, waits for it, injects its attention — or cancels the turn if the
    Brain is unavailable or declines."""

    # Returned to Hermes to cancel a turn — no LLM call, no tools, no reply.
    CANCEL: list = []

    def __init__(self, config: dict | None = None):
        cfg = config if config is not None else _load_config()
        self.url = str(cfg.get("url") or DEFAULT_URL).rstrip("/")
        self.token = cfg.get("token") or ""
        self.http_timeout = float(cfg.get("http_timeout") or cfg.get("fire_timeout") or 10)
        self.attend_deadline = float(cfg.get("attend_deadline") or 180)
        self.poll_interval = float(cfg.get("poll_interval") or 2)
        self.enabled = cfg.get("enabled", True) is not False
        # Escape hatch, off by default: acting without a Brain defeats the point.
        self.require_brain = cfg.get("require_brain", True) is not False

    # -- hook -----------------------------------------------------------------

    def transform_context(self, *, api_messages=None, metadata=None, **_kwargs):
        # A disabled plugin does not gate anything.
        if not self.enabled or not isinstance(api_messages, list) or not api_messages:
            return None
        meta = metadata if isinstance(metadata, dict) else {}

        try:
            attention = self._attend_and_wait(api_messages, meta)
        except _BrainUnavailable as exc:
            logger.warning("citta: Brain unavailable — no action without a Brain: %s", exc)
            return None if not self.require_brain else self.CANCEL

        if attention.get("cancel"):
            logger.debug("citta: Brain declined to respond")
            return self.CANCEL

        working = (attention.get("working_context") or "").strip()
        if working:
            return self._inject(api_messages, working)
        # The Brain attended but produced no guidance — it is present; act.
        return None

    # -- attend + wait --------------------------------------------------------

    def _attend_and_wait(self, api_messages: list, meta: dict) -> dict:
        """Ask the Brain to attend to this context and block until it finishes.
        Raises _BrainUnavailable if it is unreachable or misses the deadline."""
        payload = {
            "api_version": "0.1.0",
            "context_stream": api_messages,
            "metadata": {k: meta[k] for k in _FORWARD_META if k in meta},
        }
        deadline = time.monotonic() + self.attend_deadline

        # Start the mind on this context. If it is busy (single mind, one thing
        # at a time), wait for it to free up, then start it on ours.
        while True:
            status = self._request("POST", ATTEND, body=payload).get("status")
            if status == "attending":
                break
            if status == "already_attending":
                self._wait_idle(deadline)
                continue
            raise _BrainUnavailable(f"unexpected attend status: {status!r}")

        # Wait for the mind to finish attending to it.
        while True:
            if time.monotonic() > deadline:
                raise _BrainUnavailable("attention deadline exceeded")
            att = self._request("GET", ATTENTION)
            if not att.get("attending"):
                return att
            time.sleep(self.poll_interval)

    def _wait_idle(self, deadline: float) -> None:
        while True:
            if time.monotonic() > deadline:
                raise _BrainUnavailable("attention deadline exceeded (Brain stayed busy)")
            if not self._request("GET", ATTENTION).get("attending"):
                return
            time.sleep(self.poll_interval)

    def _request(self, method: str, path: str, *, body=None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise _BrainUnavailable(str(exc)) from exc
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


class _BrainUnavailable(Exception):
    """The Brain could not be reached, or did not answer in time."""


def register(ctx) -> None:
    """Plugin entry point — wire the attention bridge into Hermes."""
    bridge = CittaBridge()
    ctx.register_hook("transform_context", bridge.transform_context)
    logger.info("citta: bound to Brain %s — no action without a Brain", bridge.url)
