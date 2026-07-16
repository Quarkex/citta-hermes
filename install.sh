#!/usr/bin/env bash
# citta — Hermes ⇆ Brain attention bridge, one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Quarkex/citta-hermes/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --token bt_xxx --url https://brains.alchemist.ninja
#
# What it does (idempotent):
#   1. locates ~/.hermes  (or $HERMES_HOME / --home)
#   2. installs the citta plugin into ~/.hermes/plugins/citta/
#   3. verifies Hermes has the native `transform_context` hook
#        - present  → no source patch (the normal case)
#        - absent   → applies the minimal shim (patches/apply_shim.py)
#   4. writes plugins.citta (url/token) + enables it in config.yaml
#   5. disables the superseded Brain memory prefetch provider, if present
#
# No secrets are baked into the plugin — the token lives only in your config.yaml.

set -euo pipefail

REPO_URL="https://github.com/Quarkex/citta-hermes.git"
RAW_BASE="https://raw.githubusercontent.com/Quarkex/citta-hermes/main"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
URL=""
TOKEN=""
KEEP_MEMORY_PROVIDER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --home)  HERMES_HOME="$2"; shift 2 ;;
    --url)   URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --keep-memory-provider) KEEP_MEMORY_PROVIDER=1; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;36m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

[[ -d "$HERMES_HOME" ]] || die "Hermes home not found: $HERMES_HOME (set --home or \$HERMES_HOME)"
AGENT_DIR="$HERMES_HOME/hermes-agent"

# --- locate the repo source (local checkout, or clone for the piped one-liner) ---
SRC=""
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "$SELF_DIR" && -f "$SELF_DIR/plugins/citta/__init__.py" ]]; then
  SRC="$SELF_DIR"
else
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  say "fetching citta-hermes…"
  git clone --depth 1 "$REPO_URL" "$TMP/citta-hermes" >/dev/null 2>&1 \
    || die "git clone failed ($REPO_URL)"
  SRC="$TMP/citta-hermes"
fi

# --- 1. install the plugin ---
DEST="$HERMES_HOME/plugins/citta"
mkdir -p "$DEST"
cp "$SRC/plugins/citta/__init__.py" "$SRC/plugins/citta/plugin.yaml" "$SRC/plugins/citta/configure.py" "$DEST/"
ok "installed plugin → $DEST"

# --- 2. verify the native transform_context hook ---
PATCH_NEEDED=0
if [[ -d "$AGENT_DIR" ]]; then
  if grep -rq '"transform_context"' "$AGENT_DIR/hermes_cli/plugins.py" 2>/dev/null \
     && grep -rq 'transform_context' "$AGENT_DIR/agent/conversation_loop.py" 2>/dev/null; then
    ok "native transform_context hook present — no source patch needed"
  else
    warn "this Hermes lacks the transform_context hook"
    PATCH_NEEDED=1
  fi
else
  warn "hermes-agent source not found at $AGENT_DIR — skipping hook check"
fi

if [[ "$PATCH_NEEDED" == "1" ]]; then
  say "applying minimal shim (adds only the transform_context hook)…"
  if python3 "$SRC/patches/apply_shim.py" --agent "$AGENT_DIR"; then
    ok "shim applied"
  else
    warn "shim could not be applied automatically — see $SRC/patches/README.md"
  fi
fi

# --- 3. configure ---
say "configuring $HERMES_HOME/config.yaml…"
CFG_ARGS=(--home "$HERMES_HOME")
[[ -n "$URL" ]]   && CFG_ARGS+=(--url "$URL")
[[ -n "$TOKEN" ]] && CFG_ARGS+=(--token "$TOKEN")
[[ "$KEEP_MEMORY_PROVIDER" == "0" ]] && CFG_ARGS+=(--disable-old)
python3 "$DEST/configure.py" "${CFG_ARGS[@]}"

echo
ok "citta installed. Restart Hermes to load it."
say "verify:  hermes plugins list | grep citta"
say "config:  plugins.citta in $HERMES_HOME/config.yaml"
