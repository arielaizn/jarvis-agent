"""Server-owned focus sessions, with aggregate-only persistence.

Foreground identities live inside SurfaceReader. A distraction label exists only
as a local variable during the current tick and its synchronous speech callback.
Nothing from a screen, webcam, app identity or tab URL is written here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
import time

SURFACE_TICK_SECONDS = 1.0
ENGINE_LOOP_SECONDS = 0.1
DRIFT_GRACE_SECONDS = 0.8
SETTLE_TICKS_REQUIRED = 2
DEFERRED_APP_FALLBACK_SECONDS = 45.0
DEFAULT_SESSION_MINUTES = 30
MIN_SESSION_MINUTES = 0.05
MAX_SESSION_MINUTES = 480
DEFAULT_NAG_SECONDS = 30.0
MIN_NAG_SECONDS = 3.0
MAX_NAG_SECONDS = 3600.0
DEFAULT_SNOOZE_SECONDS = 15.0
MAX_SNOOZE_SECONDS = 3600.0
RELIEF_SECONDS = 180.0
POSTURE_DWELL_SECONDS = 0.7
ABSENCE_DWELL_SECONDS = 12.0
POSTURE_COOLDOWN_SECONDS = 30.0
EYES_SIGNAL_STALE_SECONDS = 3.0
CLEAN_STREAK_PERCENT = 85.0
MAX_INTENT_CHARACTERS = 300
SPOKEN_INTENT_CHARACTERS = 60
INTENT_WINDOW_SECONDS = 30.0
MAX_LEDGER_ROWS = 500
NAME_DISTRACTIONS = True
MAX_ESCALATION_TIER = 2
NAGS_PER_ESCALATION_TIER = 2

LEDGER_KEYS = frozenset({
    "timestamp", "planned_minutes", "active_minutes", "on_target_minutes", "drifts",
    "seconds_adrift", "percent", "completed",
})

NAMED_CALLOUTS = (
    (
        "אדוני, {label} יכול לחכות. חוזרים לעבודה.",
        "אדוני, {label} עדיין יהיה כאן אחרי שנגמור.",
        "{label}, אדוני? השעון ממשיך לספור.",
        "אדוני, נסגור את הסיבוב אצל {label} ונחזור.",
    ),
    (
        "אדוני, שוב אצל {label}. העבודה מחכה בחלון השני.",
        "{label} מקבל היום יותר תשומת לב מהמשימה, אדוני.",
        "אדוני, הביקור אצל {label} התארך. חוזרים.",
        "אדוני, עוד דקה אצל {label} היא דקה מתוך הזמן שקבענו.",
    ),
    (
        "אדוני, {label} מתחיל להפוך לפרויקט של היום.",
        "אדוני, מספיק עם {label}. בוא נסיים את מה שבאנו לעשות.",
        "{label} מסתדר בלעדיך, אדוני. המשימה פחות.",
        "אדוני, הגענו לסטייה מספר {drifts}. חוזרים מ־{label} עכשיו.",
    ),
)
NAMELESS_CALLOUTS = (
    ("אדוני, המשימה בחלון השני.", "אדוני, חוזרים למה שקבענו.",
     "השעון רץ, אדוני. בוא נחזור.", "אדוני, הסיבוב הקטן נגמר."),
    ("אדוני, שוב יצאנו מהמשימה.", "אדוני, העבודה עדיין מחכה.",
     "עוד סטייה, אדוני. נחזור עכשיו.", "אדוני, הריכוז ברח. נחזיר אותו."),
    ("אדוני, הסטיות מתחילות למלא את היום.", "אדוני, הגיע הזמן לסיים את המשימה.",
     "אדוני, אני סופר. זו סטייה מספר {drifts}.", "אדוני, מספיק סיבובים. לעבודה."),
)
DRILL_CALLOUTS = (
    ("אדוני, סוגרים את {label}. עכשיו לעבודה.", "אדוני, {label} מחוץ למשימה. חזרה.",
     "{label} יחכה, אדוני. מתחילים לעבוד.", "אדוני, הידיים מה־{label}. למשימה."),
    ("אדוני, שוב {label}. ביקשת שאקפיד. חזור לעבודה.",
     "אדוני, הסיבוב ב־{label} נגמר עכשיו.", "אדוני, {label} סגור עד סיום המשימה.",
     "אדוני, ראיתי את {label}. חזרה מייד."),
    ("אדוני, {label} סיים לקבל את הזמן שלך. לעבודה.",
     "אדוני, מספיק עם {label}. המשימה לפניך.", "אדוני, יוצאים מ־{label} ומסיימים.",
     "אדוני, זו סטייה מספר {drifts}. {label} יחכה עד שנסיים."),
)
PHONE_CALLOUTS = (
    "אדוני, הטלפון מקבל מבט ארוך. נחזור למשימה.",
    "אדוני, העיניים ירדו לטלפון. העבודה כאן.",
    "אדוני, נניח את הטלפון לרגע.",
    "אדוני, גם אני כאן. והמשימה עדיין פתוחה.",
)
SLOUCH_CALLOUTS = (
    "אדוני, הגב שלך מבקש שנזדקף קצת.",
    "אדוני, נרים מעט את הכתפיים. המסך לא בורח.",
    "אדוני, נשען אחורה ונתיישר רגע.",
    "אדוני, הכיסא אמור לתמוך בך. תן לו הזדמנות.",
)
ABSENCE_CALLOUTS = (
    "אדוני, הכיסא עובד לבד כבר כמה שניות.",
    "אדוני, כשאתה חוזר, המשימה כאן.",
    "אדוני, השעון נשאר איתי. אתה קצת חסר.",
    "אדוני, הפסקה ארוכה? אפשר להשהות את השעון.",
)
START_DEFERRED_LINE = "עבור למה שאתה עובד עליו ואנעל את המיקוד שם. במה מתמקדים?"
LOCKED_LINE = "ננעלתי, אדוני."
RETARGET_DEFERRED_LINE = "עבור ללשונית הרצויה, אדוני. אנעל את המיקוד כשתגיע."
PRIVACY_LINE = "אני אומר בקול מה הסיח אותך באותו רגע, ולא שומר את השם."

DIAG_SURFACE_KEYS = frozenset({
    "app_readable", "is_browser", "tab_read_status", "is_home", "hash_present",
    "surface_known", "own_process", "settle_ticks", "app_target", "tab_target",
    "app_on_target", "tab_on_target", "native_status",
})


def _number(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FocusEngine:
    def __init__(self, reader, ledger_path, on_say=None, *, clock=None):
        self.reader = reader
        self.ledger_path = Path(ledger_path)
        self.on_say = on_say or (lambda text, kind: None)
        self.clock = clock or time.monotonic
        self._mutex = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._last_poll = float("-inf")
        self._last_clock = self.clock()
        self._surface = {}
        self._pool_positions = defaultdict(int)
        self._on = False
        self._paused = False
        self._deferred = False
        self._started_at = ""
        self._started_clock = 0.0
        self._planned = 0.0
        self._active = 0.0
        self._adrift = 0.0
        self._drifts = 0
        self._episode_start = None
        self._episode_charged = 0.0
        self._episode_counted = False
        self._episode_excused = False
        self._episode_kind = ""
        self._last_nag = float("-inf")
        self._nag_count = 0
        self._cadence = DEFAULT_NAG_SECONDS
        self._snooze_until = 0.0
        self._relief_until = 0.0
        self._drill = False
        self._first_callout = True
        self._intent = ""
        self._intent_window = False
        self._intent_until = 0.0
        self._last_report = None
        self._ledger_status = "ok"
        self._tick_status = "idle"
        self._eyes_enabled = False
        self._eyes = {"present": True, "head_down": False, "slouched": False}
        self._eyes_updated = float("-inf")
        self._eyes_since = {"absent": None, "head_down": None, "slouched": None}
        self._posture_nag = float("-inf")
        self._streak = self._read_streak()

    def _say(self, text, kind):
        # No queue, replay buffer, event log, notes or stored last_speech field.
        try:
            self.on_say(text, kind)
        except Exception:
            # Transport errors must not kill the focus timer. No speech content
            # enters diagnostic logs, since it may include a transient label.
            self._tick_status = "speech_transport_error"

    def _pool(self, name, values):
        position = self._pool_positions[name]
        self._pool_positions[name] += 1
        return values[position % len(values)]

    def _poll(self, *, track_settle=True, from_card=False):
        try:
            observation = self.reader.poll(track_settle=track_settle, from_card=from_card)
        except Exception:
            observation = {"app_readable": False, "surface_known": False,
                           "tab_read_status": "reader_error", "native_status": "reader_error"}
        label = observation.pop("ephemeral_label", "")
        self._surface = {key: observation[key] for key in DIAG_SURFACE_KEYS if key in observation}
        return str(label)[:100]

    def start(self, minutes=DEFAULT_SESSION_MINUTES, from_home=True):
        minutes = _number(minutes, "minutes", MIN_SESSION_MINUTES, MAX_SESSION_MINUTES)
        _bool(from_home, "from_home")
        with self._mutex:
            if self._on:
                raise ValueError("a focus session is already running")
            now = self.clock()
            self.reader.clear_target()
            self._poll(track_settle=False)
            self._on = True
            self._paused = False
            self._planned = minutes * 60
            self._active = self._adrift = 0.0
            self._drifts = self._nag_count = 0
            self._started_at = _timestamp()
            self._started_clock = self._last_clock = now
            self._last_poll = now
            self._snooze_until = self._relief_until = 0.0
            self._first_callout = True
            self._intent = ""
            self._intent_window = True
            self._intent_until = now + INTENT_WINDOW_SECONDS
            self._last_report = None
            self._reset_episode()
            self._deferred = bool(from_home or self._surface.get("is_home")
                                  or not self._surface.get("surface_known"))
            if not self._deferred and not self.reader.lock_current():
                self._deferred = True
            self._tick_status = "ok"
            if self._deferred:
                self._say(START_DEFERRED_LINE, "focus_started_deferred")
            else:
                self._surface.update(app_target=True, tab_target=bool(self._surface.get("is_browser")),
                                     app_on_target=True, tab_on_target=True)
                self._say("ננעלתי, אדוני. במה מתמקדים?", "focus_started")
            return self.state()

    def _reset_episode(self):
        self._episode_start = None
        self._episode_charged = 0.0
        self._episode_counted = False
        self._episode_excused = False
        self._episode_kind = ""
        self._last_nag = float("-inf")

    def _refund_episode(self):
        self._adrift = max(0.0, self._adrift - self._episode_charged)
        if self._episode_counted:
            self._drifts = max(0, self._drifts - 1)
        self._episode_charged = 0.0
        self._episode_counted = False

    def _retarget(self, from_card=False, from_home=False):
        self._poll(track_settle=False, from_card=from_card)
        self._last_poll = self.clock()
        self._refund_episode()
        self._reset_episode()
        if from_home or self._surface.get("is_home") or not self._surface.get("surface_known"):
            self.reader.clear_target()
            self._deferred = True
            self._started_clock = self.clock()
            self._surface.update(app_target=False, tab_target=False, settle_ticks=0)
            self._say(RETARGET_DEFERRED_LINE, "focus_retarget_deferred")
        elif self.reader.lock_current():
            self._deferred = False
            self._surface.update(app_target=True, tab_target=bool(self._surface.get("is_browser")),
                                 app_on_target=True, tab_on_target=True, settle_ticks=0)
            self._say(LOCKED_LINE, "focus_locked")
        else:
            self._say("לא הצלחתי לקרוא את החלון הפעיל, אדוני. המיקוד מחכה לנעילה.", "focus_lock_error")

    def command(self, action, **params):
        with self._mutex:
            now = self.clock()
            if action == "start":
                return self.start(params.get("minutes", DEFAULT_SESSION_MINUTES), params.get("from_home", True))
            if action == "posture":
                params = dict(params)
                if "active" in params:
                    params["enabled"] = params.pop("active")
                action = "eyes"
            if action == "eyes":
                return self._update_eyes(now, **params)
            if action == "relief":
                self._relief_until = now + RELIEF_SECONDS
                self._say("שלוש דקות שקט, אדוני.", "focus_relief")
                return self.state()
            if action == "drill":
                self._drill = _bool(params.get("enabled", True), "enabled")
                self._say("אקפיד איתך, אדוני." if self._drill else "חוזרים לקצב הרגיל, אדוני.", "focus_drill")
                return self.state()
            if not self._on:
                raise ValueError("no focus session is running")
            if action in {"retarget", "lock"}:
                self._retarget(_bool(params.get("from_card", False), "from_card"),
                               _bool(params.get("from_home", params.get("from_jarvis", False)), "from_home"))
            elif action == "intent":
                text = params.get("text", params.get("intent", ""))
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("intent text is required")
                self._intent = " ".join(text.split())[:MAX_INTENT_CHARACTERS]
                self._intent_window = False
                self._say("רשמתי, אדוני.", "focus_intent")
            elif action == "pause":
                self._paused = True
                self._reset_episode()
                self._say("השעון בהשהיה, אדוני.", "focus_paused")
            elif action == "resume":
                self._paused = False
                self._last_clock = now
                self._say("ממשיכים, אדוני.", "focus_resumed")
            elif action == "extend":
                added = _number(params.get("minutes", 5), "minutes", MIN_SESSION_MINUTES, MAX_SESSION_MINUTES)
                if self._planned + added * 60 > MAX_SESSION_MINUTES * 60:
                    raise ValueError("session would exceed maximum duration")
                self._planned += added * 60
                self._say(f"הוספתי {added:g} דקות, אדוני.", "focus_extended")
            elif action == "snooze":
                seconds = _number(params.get("seconds", DEFAULT_SNOOZE_SECONDS), "seconds", 0, MAX_SNOOZE_SECONDS)
                self._snooze_until = now + seconds
                self._say(f"{seconds:g} שניות שקט, אדוני.", "focus_snoozed")
            elif action == "cadence":
                self._cadence = _number(params.get("seconds", DEFAULT_NAG_SECONDS), "seconds", MIN_NAG_SECONDS, MAX_NAG_SECONDS)
                self._say(f"אזכיר כל {self._cadence:g} שניות, אדוני.", "focus_cadence")
            elif action == "excuse":
                self._refund_episode()
                self._episode_excused = True
                self._say("מובן, אדוני. אשאיר אותך בשקט עד שתחזור.", "focus_excused")
            elif action in {"end", "abort"}:
                self._finish(completed=action == "end")
            else:
                raise ValueError("unknown focus action")
            return self.state()

    def _update_eyes(self, now, **params):
        enabled = _bool(params.get("enabled", self._eyes_enabled), "enabled")
        values = {key: _bool(params.get(key, self._eyes[key]), key) for key in self._eyes}
        stale = now - self._eyes_updated > EYES_SIGNAL_STALE_SECONDS
        self._eyes_enabled = enabled
        self._eyes_updated = now
        self._eyes = values
        for kind, active in (("absent", not values["present"]),
                             ("head_down", values["present"] and values["head_down"]),
                             ("slouched", values["present"] and values["slouched"])):
            if not enabled or not active:
                self._eyes_since[kind] = None
            elif self._eyes_since[kind] is None or stale:
                self._eyes_since[kind] = now
        # There is intentionally no microphone, camera or network API here.
        return self.state()

    def _eyes_kind(self, now):
        if not self._eyes_enabled or now - self._eyes_updated > EYES_SIGNAL_STALE_SECONDS:
            return ""
        for kind, grace in (("absent", ABSENCE_DWELL_SECONDS), ("head_down", POSTURE_DWELL_SECONDS),
                            ("slouched", POSTURE_DWELL_SECONDS)):
            since = self._eyes_since[kind]
            if since is not None and now - since >= grace:
                return kind
        return ""

    def _silent(self, now):
        return bool(now < self._snooze_until or now < self._relief_until or self._paused or self._episode_excused)

    def _speak_drift(self, label, kind, now):
        if self._silent(now):
            return
        if kind in {"head_down", "slouched", "absent"}:
            if now - self._posture_nag < POSTURE_COOLDOWN_SECONDS:
                return
            pools = {"head_down": PHONE_CALLOUTS, "slouched": SLOUCH_CALLOUTS, "absent": ABSENCE_CALLOUTS}
            self._say(self._pool(kind, pools[kind]), "focus_" + kind)
            self._posture_nag = now
        else:
            tier = min(MAX_ESCALATION_TIER, max(self._drifts - 1, self._nag_count // NAGS_PER_ESCALATION_TIER))
            if self._first_callout and self._intent and label and NAME_DISTRACTIONS:
                intent = self._intent if len(self._intent) <= SPOKEN_INTENT_CHARACTERS else "המשימה שקבענו"
                self._say(f"אדוני, {label} מרחיק אותנו מ־{intent}.", "focus_drift")
            else:
                named = bool(label and NAME_DISTRACTIONS)
                pools = DRILL_CALLOUTS if self._drill and named else NAMED_CALLOUTS if named else NAMELESS_CALLOUTS
                line = self._pool(("drill" if self._drill else "normal", named, tier), pools[tier])
                self._say(line.format(label=label, drifts=self._drifts), "focus_drift")
        self._first_callout = False
        self._last_nag = now
        self._nag_count += 1

    def tick(self):
        """Advance the live engine; public for deterministic timing/privacy tests."""
        with self._mutex:
            now = self.clock()
            dt = max(0.0, now - self._last_clock)
            self._last_clock = now
            if self._intent_window and now >= self._intent_until:
                self._intent_window = False
            label = ""
            polled = now - self._last_poll >= SURFACE_TICK_SECONDS
            if polled:
                label = self._poll(track_settle=self._on and self._deferred)
                self._last_poll = now
            self._tick_status = "ok"
            eye_kind = self._eyes_kind(now)
            if not self._on:
                if eye_kind and not self._silent(now):
                    self._speak_drift("", eye_kind, now)
                return
            if self._paused:
                return
            dt = min(dt, max(0.0, self._planned - self._active))
            self._active += dt
            if self._deferred:
                if polled and self._surface.get("settle_ticks", 0) >= SETTLE_TICKS_REQUIRED:
                    if self.reader.lock_current():
                        self._deferred = False
                        self._surface.update(app_target=True, tab_target=bool(self._surface.get("is_browser")),
                                             app_on_target=True, tab_on_target=True, settle_ticks=0)
                        self._say(LOCKED_LINE, "focus_locked")
                elif (polled and now - self._started_clock >= DEFERRED_APP_FALLBACK_SECONDS
                      and self._surface.get("is_home") and self.reader.lock_current(app_only=True)):
                    self._deferred = False
                    self._surface.update(app_target=True, tab_target=False, app_on_target=True, tab_on_target=True)
                    self._say("נעלתי את הדפדפן כאפליקציה, אדוני. אין כרגע נעילה על אתר.", "focus_locked_app_only")
            if not self._deferred:
                known = self._surface.get("surface_known", False)
                # A known different app is still a drift when its browser tab
                # cannot be read. A failed tab read in the target app is unknown.
                app_bad = bool(self._surface.get("app_readable") and self._surface.get("app_target")
                               and not self._surface.get("app_on_target") and not self._surface.get("is_home"))
                tab_bad = bool(known and self._surface.get("tab_target") and not self._surface.get("tab_on_target"))
                bad = bool(app_bad or tab_bad or eye_kind)
                if bad:
                    kind = "surface" if app_bad or tab_bad else eye_kind
                    if self._episode_start is None:
                        self._episode_start = now
                        self._episode_kind = kind
                    grace = 0.0 if kind != "surface" else DRIFT_GRACE_SECONDS
                    if now - self._episode_start >= grace and not self._episode_excused:
                        if not self._episode_counted:
                            self._episode_counted = True
                            self._drifts += 1
                        self._adrift += dt
                        self._episode_charged += dt
                        # Named callouts happen only in the poll that supplied
                        # the label. Never save one to wait out the grace timer.
                        if now - self._last_nag >= self._cadence and (polled or kind != "surface"):
                            self._speak_drift(label, kind, now)
                elif known or self._surface.get("is_home"):
                    self._reset_episode()
            if self._active >= self._planned:
                self._finish(completed=True)

    def _finish(self, *, completed):
        active = max(0.0, self._active)
        adrift = min(active, max(0.0, self._adrift))
        percent = (100.0 * (active - adrift) / active) if active else 100.0
        report = {
            "timestamp": _timestamp(), "planned_minutes": round(self._planned / 60, 3),
            "active_minutes": round(active / 60, 3), "on_target_minutes": round((active - adrift) / 60, 3),
            "drifts": self._drifts, "seconds_adrift": round(adrift, 3),
            "percent": round(percent, 2), "completed": bool(completed),
        }
        self._append_ledger(report)
        self._last_report = report
        self._streak = self._streak + 1 if completed and percent >= CLEAN_STREAK_PERCENT else 0
        self._on = self._paused = self._deferred = self._intent_window = False
        self.reader.clear_target()
        self._surface.update(app_target=False, tab_target=False, settle_ticks=0)
        intent = self._intent if len(self._intent) <= SPOKEN_INTENT_CHARACTERS else ""
        prefix = f"על {intent}: " if intent else ""
        self._say(f"{prefix}{(active - adrift) / 60:.1f} דקות במיקוד מתוך {self._planned / 60:g} שתכננו, "
                  f"אדוני. {self._drifts} סטיות. הרצף עומד על {self._streak}.", "focus_report")
        self._intent = ""
        self._reset_episode()

    def _append_ledger(self, report):
        if set(report) != LEDGER_KEYS:
            raise ValueError("focus ledger whitelist violation")
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(str(self.ledger_path), flags, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._ledger_status = "ok"
        except OSError:
            self._ledger_status = "write_failed"
            self._say("אדוני, דוח המיקוד לא נשמר לקובץ. התוצאה עדיין מופיעה על המסך.", "focus_ledger_error")

    def ledger(self):
        try:
            if not self.ledger_path.exists():
                return []
            rows = []
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                if not isinstance(item, dict) or set(item) != LEDGER_KEYS:
                    self._ledger_status = "invalid_record"
                    continue
                if (not isinstance(item["timestamp"], str) or type(item["completed"]) is not bool
                        or any(type(item[key]) not in {int, float} or not math.isfinite(item[key])
                               for key in LEDGER_KEYS - {"timestamp", "completed"})):
                    self._ledger_status = "invalid_record"
                    continue
                rows.append(item)
            return rows[-MAX_LEDGER_ROWS:]
        except (OSError, ValueError):
            self._ledger_status = "read_failed"
            return []

    def _read_streak(self):
        result = 0
        for item in reversed(self.ledger()):
            if item["completed"] and item["percent"] >= CLEAN_STREAK_PERCENT:
                result += 1
            else:
                break
        return result

    def state(self):
        with self._mutex:
            now = self.clock()
            return {
                "on": self._on, "paused": self._paused, "deferred": self._deferred,
                "active": self._on, "deferred_lock": self._deferred,
                "settle_ticks": int(self._surface.get("settle_ticks", 0)),
                "app_target": bool(self._surface.get("app_target")), "tab_target": bool(self._surface.get("tab_target")),
                "app_on_target": bool(self._surface.get("app_on_target")),
                "tab_on_target": bool(self._surface.get("tab_on_target")),
                "on_target": bool(self._on and not self._deferred and self._surface.get("surface_known")
                                  and self._surface.get("app_on_target")
                                  and (not self._surface.get("tab_target") or self._surface.get("tab_on_target"))
                                  and not self._eyes_kind(now)),
                "surface_known": bool(self._surface.get("surface_known")),
                "drifting": bool(self._episode_counted and not self._episode_excused),
                "excused": self._episode_excused, "snoozed": now < self._snooze_until,
                "snooze_remaining": max(0, math.ceil(self._snooze_until - now)),
                "relief_remaining": max(0, math.ceil(self._relief_until - now)),
                "relief": now < self._relief_until, "intent_window": self._intent_window,
                "intent_window_open": self._intent_window,
                "has_intent": bool(self._intent), "seconds_remaining": max(0, math.ceil(self._planned - self._active)),
                "remaining_seconds": max(0, math.ceil(self._planned - self._active)),
                "planned_seconds": round(self._planned, 3), "active_seconds": round(self._active, 3),
                "on_target_seconds": round(max(0.0, self._active - self._adrift), 3),
                "seconds_adrift": round(self._adrift, 3), "drifts": self._drifts,
                "streak": self._streak, "cadence_seconds": self._cadence,
                "drill_sergeant": self._drill, "eyes_enabled": self._eyes_enabled,
                "eyes_fresh": now - self._eyes_updated <= EYES_SIGNAL_STALE_SECONDS,
                "present": self._eyes["present"], "head_down": self._eyes["head_down"],
                "slouched": self._eyes["slouched"], "started_at": self._started_at,
                "tick_alive": bool(self._thread and self._thread.is_alive()),
                "tick_status": self._tick_status, "ledger_status": self._ledger_status,
                "last_report": dict(self._last_report) if self._last_report else None,
            }

    def diag(self):
        with self._mutex:
            # Read from this running engine's reader. This does not increment
            # settle ticks and cannot accidentally commit a target.
            self._poll(track_settle=False)
            result = dict(self._surface)
            result.update(deferred=self._deferred, on=self._on, paused=self._paused,
                          tick_alive=bool(self._thread and self._thread.is_alive()),
                          tick_status=self._tick_status, ledger_status=self._ledger_status,
                          intent_window=self._intent_window, excused=self._episode_excused,
                          drifts=self._drifts)
            return result

    def start_ticker(self):
        with self._mutex:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="jarvis-focus-tick", daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                self._tick_status = "tick_error"
            self._stop.wait(ENGINE_LOOP_SECONDS)

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=SURFACE_TICK_SECONDS + 3)
