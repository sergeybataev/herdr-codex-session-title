#!/bin/sh
set -eu

plugin_root="${HERDR_PLUGIN_ROOT:?HERDR_PLUGIN_ROOT is not set}"
codex_home="${CODEX_HOME:-$HOME/.codex}"
callback="$codex_home/herdr-codex-session-title.py"
config="$codex_home/config.toml"
state="$codex_home/herdr-codex-session-title-state.json"

python3 "$plugin_root/scripts/notify_config.py" uninstall "$config" "$state" "$callback"
rm -f "$callback"
echo "uninstalled Codex title notification"
