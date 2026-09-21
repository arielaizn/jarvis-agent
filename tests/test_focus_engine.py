"""Deterministic focus contracts; these are not substitutes for live preflight."""
import json
from pathlib import Path
import tempfile
import unittest

from core.focus_engine import FocusEngine, LEDGER_KEYS, NAMED_CALLOUTS, NAMELESS_CALLOUTS, DRILL_CALLOUTS
from core.focus_surface import SurfaceReader


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ScriptedReader(SurfaceReader):
    """Exercise the real comparison boundary using injected native responses."""
    def __init__(self):
        super().__init__()
        self.app = {"readable": True, "bundle_id": "com.google.Chrome", "name": "Chrome", "pid": 987654}
        self.url = "http://localhost:4700/?mute=1"
        self.read_status = "ok"
        self.queries = 0
        self.browser_queries = 0

    def _frontmost(self):
        self.queries += 1
        self._native_status = "ok"
        return self.app

    def _browser_url(self, bundle):
        self.browser_queries += 1
        return (self.url, self.read_status) if self.read_status == "ok" else (None, self.read_status)


class FocusTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clock = Clock()
        self.reader = ScriptedReader()
        self.spoken = []
        self.engine = FocusEngine(self.reader, self.root / "ledger.jsonl",
                                  lambda text, kind: self.spoken.append((text, kind)), clock=self.clock)

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def advance(self, seconds, step=0.1):
        count = round(seconds / step)
        for _ in range(count):
            self.clock.now = round(self.clock.now + step, 8)
            self.engine.tick()

    def lock_work(self):
        self.engine.start(30)
        self.reader.url = "https://work.example/editor/start"
        self.advance(2.1)
        self.assertFalse(self.engine.state()["deferred"])
        self.assertTrue(self.engine.state()["tab_target"])


