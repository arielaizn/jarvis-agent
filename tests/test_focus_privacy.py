"""Made-up identity probes against state, diagnostics, report, ledger and notes."""
import json
from pathlib import Path
import tempfile
import unittest

from core.focus_engine import FocusEngine, LEDGER_KEYS
from test_focus_engine import Clock, ScriptedReader

UNIQUE_LABEL = "copper-platypus-874921-never-in-canned-lines.example"


class TestFocusPrivacy(unittest.TestCase):
    def test_native_home_never_reads_or_settles_on_background_browser(self):
        reader = ScriptedReader()
        reader.url = "https://" + UNIQUE_LABEL + "/private"
        reader.poll()  # Establish the real previously observed browser.
        browser_queries = reader.browser_queries
        native_pid = 900001
        reader.register_home_pid(native_pid)
        reader.app = {"readable": True, "bundle_id": "org.python.python", "name": UNIQUE_LABEL, "pid": native_pid}
        for _ in range(3):
            observation = reader.poll()
            self.assertTrue(observation["is_home"])
            self.assertTrue(observation["app_readable"])
            self.assertTrue(observation["surface_known"])
            self.assertTrue(observation["app_on_target"])
            self.assertTrue(observation["tab_on_target"])
            self.assertFalse(observation["is_browser"])
            self.assertFalse(observation["hash_present"])
            self.assertEqual(observation["settle_ticks"], 0)
            self.assertEqual(observation["ephemeral_label"], "")
            self.assertNotIn(UNIQUE_LABEL, json.dumps(observation))
            self.assertNotIn(str(native_pid), json.dumps(observation))
        self.assertEqual(reader.browser_queries, browser_queries)
        self.assertNotIn(native_pid, reader.own_pids)

    def test_native_home_missing_bundle_is_known_and_retarget_defers(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = ScriptedReader()
            reader.url = "https://work.example/editor"
            reader.poll()
            reader.register_home_pid(900002)
            reader.app = {"readable": True, "bundle_id": None, "name": UNIQUE_LABEL, "pid": 900002}
            clock = Clock()
            engine = FocusEngine(reader, Path(directory) / "ledger.jsonl", clock=clock)
            state = engine.start(from_home=False)
            self.assertTrue(state["deferred"])
            self.assertTrue(engine.diag()["app_readable"])
            state = engine.command("retarget")
            self.assertTrue(state["deferred"])
            self.assertFalse(state["tab_target"])
            self.assertNotIn(UNIQUE_LABEL, json.dumps([state, engine.diag()]))
            # Only the explicit desktop-card flag may query a background browser.
            state = engine.command("retarget", from_card=True)
            self.assertFalse(state["deferred"])
            self.assertTrue(state["tab_target"])
            engine.close()

    def test_native_home_registration_replaces_previous_process(self):
        reader = ScriptedReader()
        reader.register_home_pid(900003)
        reader.register_home_pid(900004)
        self.assertEqual(reader.home_pids, {900004})
        reader.app = {"readable": True, "bundle_id": "org.python.python", "name": "Python", "pid": 900003}
        self.assertFalse(reader.poll()["is_home"])
        with self.assertRaises(ValueError):
            reader.register_home_pid(-1)
        with self.assertRaises(ValueError):
            reader.register_home_pid(True)

    def test_repeated_native_attach_does_not_reset_work_settling(self):
        reader = ScriptedReader()
        reader.register_home_pid(900005)
        reader.url = "https://work.example/editor"
        self.assertEqual(reader.poll()["settle_ticks"], 1)
        reader.register_home_pid(900005)
        self.assertEqual(reader.poll()["settle_ticks"], 2)

    def test_unique_label_spoken_once_tick_but_absent_everywhere_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / "notes"
            notes.mkdir()
            (notes / "untouched.md").write_text("Original note\n", encoding="utf-8")
            clock = Clock()
            reader = ScriptedReader()
            said = []
            engine = FocusEngine(reader, root / "ledger.jsonl", lambda text, kind: said.append(text), clock=clock)
            reader.url = "https://target-work.example/spa"
            engine.start(30, from_home=False)
            reader.url = "https://" + UNIQUE_LABEL + "/secret?token=NEVER-SEND-THIS"
            for _ in range(40):
                clock.now += 0.1
                engine.tick()
            self.assertTrue(any(UNIQUE_LABEL in line for line in said))
            public = [engine.state(), engine.diag()]
            public.append(engine.command("end"))
            public.append(engine.ledger())
            serialized = json.dumps(public, ensure_ascii=False)
            self.assertNotIn(UNIQUE_LABEL, serialized)
            self.assertNotIn("NEVER-SEND-THIS", serialized)
            self.assertNotIn("com.google.Chrome", serialized)
            self.assertNotIn("target-work.example", serialized)
            # An implementation that adds a transcript, episode log or capture
            # side effect is caught by scanning every file in this isolated root.
            for path in root.rglob("*"):
                if path.is_file():
                    value = path.read_text(encoding="utf-8")
                    self.assertNotIn(UNIQUE_LABEL, value)
                    self.assertNotIn("NEVER-SEND-THIS", value)
            self.assertEqual((notes / "untouched.md").read_text(), "Original note\n")
            self.assertEqual(len(list(notes.iterdir())), 1)
            # Engine attributes contain no label, host, URL or app identity.
            attrs = {key: value for key, value in vars(engine).items()
                     if isinstance(value, (dict, list, tuple, str, float, int, bool))}
            self.assertNotIn(UNIQUE_LABEL, repr(attrs))
            self.assertNotIn("target-work.example", repr(attrs))

    def test_ledger_rejects_any_additional_key_and_hides_poisoned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            engine = FocusEngine(ScriptedReader(), path, clock=Clock())
            record = {"timestamp": "2026-09-20T00:00:00+00:00", "planned_minutes": 30,
                      "active_minutes": 30, "on_target_minutes": 29, "drifts": 1,
                      "seconds_adrift": 60, "percent": 96.67, "completed": True}
            self.assertEqual(set(record), LEDGER_KEYS)
            with self.assertRaisesRegex(ValueError, "whitelist"):
                engine._append_ledger({**record, "label": UNIQUE_LABEL})
            self.assertFalse(path.exists())
            engine._append_ledger(record)
            stored = json.loads(path.read_text())
            self.assertEqual(set(stored), LEDGER_KEYS)
            path.write_text(json.dumps({**record, "app": UNIQUE_LABEL}) + "\n")
            self.assertEqual(engine.ledger(), [])
            self.assertNotIn(UNIQUE_LABEL, json.dumps(engine.state()))

    def test_reader_returns_hash_presence_never_hash_or_raw_identity(self):
        reader = ScriptedReader()
        reader.url = "https://" + UNIQUE_LABEL + "/private/path"
        observation = reader.poll()
        label = observation.pop("ephemeral_label")
        self.assertEqual(label, UNIQUE_LABEL)
        self.assertTrue(observation["hash_present"])
        self.assertNotIn(UNIQUE_LABEL, repr(observation))
        self.assertNotIn("com.google.Chrome", repr(observation))
        self.assertTrue(all(type(value) in {bool, int, str} for value in observation.values()))
        # Internal persistent reader data contains hashes, never the spoken label.
        reader_values = {key: value for key, value in vars(reader).items()
                         if key not in {"url", "app"}}
        self.assertNotIn(UNIQUE_LABEL, repr(reader_values))


if __name__ == "__main__":
    unittest.main()
