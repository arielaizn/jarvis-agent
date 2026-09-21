"""Native editor inventory and a bounded, subprocess-isolated Resolve bridge."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys

from core.app_paths import runtime_root
ROOT = runtime_root()
RESOLVE_ACTIONS = {
    "status", "projects", "timelines", "create_project", "load_project", "save",
    "create_timeline", "select_timeline", "import_media", "append_media", "open_page",
    "render_queue", "queue_render", "start_render", "stop_render", "render_status",
}


def _application_roots() -> list[Path]:
    return [Path("/Applications"), Path.home() / "Applications"]


def inventory() -> list[dict]:
    apps = []
    seen = set()
    for root in _application_roots():
        if not root.is_dir():
            continue
        for depth in ("*.app", "*/*.app", "*/*/*.app"):
            for app in sorted(root.glob(depth)):
                if any(part.endswith(".app") for part in app.relative_to(root).parts[:-1]):
                    continue
                if app in seen:
                    continue
                seen.add(app)
                try:
                    with (app / "Contents" / "Info.plist").open("rb") as handle:
                        info = plistlib.load(handle)
                except (OSError, ValueError, plistlib.InvalidFileException):
                    info = {}
                name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem
                apps.append({"name": name, "path": str(app), "bundle_id": info.get("CFBundleIdentifier", ""),
                             "version": info.get("CFBundleShortVersionString", ""),
                             "resolve_api": "davinci resolve" in app.stem.lower(),
                             "native_control": platform.system() == "Darwin"})
    return sorted(apps, key=lambda item: item["name"].lower())


def find_app(name: str) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("יש להזין שם תוכנה.")
    aliases = {"ריזולב": "davinci resolve", "דה וינצי": "davinci resolve", "resolve": "davinci resolve",
               "אפטר": "after effects", "אפטר אפקטס": "after effects", "בלנדר": "blender",
               "פוטושופ": "photoshop", "קפקאט": "capcut", "סינמה": "cinema 4d",
               "פרמייר": "premiere", "פיינל קאט": "final cut"}
    query = aliases.get(name.strip().lower(), name.strip().lower())
    all_apps = inventory()
    exact = [app for app in all_apps if query in {app["path"].lower(), app["name"].lower(), Path(app["path"]).stem.lower(), app["bundle_id"].lower()}]
    candidates = exact or [app for app in all_apps if query in app["name"].lower() or query in app["path"].lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError("נמצאו כמה תוכנות. יש לבחור נתיב מדויק: " + ", ".join(a["path"] for a in candidates))
    raise ValueError(f"התוכנה לא נמצאה: {name}")


def _apple_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n") + '"'


def _osascript(script: str) -> str:
    if platform.system() != "Darwin":
        raise RuntimeError("בקרת התפריטים זמינה במק בלבד.")
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "הפקודה לא בוצעה. יש לבדוק הרשאות נגישות ואוטומציה בהגדרות המערכת.")
    return result.stdout.strip()


def launch_app(name: str) -> dict:
    app = find_app(name)
    result = subprocess.run(["open", "-a", app["path"]], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "התוכנה לא נפתחה.")
    return {"success": True, "message": "נשלחה פקודת פתיחה לתוכנה.", "app": app["name"]}


def focus_app(name: str) -> dict:
    app = find_app(name)
    identifier = app["bundle_id"]
    if not identifier:
        raise ValueError("לתוכנה חסר מזהה מערכת.")
    _osascript(f'tell application id {_apple_string(identifier)} to activate')
    return {"success": True, "app": app["name"], "message": "התוכנה הובאה לקדמת המסך."}


def menu_action(name: str, menu_path: list[str]) -> dict:
    if not isinstance(menu_path, list) or not 2 <= len(menu_path) <= 6 or not all(isinstance(p, str) and 0 < len(p) <= 200 for p in menu_path):
        raise ValueError("יש לספק נתיב תפריט של 2 עד 6 שמות, לדוגמה File, Save.")
    app = find_app(name)
    focus_app(name)
    # Each item is data escaped into an AppleScript string; arbitrary scripts are never accepted.
    target = f"menu bar item {_apple_string(menu_path[0])} of menu bar 1"
    for item in menu_path[1:]:
        target = f"menu item {_apple_string(item)} of menu 1 of {target}"
    script = (f'tell application "System Events"\n'
              f'  tell (first application process whose bundle identifier is {_apple_string(app["bundle_id"])})\n'
              f'    click {target}\n'
              f'  end tell\nend tell')
    _osascript(script)
    return {"success": True, "app": app["name"], "menu_path": menu_path, "message": "פריט התפריט הופעל."}


def resolve_sdk_paths() -> tuple[Path, Path]:
    system = platform.system()
    if system == "Darwin":
        api = Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting")
        lib = Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so")
    elif system == "Windows":
        api = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting"
        lib = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Blackmagic Design/DaVinci Resolve/fusionscript.dll"
    else:
        api, lib = Path("/opt/resolve/Developer/Scripting"), Path("/opt/resolve/libs/Fusion/fusionscript.so")
    return (Path(os.environ.get("RESOLVE_SCRIPT_API", str(api))).expanduser(),
            Path(os.environ.get("RESOLVE_SCRIPT_LIB", str(lib))).expanduser())


def resolve_command(action: str = "status", **params) -> dict:
    if action not in RESOLVE_ACTIONS:
        raise ValueError("פעולת ריזולב לא מוכרת.")
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--resolve-bridge"],
            input=json.dumps({"action": action, **params}, ensure_ascii=False),
            text=True, capture_output=True, timeout=30, cwd=str(ROOT),
        )
        for line in reversed(result.stdout.splitlines()):
            if line.startswith("JARVIS_RESOLVE_RESULT="):
                return json.loads(line.split("=", 1)[1])
        return {"success": False, "connected": False, "message": "חיבור ריזולב הסתיים ללא תשובה.", "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "connected": False, "message": "ריזולב לא השיב בזמן. בדוק שהתוכנה פתוחה ושגישה חיצונית לסקריפטים מוגדרת Local."}


def _resolve_connection():
    api, lib = resolve_sdk_paths()
    module = api / "Modules" / "DaVinciResolveScript.py"
    if not module.is_file() or not lib.is_file():
        raise RuntimeError("ערכת הסקריפטים של ריזולב לא נמצאה. יש לבדוק את ההתקנה.")
    os.environ["RESOLVE_SCRIPT_LIB"] = str(lib)
    spec = importlib.util.spec_from_file_location("DaVinciResolveScript", module)
    script = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = script
    spec.loader.exec_module(script)
    # Blackmagic's loader replaces its module in sys.modules with fusionscript.
    script = sys.modules[spec.name]
    resolve = script.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("ריזולב אינו מחובר. פתח את התוכנה והגדר Preferences > System > General > External scripting using: Local. זמינות API חיצוני תלויה במהדורת ריזולב.")
    return resolve


def _name(params: dict, key: str = "name") -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError("יש להזין שם באורך 1 עד 300 תווים.")
    return value.strip()


def _paths(params: dict) -> list[str]:
    values = params.get("paths")
    if not isinstance(values, list) or not 1 <= len(values) <= 200 or not all(isinstance(v, str) for v in values):
        raise ValueError("יש לספק רשימה של 1 עד 200 קבצי מדיה.")
    paths = [Path(v).expanduser().resolve() for v in values]
    if any(not p.is_file() for p in paths):
        raise ValueError("אחד מקבצי המדיה אינו קיים או שהוא תיקייה.")
    return [str(p) for p in paths]


def _require_success(value, message: str):
    if not value:
        raise RuntimeError(message)
    return value


def _dispatch_resolve(resolve, params: dict) -> dict:
    action = params.get("action", "status")
    if action not in RESOLVE_ACTIONS:
        raise ValueError("פעולת ריזולב לא מוכרת.")
    manager = _require_success(resolve.GetProjectManager(), "מנהל הפרויקטים אינו זמין.")
    project = manager.GetCurrentProject()
    if action == "status":
        current = project.GetCurrentTimeline() if project else None
        return {"success": True, "connected": True, "product": resolve.GetProductName(),
                "version": resolve.GetVersionString(), "page": resolve.GetCurrentPage(),
                "project": project.GetName() if project else None,
                "timeline": current.GetName() if current else None,
                "is_rendering": bool(project.IsRenderingInProgress()) if project else False}
    if action == "projects":
        return {"success": True, "projects": manager.GetProjectListInCurrentFolder() or [],
                "folders": manager.GetFolderListInCurrentFolder() or []}
    if action == "create_project":
        name = _name(params)
        if name in (manager.GetProjectListInCurrentFolder() or []):
            raise ValueError("כבר קיים פרויקט בשם הזה.")
        if project:
            _require_success(manager.SaveProject(), "הפרויקט הנוכחי לא נשמר ולכן הפרויקט החדש לא נוצר.")
        created = _require_success(manager.CreateProject(name), "יצירת הפרויקט נכשלה.")
        return {"success": True, "project": created.GetName()}
    if action == "load_project":
        name = _name(params)
        if name not in (manager.GetProjectListInCurrentFolder() or []):
            raise ValueError("הפרויקט לא נמצא בתיקייה הנוכחית.")
        if project and project.GetName() != name:
            _require_success(manager.SaveProject(), "הפרויקט הנוכחי לא נשמר ולכן לא הוחלף.")
        loaded = _require_success(manager.LoadProject(name), "פתיחת הפרויקט נכשלה.")
        return {"success": True, "project": loaded.GetName()}
    if action == "open_page":
        page = params.get("page")
        if page not in {"media", "photo", "cut", "edit", "fusion", "color", "fairlight", "deliver"}:
            raise ValueError("עמוד ריזולב לא מוכר.")
        _require_success(resolve.OpenPage(page), "מעבר העמוד נכשל.")
        return {"success": True, "page": resolve.GetCurrentPage()}
    _require_success(project, "אין פרויקט פתוח בריזולב.")
    if action == "save":
        _require_success(manager.SaveProject(), "שמירת הפרויקט נכשלה.")
        return {"success": True, "project": project.GetName(), "saved": True}
    if action == "timelines":
        timelines = []
        for index in range(1, project.GetTimelineCount() + 1):
            timeline = project.GetTimelineByIndex(index)
            timelines.append({"index": index, "name": timeline.GetName(),
                              "start_frame": timeline.GetStartFrame(), "end_frame": timeline.GetEndFrame()})
        return {"success": True, "timelines": timelines}
    if action == "select_timeline":
        index = params.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= project.GetTimelineCount():
            raise ValueError("מספר הטיימליין אינו תקין.")
        timeline = project.GetTimelineByIndex(index)
        _require_success(project.SetCurrentTimeline(timeline), "בחירת הטיימליין נכשלה.")
        return {"success": True, "timeline": timeline.GetName()}
    if action == "create_timeline":
        name = _name(params)
        timeline = _require_success(project.GetMediaPool().CreateEmptyTimeline(name), "יצירת הטיימליין נכשלה.")
        return {"success": True, "timeline": timeline.GetName()}
    if action in {"import_media", "append_media"}:
        paths = _paths(params)
        if action == "append_media":
            _require_success(project.GetCurrentTimeline(), "אין טיימליין פעיל להוספת מדיה.")
        clips = project.GetMediaPool().ImportMedia(paths) or []
        _require_success(clips, "ריזולב לא ייבא קבצי מדיה.")
        result = {"success": len(clips) == len(paths), "requested_files": len(paths), "imported_clips": len(clips),
                  "clips": [clip.GetName() for clip in clips]}
        if action == "append_media":
            appended = project.GetMediaPool().AppendToTimeline(clips) or []
            _require_success(appended, "הקבצים יובאו למאגר המדיה אך לא נוספו לטיימליין.")
            result["appended_clips"] = len(appended)
            result["success"] = result["success"] and len(appended) == len(clips)
        return result
    if action == "render_queue":
        return {"success": True, "jobs": project.GetRenderJobList() or [],
                "presets": project.GetRenderPresetList() or [], "is_rendering": bool(project.IsRenderingInProgress())}
    if action == "queue_render":
        _require_success(project.GetCurrentTimeline(), "אין טיימליין פעיל לייצוא.")
        target = Path(_name(params, "output_dir")).expanduser().resolve()
        if not target.is_dir():
            raise ValueError("תיקיית הייצוא חייבת להיות קיימת.")
        name = _name(params)
        if any(c in name for c in ("/", "\\", "\0")) or name in {".", ".."}:
            raise ValueError("שם קובץ הייצוא אינו תקין.")
        if any(p.is_file() and (p.name == name or p.stem == name) for p in target.iterdir()):
            raise ValueError("קובץ בשם הזה כבר קיים בתיקייה. יש לבחור שם אחר.")
        if params.get("preset"):
            _require_success(project.LoadRenderPreset(_name(params, "preset")), "פריסט הייצוא לא נטען.")
        _require_success(project.SetRenderSettings({"TargetDir": str(target), "CustomName": name}), "הגדרות הייצוא לא נשמרו.")
        job_id = _require_success(project.AddRenderJob(), "המשימה לא נוספה לתור הייצוא.")
        return {"success": True, "job_id": job_id, "queued": True, "rendered": False}
    if action in {"start_render", "render_status"}:
        job_id = _name(params, "job_id")
        known = {str(item.get("JobId")) for item in (project.GetRenderJobList() or [])}
        if job_id not in known:
            raise ValueError("מזהה הייצוא לא נמצא בתור.")
        if action == "start_render":
            _require_success(project.StartRendering([job_id]), "הייצוא לא התחיל.")
        return {"success": True, "job_id": job_id, "render_status": project.GetRenderJobStatus(job_id),
                "is_rendering": bool(project.IsRenderingInProgress()), "delivery_verified": False}
    if action == "stop_render":
        project.StopRendering()
        stopped = not bool(project.IsRenderingInProgress())
        return {"success": stopped, "is_rendering": not stopped}
    raise ValueError("פעולת ריזולב לא מוכרת.")


def diagnostics() -> dict:
    api, lib = resolve_sdk_paths()
    return {"sdk_found": (api / "Modules" / "DaVinciResolveScript.py").is_file(),
            "library_found": lib.is_file(), "resolve": resolve_command("status")}


if __name__ == "__main__" and "--resolve-bridge" in sys.argv:
    try:
        result = _dispatch_resolve(_resolve_connection(), json.load(sys.stdin))
    except Exception as error:
        result = {"success": False, "connected": False, "message": str(error)}
    print("JARVIS_RESOLVE_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
