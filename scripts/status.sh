#!/bin/sh
set -eu

plugin_root="${HERDR_PLUGIN_ROOT:?HERDR_PLUGIN_ROOT is not set}"
codex_home="${CODEX_HOME:-$HOME/.codex}"
python3 "$plugin_root/scripts/notify_config.py" status \
  "$codex_home/config.toml" \
  "$codex_home/herdr-codex-session-title-state.json" \
  "$codex_home/herdr-codex-session-title.py"
