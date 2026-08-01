# Herdr Codex Session Title

This Herdr plugin mirrors the current Codex chat name into the matching Herdr
agent and pane display names. A name set with Codex `/rename` wins; otherwise
the generated Codex title or first user message is used. Titles are normalized
to Herdr's lowercase, 32-character command-alias format while the readable title
is compacted to at most 40 characters at a word boundary and reported as pane
display metadata.

A lightweight local watcher synchronizes existing/resumed panes when the plugin
starts and watches Codex's session index for `/rename` changes. It prefers the
session ID printed by `/rename`, then `codex resume <id>` process arguments, and
only then Herdr's reported session identity. The watcher polls file metadata once
per second and reads recent pane contents only at startup or when the session
index changes.

The integration uses Codex's documented top-level `notify` command and handles
`agent-turn-complete` notifications. It uses the exact `thread-id`, reads Codex
state locally and read-only, and verifies that the thread is the pane's active
session before sending `agent.rename` to Herdr's Unix socket. Child and subagent
notifications cannot overwrite the parent session's pane title. Nothing is sent
to another service.

Python 3.11 or newer is required.

## Install

```sh
herdr plugin install sergeybataev/herdr-codex-session-title --ref v0.0.5 --yes
herdr plugin action invoke install --plugin dev.bataev.herdr-codex-session-title
herdr plugin action invoke watch --plugin dev.bataev.herdr-codex-session-title
```

The explicit `watch` action starts synchronization immediately in an already
running Herdr server. Future Herdr server starts launch it automatically.

Restart Codex sessions that were already running. New sessions load the notify
command at startup. The agent name is refreshed after every completed turn.

The installer preserves and chains an existing Codex notify command. It edits
only the top-level `notify` assignment in `~/.codex/config.toml`, records the
original assignment, and restores it exactly during uninstall.

## Status and uninstall

```sh
herdr plugin action invoke status --plugin dev.bataev.herdr-codex-session-title
herdr plugin action invoke uninstall --plugin dev.bataev.herdr-codex-session-title
herdr plugin uninstall dev.bataev.herdr-codex-session-title
```

The callback is failure-silent and always exits successfully so a title lookup
or Herdr outage cannot disturb Codex.

## Development

```sh
sh tests/run.sh
```
