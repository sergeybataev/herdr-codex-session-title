# Herdr Codex Session Title

This Herdr plugin mirrors the current Codex chat name into the matching Herdr
agent name. A name set with Codex `/rename` wins; otherwise the generated Codex
title or first user message is used. Titles are normalized to Herdr's lowercase,
32-character agent-name format.

The integration uses Codex's documented top-level `notify` command and handles
`agent-turn-complete` notifications. It uses the exact `thread-id`, reads Codex
state locally and read-only, then sends `agent.rename` to Herdr's Unix socket.
Nothing is sent to another service.

Python 3.11 or newer is required.

## Install

```sh
herdr plugin install sergeybataev/herdr-codex-session-title --ref v0.0.1 --yes
herdr plugin action invoke install --plugin dev.bataev.herdr-codex-session-title
```

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
