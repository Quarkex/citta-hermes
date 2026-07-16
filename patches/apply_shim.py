#!/usr/bin/env python3
"""Minimal transform_context shim — the ONLY patch citta ever needs, and only
on Hermes builds that predate the native hook.

Modern Hermes (incl. the Quarkex fork) invokes ``transform_context`` in
``agent/conversation_loop.py`` right before the LLM call and lists it in
``VALID_HOOKS``. Where that is already true, citta needs no patch at all.

This shim adds *only* the hook — nothing else. It:
  1. ensures ``"transform_context"`` is in ``VALID_HOOKS`` (hermes_cli/plugins.py)
  2. verifies the invocation exists in conversation_loop.py; if it does not, it
     writes the exact ~12-line block to inject and exits non-zero so the
     installer can point you at it (we do not blind-inject into code we cannot
     recognise — that is how the old 2000-line-drift patch broke).

Idempotent. Usage: apply_shim.py --agent ~/.hermes/hermes-agent
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

INVOCATION = '''\
            # --- citta transform_context shim ---
            try:
                from hermes_cli.plugins import invoke_hook as _invoke_hook
                _ctx_results = _invoke_hook(
                    "transform_context",
                    api_messages=api_messages,
                    metadata={"iteration": locals().get("api_call_count", 0)},
                )
                for _ctx_r in _ctx_results:
                    if isinstance(_ctx_r, list) and _ctx_r:
                        api_messages = _ctx_r
                        break
            except Exception:
                pass
            # --- end citta shim ---
'''


def ensure_valid_hook(plugins_py: Path) -> bool:
    src = plugins_py.read_text(encoding="utf-8")
    if '"transform_context"' in src:
        print("  VALID_HOOKS: transform_context already present")
        return True
    m = re.search(r"VALID_HOOKS\s*:\s*Set\[str\]\s*=\s*\{", src)
    if not m:
        print("  ! could not find VALID_HOOKS to extend")
        return False
    insert_at = m.end()
    src = src[:insert_at] + '\n    "transform_context",' + src[insert_at:]
    plugins_py.write_text(src, encoding="utf-8")
    print("  VALID_HOOKS: added transform_context")
    return True


def check_invocation(loop_py: Path) -> bool:
    src = loop_py.read_text(encoding="utf-8")
    if re.search(r'invoke_hook\(\s*["\']transform_context["\']', src):
        print("  conversation_loop.py: transform_context already invoked")
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, help="path to hermes-agent")
    args = ap.parse_args()
    agent = Path(args.agent)

    plugins_py = agent / "hermes_cli" / "plugins.py"
    loop_py = agent / "agent" / "conversation_loop.py"
    for p in (plugins_py, loop_py):
        if not p.exists():
            print(f"  ! not found: {p}")
            return 1

    ensure_valid_hook(plugins_py)

    if check_invocation(loop_py):
        return 0

    out = agent.parent / "citta-transform_context.snippet.py"
    out.write_text(INVOCATION, encoding="utf-8")
    print("  ! conversation_loop.py does not invoke transform_context.")
    print(f"  ! Insert this block right before the LLM/provider call: {out}")
    print("  ! (search for where `api_messages` is finalized for the request).")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
