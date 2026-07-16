#!/usr/bin/env python3
"""Idempotent config.yaml editor for the citta plugin.

Ensures ``plugins.citta`` is set (url/token), enables the plugin in
``plugins.enabled``, and — under ``--disable-old`` — turns off the superseded
Brain ``MemoryProvider`` (``memory.provider: brain``), since Manasikara's
``attend`` already recalls. Always backs up config.yaml first.

Usage:
    configure.py [--home DIR] [--url URL] [--token TOKEN] [--disable-old]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required (pip install pyyaml)")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=str(Path.home() / ".hermes"))
    ap.add_argument("--url", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--disable-old", action="store_true")
    args = ap.parse_args()

    home = Path(args.home)
    cfg_path = home / "config.yaml"
    root = _load(cfg_path)

    if cfg_path.exists():
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = cfg_path.with_suffix(f".yaml.bak-{stamp}")
        shutil.copy2(cfg_path, backup)
        print(f"  backed up config → {backup.name}")

    plugins = root.setdefault("plugins", {})
    citta = plugins.setdefault("citta", {})

    # Token: explicit arg > existing citta.token > mcp_servers.brain bearer.
    token = args.token or citta.get("token") or ""
    if not token:
        mcp = (root.get("mcp_servers") or {}).get("brain") or {}
        auth = (mcp.get("headers") or {}).get("Authorization", "") or ""
        token = auth[7:] if auth.startswith("Bearer ") else auth

    if args.url:
        citta["url"] = args.url
    citta.setdefault("url", "https://brains.alchemist.ninja")
    if token:
        citta["token"] = token
    citta["enabled"] = True

    enabled = plugins.setdefault("enabled", [])
    if not isinstance(enabled, list):
        enabled = []
        plugins["enabled"] = enabled
    if "citta" not in enabled:
        enabled.append("citta")
        print("  enabled plugin: citta")
    else:
        print("  plugin already enabled: citta")

    if args.disable_old:
        mem = root.get("memory") or {}
        if mem.get("provider") == "brain":
            mem["provider"] = ""
            root["memory"] = mem
            print("  disabled superseded Brain MemoryProvider (memory.provider)")

    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(root, f, default_flow_style=False, sort_keys=True, allow_unicode=True)

    shown = (token[:6] + "…") if token else "(none — set with --token)"
    print(f"  citta.url={citta['url']}  citta.token={shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
