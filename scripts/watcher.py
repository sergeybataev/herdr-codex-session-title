#!/usr/bin/env python3
"""Keep Codex pane titles synchronized at startup and after /rename."""

import fcntl
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time


ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CALLBACK_PATH = os.path.join(ROOT, "scripts", "herdr-codex-session-title.py")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def load_callback():
    spec = importlib.util.spec_from_file_location("herdr_codex_title_callback", CALLBACK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


callback = load_callback()


def screen_session_id(screen):
    matches = []
    for line in screen.splitlines():
        if "Session renamed to" in line:
            matches.extend(SESSION_ID.findall(line))
    return matches[-1].lower() if matches else None


def process_session_id(process_info):
    for process in process_info.get("foreground_processes", []):
        arguments = process.get("argv") or []
        for index, argument in enumerate(arguments):
            if argument in ("resume", "--resume") and index + 1 < len(arguments):
                match = SESSION_ID.fullmatch(arguments[index + 1])
                if match:
                    return match.group(0).lower()
            if argument.startswith("--resume="):
                match = SESSION_ID.fullmatch(argument.split("=", 1)[1])
                if match:
                    return match.group(0).lower()
    return None


def process_identity(process_info):
    group = process_info.get("foreground_process_group_id")
    processes = process_info.get("foreground_processes") or []
    pids = [str(process.get("pid")) for process in processes if process.get("pid") is not None]
    if group is None and not pids:
        return None
    return "{}:{}".format(group if group is not None else "", ",".join(pids))


def choose_session_id(agent, process_info, screen, cache=None):
    pane_id = agent.get("pane_id")
    identity = process_identity(process_info)
    from_screen = screen_session_id(screen)
    if from_screen:
        if cache is not None and pane_id and identity:
            cache[pane_id] = {"process_identity": identity, "session_id": from_screen}
        return from_screen
    cached = cache.get(pane_id) if cache is not None and pane_id else None
    if isinstance(cached, dict) and cached.get("process_identity") == identity:
        value = cached.get("session_id")
        if isinstance(value, str) and value:
            return value
    if cache is not None and pane_id and cached is not None:
        cache.pop(pane_id, None)
    from_process = process_session_id(process_info)
    if from_process:
        return from_process
    reported = agent.get("agent_session") or {}
    value = reported.get("value")
    return value if isinstance(value, str) and value else None


def herdr_command(*arguments, json_output=True):
    binary = os.environ.get("HERDR_BIN_PATH") or "herdr"
    try:
        completed = subprocess.run(
            [binary, *arguments],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if completed.returncode != 0:
            return None
        return json.loads(completed.stdout) if json_output else completed.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def sync_agent(agent, cache=None):
    if agent.get("agent") != "codex":
        return
    pane_id = agent.get("pane_id")
    socket_path = os.environ.get("HERDR_SOCKET_PATH")
    if not isinstance(pane_id, str) or not pane_id or not socket_path:
        return
    process_response = herdr_command("pane", "process-info", "--pane", pane_id) or {}
    process_info = ((process_response.get("result") or {}).get("process_info") or {})
    screen = herdr_command("agent", "read", pane_id, "--lines", "40", json_output=False) or ""
    session_id = choose_session_id(agent, process_info, screen, cache)
    if not session_id:
        return
    title = callback.resolve_title(callback.codex_home(), session_id, {"input-messages": []})
    if not title:
        return
    callback.rename_agent(socket_path, pane_id, callback.herdr_name(title, session_id))
    callback.report_display_title(socket_path, pane_id, title)


def load_session_cache(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_session_cache(path, cache):
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".session-cache-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def sync_all(cache=None, cache_path=None):
    response = herdr_command("agent", "list") or {}
    agents = ((response.get("result") or {}).get("agents") or [])
    before = json.dumps(cache, sort_keys=True) if cache is not None else None
    for agent in agents:
        try:
            sync_agent(agent, cache)
        except Exception:
            continue
    if cache is not None and cache_path and json.dumps(cache, sort_keys=True) != before:
        save_session_cache(cache_path, cache)


def file_signature(path):
    try:
        status = os.stat(path)
        return status.st_mtime_ns, status.st_size
    except OSError:
        return None


def main():
    state_dir = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if not state_dir or os.environ.get("HERDR_ENV") != "1" or not os.environ.get("HERDR_SOCKET_PATH"):
        return 0
    os.makedirs(state_dir, exist_ok=True)
    lock_path = os.path.join(state_dir, "watcher.lock")
    with open(lock_path, "a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        cache_path = os.path.join(state_dir, "session-cache.json")
        cache = load_session_cache(cache_path)
        index_path = os.path.join(callback.codex_home(), "session_index.jsonl")
        sync_all(cache, cache_path)
        previous = file_signature(index_path)
        while True:
            time.sleep(1)
            current = file_signature(index_path)
            if current != previous:
                previous = current
                sync_all(cache, cache_path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
