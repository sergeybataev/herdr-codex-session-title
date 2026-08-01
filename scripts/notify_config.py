#!/usr/bin/env python3
"""Safely install and restore the top-level Codex notify assignment."""

import json
import os
import re
import sys
import tempfile
import tomllib


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return ""


def parse_config(text):
    try:
        data = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as error:
        raise SystemExit("error: Codex config is not valid TOML: {}".format(error))
    notify = data.get("notify")
    if notify is not None and (
        not isinstance(notify, list)
        or not notify
        or not all(isinstance(part, str) and part for part in notify)
    ):
        raise SystemExit("error: top-level Codex notify must be a non-empty string array")
    return notify


def notify_span(text):
    """Return the byte span of the root notify assignment, preserving layout."""
    offset = 0
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("["):
            break
        if re.match(r"^\s*notify\s*=", line):
            candidate = ""
            end = offset
            for part in lines[index:]:
                candidate += part
                end += len(part)
                try:
                    parsed = tomllib.loads(candidate)
                except tomllib.TOMLDecodeError:
                    continue
                if "notify" in parsed:
                    return offset, end
            raise SystemExit("error: could not locate the end of the notify assignment")
        offset += len(line)
    return None


def insertion_offset(text):
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("["):
            return offset
        offset += len(line)
    return len(text)


def notify_assignment(command):
    return "notify = {}\n".format(json.dumps(command, ensure_ascii=True))


def atomic_write(path, text, mode=0o600):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    current_mode = mode
    try:
        current_mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        pass
    descriptor, temporary = tempfile.mkstemp(prefix=".herdr-title-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, current_mode)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise SystemExit("error: integration state is unreadable: {}".format(error))
    if not isinstance(value, dict):
        raise SystemExit("error: integration state is malformed")
    return value


def install(config_path, state_path, callback_path):
    text = read_text(config_path)
    current = parse_config(text)
    span = notify_span(text)
    if current is not None and span is None:
        raise SystemExit("error: existing Codex notify assignment uses an unsupported TOML key form")
    ours = ["python3", callback_path]
    state = load_state(state_path)
    if state is not None:
        if state.get("previous_notify") == ours:
            raise SystemExit("error: refusing recursive Codex notify restore state")
        if current == ours:
            print("Codex title notification already installed")
            return
        if current != state.get("previous_notify"):
            raise SystemExit("error: integration state exists but Codex notify changed")
    else:
        if current == ours:
            raise SystemExit("error: Codex notify references this plugin but restore state is missing")
        state = {
            "previous_notify": current,
            "previous_assignment": text[slice(*span)] if span else None,
        }
        atomic_write(state_path, json.dumps(state, indent=2) + "\n")

    replacement = notify_assignment(ours)
    if span:
        updated = text[: span[0]] + replacement + text[span[1] :]
    else:
        at = insertion_offset(text)
        prefix = text[:at]
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        updated = prefix + replacement + text[at:]
    atomic_write(config_path, updated)
    print("registered Codex agent-turn-complete notification")


def uninstall(config_path, state_path, callback_path):
    state = load_state(state_path)
    if state is None:
        if parse_config(read_text(config_path)) == ["python3", callback_path]:
            raise SystemExit("error: Codex notify references this plugin but restore state is missing")
        print("Codex title notification is not installed")
        return
    text = read_text(config_path)
    ours = ["python3", callback_path]
    if parse_config(text) != ours:
        raise SystemExit("error: Codex notify changed; config left untouched")
    span = notify_span(text)
    if not span:
        raise SystemExit("error: installed notify assignment is missing")
    previous = state.get("previous_assignment")
    replacement = previous if isinstance(previous, str) else ""
    atomic_write(config_path, text[: span[0]] + replacement + text[span[1] :])
    os.unlink(state_path)
    print("restored previous Codex notification configuration")


def status(config_path, state_path, callback_path):
    current = parse_config(read_text(config_path))
    ours = ["python3", callback_path]
    state_exists = load_state(state_path) is not None
    callback_exists = os.path.isfile(callback_path)
    print("callback: {}".format("installed" if callback_exists else "missing"))
    print("notify: {}".format("registered" if current == ours else "not registered"))
    print("restore state: {}".format("present" if state_exists else "missing"))
    return 0 if callback_exists and current == ours and state_exists else 1


def main(argv):
    if len(argv) != 5 or argv[1] not in ("install", "uninstall", "status"):
        print("usage: notify_config.py install|uninstall|status CONFIG STATE CALLBACK", file=sys.stderr)
        return 2
    action, config_path, state_path, callback_path = argv[1:]
    if action == "install":
        install(config_path, state_path, callback_path)
        return 0
    if action == "uninstall":
        uninstall(config_path, state_path, callback_path)
        return 0
    return status(config_path, state_path, callback_path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
