"""Fast, read-only setup checks; configured does not mean connected."""
import importlib.util
import ctypes
import json
import platform
from pathlib import Path
from core.integration_config import load_integrations, resolve_path
from core.skills import discover_skills


def mac_permissions() -> dict:
    services = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    graphics.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    return {"accessibility": bool(services.AXIsProcessTrusted()),
            "screen_recording": bool(graphics.CGPreflightScreenCaptureAccess())}


def collect_status() -> dict:
    config = load_integrations()
    checks = []
    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})
    browser = resolve_path(config["browser"].get("python_path", ".venv-browser/bin/python"))
    add("מנוע הדפדפן", "ready" if browser.is_file() else "needs_setup",
        "סביבת הדפדפן מותקנת. החיבור נבדק בעת הפעלת משימה." if browser.is_file() else "יש להפעיל את install.command")
    if platform.system() == "Darwin":
        try:
            permissions = mac_permissions()
            for name, value in [("נגישות", permissions["accessibility"]),
                                ("הקלטת מסך", permissions["screen_recording"])]:
                add(name, "ready" if value else "needs_setup",
                    "ההרשאה פעילה לתהליך הנוכחי" if value else "יש להפעיל בהגדרות המערכת > פרטיות ואבטחה עבור היישום שמפעיל את ג׳רוויס")
        except (OSError, AttributeError):
            add("הרשאות macOS", "needs_setup", "לא הצלחתי לבדוק את הרשאות macOS")
    items = discover_skills()
    add("סקילים", "ready" if items else "needs_setup", f"נמצאו {len(items)} חבילות SKILL.md")
    servers = []
    try:
        path = resolve_path(config["mcp"]["config_path"])
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = list(data.get("mcpServers", {}))
        add("MCP", "ready" if importlib.util.find_spec("mcp") else "needs_setup",
            f"מוגדרים {len(servers)} שרתים. החיבור נבדק בעת שימוש בכל שרת.")
    except (ValueError, OSError):
        add("MCP", "needs_setup", "קובץ הגדרות השרתים אינו תקין")
    names = ("DaVinci Resolve", "Adobe After Effects", "Adobe Photoshop", "Blender", "CapCut", "Cinema 4D", "Final Cut Pro", "Adobe Premiere", "PalmierPro")
    from core.editing_runtime import inventory
    installed = [app["name"] for app in inventory()
                 if any(n.casefold() in (app["name"] + " " + app["path"]).casefold() for n in names)]
    add("תוכנות עריכה", "ready" if installed else "needs_setup", f"נמצאו {len(installed)} תוכנות. התקנה אינה מעידה על חיבור פעיל.")
    sdk = Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py")
    add("ממשק Resolve", "ready" if sdk.exists() else "needs_setup",
        "ממשק הסקריפטים מותקן. יש לבדוק חיבור מתוך כלי תוכנות העריכה." if sdk.exists() else "ממשק הסקריפטים לא נמצא בנתיב ברירת המחדל")
    return {"checks": checks, "skills_count": len(items), "mcp_servers": servers, "editing_apps": sorted(set(installed))}


if __name__ == "__main__":
    print(json.dumps(collect_status(), ensure_ascii=False, indent=2))
