"""Editor automation available to the Gemini action registry."""
import json


def editing_apps(parameters=None, player=None, **kwargs) -> str:
    from core import editing_runtime as editors
    params = dict(parameters or {})
    action = params.pop("action", "inventory")
    try:
        if action == "inventory":
            result = {"success": True, "apps": editors.inventory()}
        elif action == "diagnostics":
            result = editors.diagnostics()
        elif action == "launch":
            result = editors.launch_app(params.get("app_name", ""))
        elif action == "focus":
            result = editors.focus_app(params.get("app_name", ""))
        elif action == "menu":
            path = params.get("menu_path", [])
            if isinstance(path, list) and any(any(word in str(item).lower() for word in ("delete", "erase", "purge", "מחיקה", "מחק")) for item in path):
                from core import confirm
                return confirm.request("editor-menu", "מחיקה בתוכנת העריכה", " / ".join(path),
                                       lambda: json.dumps(editors.menu_action(params.get("app_name", ""), path), ensure_ascii=False))
            result = editors.menu_action(params.get("app_name", ""), path)
        elif action in {"shortcut", "type"}:
            from actions.computer_control import computer_control
            editors.focus_app(params.get("app_name", ""))
            command = {"action": "hotkey", "keys": params.get("keys", "")} if action == "shortcut" else {"action": "type", "text": params.get("text", "")}
            return computer_control(command, player=player)
        elif action.startswith("resolve_"):
            result = editors.resolve_command(action.removeprefix("resolve_"), **params)
        else:
            raise ValueError("פעולת עריכה לא מוכרת.")
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, RuntimeError, OSError, TimeoutError) as error:
        return json.dumps({"success": False, "error": str(error)}, ensure_ascii=False)


TOOL = {
    "name": "editing_apps",
    "description": "גישה לתוכנות עריכה מותקנות: inventory, launch, focus, menu, shortcut, type. בריזולב יש חיבור API לפעולות resolve_ עם סטטוס מאומת. queue_render מוסיף לתור; start_render מתחיל רק מזהה שנבחר; render_status בודק התקדמות. אין להסיק מסירה או קובץ תקין מהוספה לתור.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["inventory", "diagnostics", "launch", "focus", "menu", "shortcut", "type", "resolve_status", "resolve_projects", "resolve_timelines", "resolve_create_project", "resolve_load_project", "resolve_save", "resolve_create_timeline", "resolve_select_timeline", "resolve_import_media", "resolve_append_media", "resolve_open_page", "resolve_render_queue", "resolve_queue_render", "resolve_start_render", "resolve_stop_render", "resolve_render_status"]},
        "app_name": {"type": "STRING", "description": "שם התוכנה כפי שמופיע ברשימת התוכנות"},
        "menu_path": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "שמות התפריטים, למשל File ואז Save"},
        "keys": {"type": "STRING", "description": "קיצור מקשים, לדוגמה command+s"},
        "text": {"type": "STRING", "description": "טקסט להקלדה, תומך בעברית"},
        "name": {"type": "STRING", "description": "שם פרויקט, טיימליין או קובץ ייצוא"},
        "paths": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "נתיבי קבצי מדיה מקומיים"},
        "index": {"type": "INTEGER", "description": "מספר טיימליין החל מ-1"},
        "page": {"type": "STRING", "description": "עמוד ריזולב: media, cut, edit, fusion, color, fairlight, deliver"},
        "output_dir": {"type": "STRING", "description": "תיקיית ייצוא קיימת"},
        "preset": {"type": "STRING", "description": "פריסט ייצוא קיים, אופציונלי"},
        "job_id": {"type": "STRING", "description": "מזהה משימת ייצוא"},
    }, "required": ["action"]},
    "handler": editing_apps,
}
