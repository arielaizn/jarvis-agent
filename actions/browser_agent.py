"""Browser-use action, discovered by the existing Jarvis tool registry."""
import json


def browser_agent(parameters=None, player=None, **kwargs) -> str:
    from core import browser_runtime
    params = parameters or {}
    action = params.get("action", "status")
    try:
        if action == "start":
            result = browser_runtime.start(params.get("task", ""), max_steps=params.get("max_steps"))
        elif action == "status":
            result = browser_runtime.status(params.get("job_id", ""))
        elif action == "cancel":
            result = browser_runtime.cancel(params.get("job_id", ""))
        elif action == "diagnostics":
            result = browser_runtime.diagnostics()
        else:
            raise ValueError("פעולת דפדפן לא מוכרת.")
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, RuntimeError, OSError) as error:
        return json.dumps({"success": False, "error": str(error)}, ensure_ascii=False)


TOOL = {
    "name": "browser_agent",
    "description": "סוכן browser-use לגלישה ולביצוע משימות באתרי אינטרנט. start מתחיל משימה ברקע ומחזיר job_id. יש לבדוק status עד is_done; הצלחה מחייבת is_successful=true. cancel עוצר משימה. diagnostics בודק התקנה. הדפדפן משתמש בפרופיל נפרד או בחיבור CDP שהמשתמש הגדיר.",
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "enum": ["start", "status", "cancel", "diagnostics"]},
        "task": {"type": "STRING", "description": "המשימה המדויקת שהמשתמש ביקש לבצע בדפדפן"},
        "job_id": {"type": "STRING", "description": "מזהה משימה לבדיקת מצב או לעצירה"},
        "max_steps": {"type": "INTEGER", "description": "מגבלת צעדים, בין 1 ל-200"},
    }, "required": ["action"]},
    "handler": browser_agent,
}
