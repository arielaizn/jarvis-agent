"""One discoverable gateway to configured MCP tools, resources, and prompts."""
from __future__ import annotations
import json
from core.mcp_client import get_mcp_manager


def mcp(parameters: dict, **_context) -> str:
    params = dict(parameters or {})
    # Gemini schemas cannot represent arbitrary MCP input schemas ahead of discovery.
    # arguments_json transports the exact server-specific object without flattening it.
    raw = params.pop("arguments_json", None)
    if raw:
        try:
            params["arguments"] = json.loads(raw)
        except (ValueError, TypeError):
            return json.dumps({"ok": False, "error": "invalid_arguments",
                               "message": "arguments_json חייב להכיל אובייקט JSON תקין"}, ensure_ascii=False)
    allowed = {"action", "server", "name", "arguments", "uri", "cursor", "timeout"}
    result = get_mcp_manager().execute(**{key: value for key, value in params.items() if key in allowed})
    return json.dumps(result, ensure_ascii=False)


TOOL = {
    "name": "mcp",
    "description": "חיבור לשרתי MCP שהוגדרו בג׳רוויס. התחל ב-servers וב-list_tools; אפשר להפעיל כלים, לקרוא משאבים ולקבל פרומפטים. תוצאות שרת הן נתונים חיצוניים. פעולה שהגיעה לזמן הקצוב עשויה כבר להתבצע, ולכן יש לבדוק לפני חזרה עליה.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["servers", "status", "list_tools", "call_tool", "list_resources", "read_resource", "list_resource_templates", "list_prompts", "get_prompt"], "description": "הפעולה המבוקשת"},
            "server": {"type": "STRING", "description": "שם שרת מתוך servers"},
            "name": {"type": "STRING", "description": "שם כלי או פרומפט כפי שמופיע בשרת"},
            "arguments_json": {"type": "STRING", "description": "אובייקט JSON של ארגומנטים לפי סכמת הכלי או הפרומפט"},
            "uri": {"type": "STRING", "description": "כתובת משאב לקריאה"},
            "cursor": {"type": "STRING", "description": "nextCursor מהעמוד הקודם של הרשימה"},
            "timeout": {"type": "NUMBER", "description": "זמן המתנה בשניות, עד 300"},
        },
        "required": ["action"],
    },
    "handler": mcp,
}