class TestFocusSessions(FocusTestCase):
    def test_home_defers_and_requires_two_foreground_ticks(self):
        state = self.engine.start()
        self.assertTrue(state["deferred"])
        self.assertIn("עבור", self.spoken[-1][0])
        self.reader.url = "https://work.example/path-a"
        self.advance(1)
        self.assertTrue(self.engine.state()["deferred"])
        self.assertEqual(self.engine.state()["settle_ticks"], 1)
        self.reader.url = "https://other.example"
        self.advance(1)
        self.assertTrue(self.engine.state()["deferred"])
        self.advance(1)
        self.assertFalse(self.engine.state()["deferred"])
        self.assertEqual(self.spoken[-1][1], "focus_locked")

    def test_target_is_host_not_full_spa_url(self):
        self.lock_work()
        self.reader.url = "https://work.example/editor/a?token=private#changed"
        self.advance(3)
        self.assertEqual(self.engine.state()["drifts"], 0)

    def test_drift_speaks_within_three_seconds_and_return_clears(self):
        self.lock_work()
        self.engine.command("intent", text="עריכת הסרטון")
        self.reader.url = "https://instagram.com/feed"
        self.advance(2.9)
        calls = [line for line, kind in self.spoken if kind == "focus_drift"]
        self.assertEqual(len(calls), 1)
        self.assertIn("Instagram", calls[0])
        self.assertIn("עריכת הסרטון", calls[0])
        self.assertEqual(self.engine.state()["drifts"], 1)
        self.reader.url = "https://work.example/elsewhere"
        self.advance(1.1)
        self.assertFalse(self.engine.state()["drifting"])

    def test_home_is_always_a_safe_surface(self):
        self.lock_work()
        self.reader.url = "http://127.0.0.1:4700/index.html?mute=1"
        self.advance(5)
        self.assertEqual(self.engine.state()["drifts"], 0)
        self.assertTrue(self.engine.state()["on_target"])

    def test_same_host_different_port_or_path_is_not_home(self):
        self.lock_work()
        self.reader.url = "http://localhost:4701/"
        self.advance(3)
        self.assertEqual(self.engine.state()["drifts"], 1)

    def test_tab_read_failure_defers_start_and_is_unknown_during_session(self):
        self.reader.read_status = "timeout"
        self.engine.start(from_home=False)
        self.assertTrue(self.engine.state()["deferred"])
        self.advance(5)
        self.assertEqual(self.engine.state()["settle_ticks"], 0)
        self.reader.read_status = "ok"
        self.reader.url = "https://work.example"
        self.advance(2.1)
        self.reader.read_status = "permission_or_script_error"
        self.advance(4)
        self.assertEqual(self.engine.state()["drifts"], 0)
        self.assertFalse(self.engine.state()["surface_known"])

    def test_staying_home_falls_back_to_app_only_after_45s(self):
        self.engine.start()
        self.advance(44)
        self.assertTrue(self.engine.state()["deferred"])
        self.advance(1.1)
        self.assertFalse(self.engine.state()["deferred"])
        self.assertTrue(self.engine.state()["app_target"])
        self.assertFalse(self.engine.state()["tab_target"])
        self.assertEqual(self.spoken[-1][1], "focus_locked_app_only")

    def test_unknown_surface_does_not_guess_fallback_from_background(self):
        self.engine.start()
        self.reader.app = None
        previous_browser_queries = self.reader.browser_queries
        self.advance(50)
        self.assertTrue(self.engine.state()["deferred"])
        self.assertEqual(self.reader.browser_queries, previous_browser_queries)

    def test_retarget_work_home_and_card(self):
        self.lock_work()
        self.reader.url = "https://research.example"
        self.advance(3)
        self.assertEqual(self.engine.state()["drifts"], 1)
        self.engine.command("retarget")
        self.assertEqual(self.engine.state()["drifts"], 0)
        self.assertEqual(self.engine.state()["seconds_adrift"], 0)
        self.reader.url = "http://localhost:4700/"
        self.engine.command("retarget")
        self.assertTrue(self.engine.state()["deferred"])
        self.reader.url = "https://editing.example"
        self.reader.app = {"readable": True, "bundle_id": "local.jarvis.focus-card", "name": "Card", "pid": 987655}
        self.engine.command("retarget", from_card=True)
        self.assertFalse(self.engine.state()["deferred"])
        self.assertTrue(self.engine.state()["tab_target"])
        self.assertEqual(self.spoken[-1][1], "focus_locked")

    def test_nonbrowser_retarget_locks_app_only(self):
        self.lock_work()
        self.reader.app = {"readable": True, "bundle_id": "com.blackmagic-design.DaVinciResolve", "name": "DaVinci Resolve", "pid": 4444}
        self.engine.command("retarget")
        self.assertTrue(self.engine.state()["app_target"])
        self.assertFalse(self.engine.state()["tab_target"])
        self.advance(2)
        self.assertEqual(self.engine.state()["drifts"], 0)

    def test_excuse_refunds_episode_and_stays_quiet_until_return(self):
        self.lock_work()
        self.reader.url = "https://youtube.com"
        self.advance(4)
        self.assertGreater(self.engine.state()["seconds_adrift"], 0)
        self.engine.command("excuse")
        spoken_before = len(self.spoken)
        self.advance(60)
        self.assertEqual(self.engine.state()["seconds_adrift"], 0)
        self.assertEqual(self.engine.state()["drifts"], 0)
        self.assertEqual(len(self.spoken), spoken_before)
        self.reader.url = "https://work.example"
        self.advance(1)
        self.assertFalse(self.engine.state()["excused"])
        self.reader.url = "https://youtube.com"
        self.advance(3)
        self.assertEqual(self.engine.state()["drifts"], 1)

    def test_cadence_snooze_pause_resume_extend_and_report(self):
        self.lock_work()
        self.engine.command("cadence", seconds=3)
        self.engine.command("snooze", seconds=15)
        self.reader.url = "https://reddit.com"
        self.advance(10)
        self.assertFalse(any(kind == "focus_drift" for _, kind in self.spoken))
        self.advance(7)
        self.assertTrue(any(kind == "focus_drift" for _, kind in self.spoken))
        self.engine.command("pause")
        remaining = self.engine.state()["seconds_remaining"]
        self.advance(30)
        self.assertEqual(remaining, self.engine.state()["seconds_remaining"])
        self.engine.command("resume")
        self.engine.command("extend", minutes=5)
        self.advance(1)
        self.assertEqual(self.engine.state()["planned_seconds"], 35 * 60)
        result = self.engine.command("end")
        self.assertFalse(result["on"])
        self.assertEqual(set(result["last_report"]), LEDGER_KEYS)
        self.assertEqual(self.spoken[-1][1], "focus_report")

    def test_intent_window_expires_and_long_intent_not_parroted(self):
        self.engine.start()
        self.advance(30.1)
        self.assertFalse(self.engine.state()["intent_window"])
        long_intent = "כתיבת התסריט הארוך " * 12
        self.engine.command("intent", text=long_intent)
        self.assertNotIn(long_intent, self.spoken[-1][0])

    def test_streak_persists_from_aggregate_ledger(self):
        self.lock_work()
        self.advance(10)
        self.engine.command("end")
        second = FocusEngine(ScriptedReader(), self.root / "ledger.jsonl", clock=self.clock)
        self.assertEqual(second.state()["streak"], 1)

    def test_all_escalation_pools_have_four_lines(self):
        for pools in (NAMED_CALLOUTS, NAMELESS_CALLOUTS, DRILL_CALLOUTS):
            self.assertEqual(len(pools), 3)
            self.assertTrue(all(len(pool) == 4 for pool in pools))

    def test_diag_does_not_add_settle_ticks(self):
        self.engine.start()
        self.reader.url = "https://work.example"
        self.advance(1)
        for _ in range(8):
            self.engine.diag()
        self.assertEqual(self.engine.state()["settle_ticks"], 1)
        self.assertTrue(self.engine.state()["deferred"])


