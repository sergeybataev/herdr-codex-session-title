#!/bin/sh
set -eu

plugin_root="${HERDR_PLUGIN_ROOT:?HERDR_PLUGIN_ROOT is not set}"
codex_home="${CODEX_HOME:-$HOME/.codex}"
callback="$codex_home/herdr-codex-session-title.py"
config="$codex_home/config.toml"
state="$codex_home/herdr-codex-session-title-state.json"

command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
  echo "python 3.11 or newer is required" >&2
  exit 1
}
mkdir -p "$codex_home"
cp "$plugin_root/scripts/herdr-codex-session-title.py" "$callback"
chmod 0700 "$callback"
python3 "$plugin_root/scripts/notify_config.py" install "$config" "$state" "$callback"
echo "installed: $callback"
echo "restart already-running Codex sessions to load the notify command"
