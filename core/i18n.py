"""Hebrew display text; protocol keys, paths, and model identifiers stay unchanged."""
from __future__ import annotations

from datetime import datetime

_STATUS = {
    "INITIALISING": "מאתחל", "LISTENING": "מקשיב", "THINKING": "חושב",
    "PROCESSING": "מעבד", "SPEAKING": "מדבר", "SLEEPING": "ממתין להפעלה",
    "MUTED": "מושתק", "CONNECTING": "מתחבר", "RECONNECTING": "מתחבר מחדש",
    "READY": "מוכן", "ONLINE": "מחובר", "OFFLINE": "מנותק", "ERROR": "שגיאה",
    "DISCONNECTED": "מנותק", "STOPPED": "נעצר", "IDLE": "ממתין",
}


def he_status(state: str) -> str:
    return _STATUS.get(state.upper(), state)


def display_name(name: str) -> str:
    return "ג׳רוויס" if name.upper().replace(".", "") == "JARVIS" else name


def hebrew_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    days = ("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")
    return f"יום {days[now.weekday()]} · {now:%d.%m.%Y}"


_SYSTEM_MESSAGES = {
    "Interrupted — listening...": "התשובה נעצרה. מקשיב…",
    "Shutdown requested.": "התקבלה בקשת כיבוי.",
    "Phone connected via Remote Dashboard.": "הטלפון מחובר ללוח הבקרה.",
    "Reconnected — conversation restored.": "החיבור חודש והשיחה שוחזרה.",
    "JARVIS online.": "ג׳רוויס מחובר.",
    "JARVIS online — sleeping. Say 'Hey Jarvis' to wake me.": "ג׳רוויס מחובר וממתין להפעלה. אפשר לומר Hey Jarvis.",
    "I'm asleep — say 'Hey Jarvis' or tap WAKE NOW first.": "ג׳רוויס ממתין. אפשר לומר Hey Jarvis או ללחוץ על הפעלה עכשיו.",
    "Could not restore the conversation — starting fresh.": "שחזור השיחה נכשל. נפתחה שיחה חדשה.",
    "Could not fetch the news for the briefing.": "טעינת החדשות לעדכון נכשלה.",
    "API key invalid — please re-enter your key.": "מפתח ה־API אינו תקין. יש להזין אותו מחדש.",
    "Remote session active.": "החיבור מרחוק פעיל.",
    "Wake word ready.": "מילת ההפעלה מוכנה.",
}


def localize_log(text: str) -> str:
    """Translate known system messages without altering user/assistant content."""
    prefix, sep, body = text.partition(": ")
    labels = {"SYS": "מערכת", "ERR": "שגיאה", "You": "אתה", "FILE": "קובץ", "[Web]": "מהדפדפן"}
    if not sep:
        return text
    if prefix in ("SYS", "ERR"):
        body = _SYSTEM_MESSAGES.get(body, body)
    return f"{labels.get(prefix, display_name(prefix))}: {body}"
