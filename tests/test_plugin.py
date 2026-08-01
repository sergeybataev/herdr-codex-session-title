import importlib.util
import json
import os
import socket
import sqlite3
import tempfile
import threading
import tomllib
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(__file__))


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notify_config = load_script("notify_config", "notify_config.py")
callback = load_script("title_callback", "herdr-codex-session-title.py")


class ConfigTests(unittest.TestCase):
    def test_existing_multiline_notify_is_preserved_and_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "config.toml")
            state = os.path.join(directory, "state.json")
            callback_path = os.path.join(directory, "callback.py")
            original = 'model = "test"\nnotify = [\n  "sh",\n  "/tmp/old.sh",\n]\n\n[tui]\nanimations = false\n'
            with open(config, "w", encoding="utf-8") as handle:
                handle.write(original)
            with open(callback_path, "w", encoding="utf-8") as handle:
                handle.write("# callback\n")

            notify_config.install(config, state, callback_path)
            notify_config.install(config, state, callback_path)
            with open(config, "rb") as handle:
                installed = tomllib.load(handle)
            self.assertEqual(installed["notify"], ["python3", callback_path])
            self.assertFalse(installed["tui"]["animations"])

            notify_config.uninstall(config, state, callback_path)
            with open(config, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_install_without_existing_notify_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "config.toml")
            state = os.path.join(directory, "state.json")
            callback_path = os.path.join(directory, "callback.py")
            original = 'model = "test"\n\n[tui]\nanimations = true\n'
            with open(config, "w", encoding="utf-8") as handle:
                handle.write(original)
            notify_config.install(config, state, callback_path)
            notify_config.uninstall(config, state, callback_path)
            with open(config, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_install_rejects_own_notify_without_restore_state(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "config.toml")
            state = os.path.join(directory, "state.json")
            callback_path = os.path.join(directory, "callback.py")
            with open(config, "w", encoding="utf-8") as handle:
                handle.write('notify = ["python3", {}]\n'.format(json.dumps(callback_path)))

            with self.assertRaises(SystemExit):
                notify_config.install(config, state, callback_path)
            self.assertFalse(os.path.exists(state))

    def test_uninstall_rejects_own_notify_without_restore_state(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "config.toml")
            state = os.path.join(directory, "state.json")
            callback_path = os.path.join(directory, "callback.py")
            original = 'notify = ["python3", {}]\n'.format(json.dumps(callback_path))
            with open(config, "w", encoding="utf-8") as handle:
                handle.write(original)

            with self.assertRaises(SystemExit):
                notify_config.uninstall(config, state, callback_path)
            with open(config, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_install_rejects_quoted_notify_key_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            config = os.path.join(directory, "config.toml")
            state = os.path.join(directory, "state.json")
            callback_path = os.path.join(directory, "callback.py")
            original = '"notify" = ["sh", "/tmp/old-notifier"]\n'
            with open(config, "w", encoding="utf-8") as handle:
                handle.write(original)

            with self.assertRaises(SystemExit):
                notify_config.install(config, state, callback_path)
            self.assertFalse(os.path.exists(state))
            with open(config, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)


class CallbackTests(unittest.TestCase):
    def make_database(self, directory):
        path = os.path.join(directory, "state_5.sqlite")
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, name TEXT, title TEXT, first_user_message TEXT)")
        connection.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?)",
            [
                ("named", "Explicit name", "Generated title", "First prompt"),
                ("indexed", None, "Generated title", "First prompt"),
                ("generated", None, "Generated title", "First prompt"),
            ],
        )
        connection.commit()
        connection.close()

    def capture_rename(self, directory, thread_id):
        socket_path = os.path.join(directory, "herdr-{}.sock".format(thread_id))
        received = []
        ready = threading.Event()

        def server():
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(socket_path)
            listener.listen(2)
            ready.set()
            for _ in range(2):
                connection, _ = listener.accept()
                payload = b""
                while not payload.endswith(b"\n"):
                    payload += connection.recv(65536)
                request = json.loads(payload)
                received.append(request)
                connection.sendall(b'{"id":"ok","result":{}}\n')
                connection.close()
            listener.close()

        worker = threading.Thread(target=server)
        worker.start()
        ready.wait(2)
        environment = {
            "CODEX_HOME": directory,
            "HERDR_ENV": "1",
            "HERDR_PANE_ID": "w1:p1",
            "HERDR_SOCKET_PATH": socket_path,
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            callback.handle(json.dumps({"type": "agent-turn-complete", "thread-id": thread_id, "input-messages": ["Fallback"]}))
        worker.join(2)
        self.assertFalse(worker.is_alive())
        return received

    def test_title_priority_and_socket_request(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_database(directory)
            with open(os.path.join(directory, "session_index.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": "indexed", "thread_name": "Custom indexed name"}) + "\n")
            named = self.capture_rename(directory, "named")
            indexed = self.capture_rename(directory, "indexed")
            generated = self.capture_rename(directory, "generated")
            self.assertEqual(named[0]["method"], "agent.rename")
            self.assertEqual(named[0]["params"], {"target": "w1:p1", "name": "explicit-name"})
            self.assertEqual(named[1]["method"], "pane.report_metadata")
            self.assertEqual(
                named[1]["params"],
                {
                    "pane_id": "w1:p1",
                    "source": "dev.bataev.herdr-codex-session-title",
                    "agent": "codex",
                    "display_agent": "Explicit name",
                    "title": "Explicit name",
                },
            )
            self.assertEqual(indexed[0]["params"]["name"], "custom-indexed-name")
            self.assertEqual(indexed[1]["params"]["display_agent"], "Custom indexed name")
            self.assertEqual(generated[0]["params"]["name"], "generated-title")
            self.assertEqual(generated[1]["params"]["display_agent"], "Generated title")

    def test_herdr_name_is_valid_and_deterministic(self):
        self.assertEqual(callback.herdr_name("123 Very Long Session Title " * 3, "thread"), "codex-123-very-long-session-titl")
        self.assertEqual(callback.herdr_name("Привет", "019f-bee8"), "codex-019fbee8")

    def test_previous_notifier_is_chained(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, callback.STATE_NAME), "w", encoding="utf-8") as handle:
                json.dump({"previous_notify": ["old-notifier", "--flag"]}, handle)
            raw = '{"type":"ignored"}'
            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": directory}, clear=False),
                mock.patch.object(callback.subprocess, "Popen") as popen,
            ):
                callback.handle(raw)
            popen.assert_called_once_with(
                ["old-notifier", "--flag", raw],
                stdin=callback.subprocess.DEVNULL,
                stdout=callback.subprocess.DEVNULL,
                stderr=callback.subprocess.DEVNULL,
                start_new_session=True,
            )

    def test_previous_notifier_never_chains_this_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, callback.STATE_NAME), "w", encoding="utf-8") as handle:
                json.dump({"previous_notify": ["python3", callback.__file__]}, handle)
            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": directory}, clear=False),
                mock.patch.object(callback.subprocess, "Popen") as popen,
            ):
                callback.handle('{"type":"ignored"}')
            popen.assert_not_called()

    def test_malformed_notification_never_raises(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": tempfile.gettempdir()}, clear=False):
            callback.main(["callback", "not-json"])


if __name__ == "__main__":
    unittest.main()
