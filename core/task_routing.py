"""Choose a lane, never grant permissions or replace the user's request."""
import re
from core.desktop_activity import desktop_request, ACTION
from core import typesafe_client

FILES = re.compile(r'(?:קובץ|קבצים|תיקיי?ה|תיקיות|הורדות|שולחן העבודה|\b(?:files?|folders?|downloads?|directory|terminal|shell)\b)', re.I)
WRITE = re.compile(r'(?:תפתח|פתח|תיצור|צור|תעתיק|העתק|תעביר|העבר|תמחק|מחק|תשנה|תסדר|תארגן|תריץ|הרץ|תבדוק|בדוק|\b(?:open|create|copy|move|delete|rename|organize|run|check|list)\b)',re.I)
QUESTIONS = {'lane': {'type':'choice', 'instructions':
    'Choose the execution lane for the direct user request. Computer means actually inspecting or operating local files, installed apps, websites, desktop or network tools. Workspace means notes, email, calendar, Drive or a general knowledge answer. A question asking whether access exists is capability. Unclear has no match. Do not execute or grant permission.',
    'criteria': {'computer':'Actual computer/browser/file operation outside the note vault.',
                 'workspace':'Notes, mail/calendar/Drive, conversation or general information.',
                 'capability':'Asks what access/permissions Jarvis currently has.',
                 'unclear':'No clear lane.'}}}

def choose_lane(question, judge=None):
    if desktop_request(question):return 'computer'
    if FILES.search(question) and WRITE.search(question):return 'computer'
    # Exact capability queries do not need a remote model.
    if re.search(r'(?:יש לך|אין לך|האם אתה יכול|do you have|can you access).{0,50}(?:גישה|הרשא|access|permission)',question,re.I):return 'capability'
    try:
        answer=(judge or typesafe_client.evaluate)({'request':question[:3000]},QUESTIONS,timeout=1.25)['answers']['lane']
        if answer['probabilities'].get(answer['choice'],0)>=.85:return answer['choice']
    except Exception:pass
    return 'workspace'
