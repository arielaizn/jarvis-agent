"""Privacy boundary for fresh native foreground and Chrome front-window reads.

Only this module ever sees app identities or URLs. The engine receives booleans,
statuses and a label for one spoken callback. URL paths are never used as targets.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit

NATIVE_TIMEOUT_SECONDS = 2.0
BROWSER_TIMEOUT_SECONDS = 1.5
COMPILE_TIMEOUT_SECONDS = 60
HOME_PORT = 4700
HOME_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
HOME_PATHS = frozenset({"", "/", "/index.html"})
CHROME_BUNDLES = frozenset({
    "com.google.Chrome", "com.google.Chrome.canary", "com.brave.Browser",
    "com.microsoft.edgemac", "org.chromium.Chromium", "com.vivaldi.Vivaldi",
    "company.thebrowser.Browser", "com.operasoftware.Opera",
})
OWN_BUNDLES = frozenset({"local.jarvis.focus-card", "com.jarvis.focuscard"})
DISTRACTION_HOST_NAMES = {
    "instagram.com": "Instagram", "youtube.com": "YouTube", "youtu.be": "YouTube",
    "x.com": "X", "twitter.com": "X", "reddit.com": "Reddit", "tiktok.com": "TikTok",
    "netflix.com": "Netflix", "mail.google.com": "Gmail", "gmail.com": "Gmail",
    "slack.com": "Slack",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spoken_host(host: str) -> str:
    host = host.removeprefix("www.")
    for domain, name in DISTRACTION_HOST_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


class SurfaceReader:
    """Own target hashes and settle candidates; never expose either.

    ``poll`` obtains a FRESH process query. ``lock_current`` consumes only the
    hashes of that just-observed surface. Background browser reads are possible
    exclusively for explicit desktop-card recovery or our own card process.
    The native main window is a separate home surface, never a settle candidate.
    """

    def __init__(self, root=None, runner=None, own_pids=(), home_port=HOME_PORT):
        self.root = Path(root or Path(__file__).resolve().parents[1])
        self.runner = runner or subprocess.run
        self.home_port = int(home_port)
        self.own_pids = {os.getpid(), *(int(pid) for pid in own_pids)}
        self.home_pids = set()
        self._mutex = threading.RLock()
        self._target_app = None
        self._target_host = None
        self._candidate = None
        self._settle_ticks = 0
        self._current = None
        self._last_browser_bundle = None
        self._binary = self.root / ".runtime" / "focus-surface"
        self._native_status = "not_started"
        self._compile_failed = False

    def register_own_pid(self, pid):
        with self._mutex:
            self.own_pids.add(int(pid))

    def register_home_pid(self, pid):
        """Replace the native main window identity without treating it as a card."""
        if type(pid) is not int or not 0 < pid <= 2_147_483_647:
            raise ValueError("native PID must be a positive process id")
        with self._mutex:
            if self.home_pids == {pid}:
                return
            self.home_pids = {pid}
            self.own_pids.discard(pid)
            self._candidate = None
            self._settle_ticks = 0

    def _run(self, args, timeout):
        return self.runner(args, capture_output=True, text=True, timeout=timeout, check=False)

    def _ensure_native(self):
        if sys.platform != "darwin":
            self._native_status = "unsupported_platform"
            return False
        source = self.root / "scripts" / "focus_surface.swift"
        if self._binary.exists() and self._binary.stat().st_mtime >= source.stat().st_mtime:
            return True
        if self._compile_failed:
            return False
        try:
            self._binary.parent.mkdir(parents=True, exist_ok=True)
            result = self._run(["/usr/bin/swiftc", str(source), "-o", str(self._binary)],
                               COMPILE_TIMEOUT_SECONDS)
            if result.returncode:
                self._native_status = "compile_failed"
                self._compile_failed = True
                return False
            self._binary.chmod(0o700)
            return True
        except (OSError, subprocess.SubprocessError):
            self._native_status = "compile_failed"
            self._compile_failed = True
            return False

    def _frontmost(self):
        if not self._ensure_native():
            return None
        try:
            result = self._run([str(self._binary)], NATIVE_TIMEOUT_SECONDS)
            value = json.loads(result.stdout)
            if result.returncode or not value.get("readable"):
                self._native_status = "unreadable"
                return None
            self._native_status = "ok"
            return value
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            self._native_status = "unreadable"
            return None

    def _browser_url(self, bundle):
        # Bundle IDs are restricted to our explicit supported set; no URL or app
        # name is interpolated into shell source. No shell process is involved.
        if bundle not in CHROME_BUNDLES:
            return None, "unsupported_browser"
        script = ('tell application id "' + bundle + '"\n'
                  'if (count of windows) is 0 then return ""\n'
                  'return URL of active tab of front window\nend tell')
        try:
            result = self._run(["/usr/bin/osascript", "-e", script], BROWSER_TIMEOUT_SECONDS)
            if result.returncode:
                return None, "permission_or_script_error"
            url = result.stdout.strip()
            if not url:
                return None, "no_front_tab"
            return url, "ok"
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except (OSError, subprocess.SubprocessError):
            return None, "unreadable"

    def poll(self, *, track_settle=True, from_card=False):
        with self._mutex:
            raw = self._frontmost()
            native_home = bool(raw and raw.get("pid") in self.home_pids and not from_card)
            app_readable = bool(raw and (raw.get("bundle_id") or native_home))
            if raw and not app_readable:
                self._native_status = "missing_bundle_identifier"
            bundle = str((raw or {}).get("bundle_id") or "")
            if native_home and not bundle:
                bundle = "local.jarvis.native-home"
            name = str((raw or {}).get("name", ""))
            own = bool(raw and (raw.get("pid") in self.own_pids or bundle in OWN_BUNDLES))
            browser = bool(bundle in CHROME_BUNDLES and not native_home)
            card_recovery = bool(from_card or (own and not native_home))
            # A card can steal activation. Recover ONLY the last browser actually
            # observed in the foreground, never the first installed browser.
            if card_recovery and not browser:
                bundle = self._last_browser_bundle or ""
                browser = bool(bundle)
                app_readable = browser
                name = ""
            elif browser:
                self._last_browser_bundle = bundle
            app_hash = _hash(bundle) if app_readable else None
            host_hash = None
            home = native_home
            label = ""
            tab_status = "not_browser" if app_readable else "app_unreadable"
            if card_recovery and not browser:
                tab_status = "no_observed_browser"
            if browser:
                url, tab_status = self._browser_url(bundle)
                if url:
                    try:
                        parsed = urlsplit(url)
                        host = (parsed.hostname or "").lower().rstrip(".")
                        home = (parsed.scheme in {"http", "https"} and host in HOME_HOSTS
                                and parsed.port == self.home_port and parsed.path in HOME_PATHS)
                        if host:
                            host_hash = _hash(host)
                            label = "" if home else _spoken_host(host)
                        elif not home:
                            tab_status = "no_host"
                    except ValueError:
                        tab_status = "invalid_url"
            elif app_readable and not home:
                # Display names are ephemeral, bounded and control-character free.
                label = re.sub(r"[\x00-\x1f\x7f]", "", name)[:80]

            known = bool(app_readable and (not browser or host_hash is not None))
            candidate = (app_hash, host_hash if browser else None) if known and not home else None
            if track_settle:
                if candidate is not None and candidate == self._candidate:
                    self._settle_ticks += 1
                else:
                    self._candidate = candidate
                    self._settle_ticks = 1 if candidate is not None else 0
            self._current = {
                "app": app_hash, "host": host_hash, "home": home,
                "browser": browser, "known": known, "own": own or native_home,
            }
            app_matches = bool(self._target_app and app_hash == self._target_app)
            tab_matches = bool(self._target_host is None or (host_hash and host_hash == self._target_host))
            app_on_target = bool(home or (app_readable and app_matches))
            tab_on_target = bool(home or (known and tab_matches))
            return {
                "app_readable": app_readable,
                "is_browser": browser,
                "tab_read_status": tab_status,
                "is_home": home,
                "hash_present": host_hash is not None,
                "surface_known": known,
                "own_process": own or native_home,
                "settle_ticks": self._settle_ticks,
                "app_target": self._target_app is not None,
                "tab_target": self._target_host is not None,
                "app_on_target": app_on_target,
                "tab_on_target": tab_on_target,
                "native_status": self._native_status,
                "ephemeral_label": label,
            }

    def lock_current(self, *, app_only=False):
        with self._mutex:
            value = self._current or {}
            if not value.get("app") or (not app_only and not value.get("known")):
                return False
            self._target_app = value["app"]
            self._target_host = None if app_only else value.get("host")
            self._candidate = None
            self._settle_ticks = 0
            return True

    def clear_target(self):
        with self._mutex:
            self._target_app = None
            self._target_host = None
            self._candidate = None
            self._settle_ticks = 0

    def reset_settle(self):
        with self._mutex:
            self._candidate = None
            self._settle_ticks = 0
