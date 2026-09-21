"""Presentation hints only. They never grant tools or expand task permissions."""
import re
import platform
import subprocess

APP_ALIASES = {
    'Blender': ('blender', 'בלנדר'),
    'DaVinci Resolve': ('davinci', 'resolve', 'ריזולב', 'דה וינצי'),
    'Adobe Photoshop': ('photoshop', 'פוטושופ'),
    'Adobe After Effects': ('after effects', 'אפטר אפקטס'),
    'Adobe Premiere Pro': ('premiere', 'פרמייר'),
    'CapCut': ('capcut', 'קפקאט'),
    'Google Chrome': ('chrome', 'כרום'),
    'Safari': ('safari', 'ספארי'),
    'Firefox': ('firefox', 'פיירפוקס'),
    'Visual Studio Code': ('vscode', 'vs code', 'visual studio code'),
}
ACTION = re.compile(r'(?:תפתח|פתח|תעבוד|תבנה|תעשה|תיצור|צור|תערוך|ערוך|תלחץ|לחץ|תגלול|גלול|תעבור|תציג|תפעיל|תריץ|תזיז|תסדר|תכניס|תכתוב|תמחק|תשנה|תוסיף|תחליף|תשמור|תסגור|הקפץ|תקפיץ|(?:open|launch|activate|bring|click|scroll|drag|type|edit|build|create|move|switch|close)\b)',re.I)
SURFACE = re.compile(r'(?:מסך|מחשב|תוכנ|חלון|לשונית|דפדפן|האפליקציה|desktop|screen|browser|window|application|this app)',re.I)


def requested_app(text):
    folded = text.casefold()
    return next((name for name, aliases in APP_ALIASES.items() if any(alias in folded for alias in aliases)), None)


def desktop_request(text):
    return bool(isinstance(text,str) and ACTION.search(text) and (requested_app(text) or SURFACE.search(text)))


def present_requested_app(text):
    """Activate an explicitly named app; reuse existing instances and windows."""
    name = requested_app(text)
    if not name or not desktop_request(text): return {'activated':False}
    try:
        if platform.system() == 'Darwin':
            # open -a asks Launch Services to reuse and activate an existing app.
            # Do not use -n (new instance) or -g (background).
            result = subprocess.run(['open','-a',name],capture_output=True,timeout=5)
            activated = result.returncode == 0
        elif platform.system() == 'Windows':
            import pygetwindow
            candidates = pygetwindow.getWindowsWithTitle(name)
            if not candidates and name.startswith('Adobe '):
                candidates = pygetwindow.getWindowsWithTitle(name.removeprefix('Adobe '))
            if not candidates: return {'activated':False,'app':name}
            window = candidates[0]
            if window.isMinimized: window.restore()
            window.activate()
            activated = True
        else:
            result = subprocess.run(['wmctrl','-a',name],capture_output=True,timeout=3)
            activated = result.returncode == 0
        return {'activated':activated,'app':name}
    except Exception:
        return {'activated':False,'app':name}