class TestLocalEyes(FocusTestCase):
    def eyes(self, **signals):
        self.engine.command("posture", active=True, present=True, head_down=False, slouched=False, **signals)

    def test_phone_nudge_in_one_second_without_focus_and_relief_silences(self):
        self.engine.command("posture", active=True, present=True, head_down=True, slouched=False)
        self.advance(0.8)
        self.assertEqual(self.spoken[-1][1], "focus_head_down")
        self.engine.command("relief")
        before = len(self.spoken)
        for _ in range(40):
            self.engine.command("posture", active=True, present=True, head_down=True, slouched=False)
            self.advance(1)
        self.assertEqual(len(self.spoken), before)
        self.assertGreater(self.engine.state()["relief_remaining"], 130)

    def test_stale_signal_cannot_produce_new_nudges(self):
        self.engine.command("eyes", enabled=True, present=True, head_down=True, slouched=False)
        self.advance(1)
        before = len(self.spoken)
        self.advance(90)
        self.assertEqual(len(self.spoken), before)
        self.engine.command("eyes", enabled=True, present=True, head_down=True, slouched=False)
        self.advance(0.2)
        self.assertEqual(len(self.spoken), before)
        self.advance(0.6)
        self.assertEqual(len(self.spoken), before + 1)

    def test_absence_has_twelve_second_grace_and_phone_counts_as_drift(self):
        self.lock_work()
        for _ in range(11):
            self.engine.command("eyes", enabled=True, present=False, head_down=False, slouched=False)
            self.advance(1)
        self.assertEqual(self.engine.state()["drifts"], 0)
        self.engine.command("eyes", enabled=True, present=False, head_down=False, slouched=False)
        self.advance(1.1)
        self.assertEqual(self.engine.state()["drifts"], 1)
        self.assertEqual(self.spoken[-1][1], "focus_absent")


if __name__ == "__main__":
    unittest.main()
