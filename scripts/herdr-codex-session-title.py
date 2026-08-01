#!/usr/bin/env python3
"""Failure-silent Codex notify callback that renames the matching Herdr agent."""

import glob
import json
import os
import socket
import sqlite3
import subprocess
import sys
import uuid

MAX_TITLE_CHARS = 120
STATE_NAME = "herdr-codex-session-title-state.json"


def clean_title(value):
    if not isinstance(value, str):
        return None
    value = "".join(" " if ord(character) < 32 or ord(character) == 127 else character for character in value)
    value = " ".join(value.split())
    return value[:MAX_TITLE_CHARS] or None


def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def database_titles(home, thread_id):
    paths = glob.glob(os.path.join(home, "state_*.sqlite"))
    paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    for path in paths:
        try:
            connection = sqlite3.connect("file:{}?mode=ro".format(path), uri=True, timeout=0.2)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                wanted = [name for name in ("name", "title", "first_user_message") if name in columns]
                if "id" not in columns or not wanted:
                    continue
                row = connection.execute(
                    "SELECT {} FROM threads WHERE id = ?".format(", ".join(wanted)),
                    (thread_id,),
                ).fetchone()
                if row:
                    values = dict(zip(wanted, row))
                    explicit = clean_title(values.get("name"))
                    fallback = clean_title(values.get("title")) or clean_title(values.get("first_user_message"))
                    return explicit, fallback
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            continue
    return None, None


def indexed_name(home, thread_id):
    result = None
    try:
        with open(os.path.join(home, "session_index.jsonl"), encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if thread_id not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("id") == thread_id:
                    result = clean_title(record.get("thread_name")) or result
    except OSError:
        pass
    return result


def notification_title(notification):
    messages = notification.get("input-messages")
    if not isinstance(messages, list):
        return None
    for message in messages:
        title = clean_title(message)
        if title:
            return title
    return None


def resolve_title(home, thread_id, notification):
    explicit, fallback = database_titles(home, thread_id)
    return explicit or indexed_name(home, thread_id) or fallback or notification_title(notification)


def rename_agent(socket_path, pane_id, title):
    request = {
        "id": "plugin:codex-title:" + uuid.uuid4().hex,
        "method": "agent.rename",
        "params": {"target": pane_id, "name": title},
    }
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.5)
    try:
        client.connect(socket_path)
        client.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
        try:
            client.recv(4096)
        except OSError:
            pass
    finally:
        client.close()


def previous_notify(home):
    try:
        with open(os.path.join(home, STATE_NAME), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    command = state.get("previous_notify") if isinstance(state, dict) else None
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        return None
    callback = os.path.realpath(__file__)
    executable = os.path.realpath(os.path.expanduser(command[0]))
    script = os.path.realpath(os.path.expanduser(command[1])) if len(command) > 1 else None
    if executable == callback or script == callback:
        return None
    return command


def chain_previous(home, raw_notification):
    command = previous_notify(home)
    if not command:
        return
    try:
        subprocess.Popen(
            command + [raw_notification],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def handle(raw_notification):
    home = codex_home()
    try:
        notification = json.loads(raw_notification)
        if not isinstance(notification, dict) or notification.get("type") != "agent-turn-complete":
            return
        if os.environ.get("HERDR_ENV") != "1":
            return
        pane_id = os.environ.get("HERDR_PANE_ID")
        socket_path = os.environ.get("HERDR_SOCKET_PATH")
        thread_id = notification.get("thread-id")
        if not all(isinstance(item, str) and item for item in (pane_id, socket_path, thread_id)):
            return
        title = resolve_title(home, thread_id, notification)
        if title:
            rename_agent(socket_path, pane_id, title)
    finally:
        chain_previous(home, raw_notification)


def main(argv):
    if len(argv) != 2:
        return 0
    try:
        handle(argv[1])
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
