"""Permission facts for the current process. Never infer an OS grant from consent.

Only the native dialog can persist computer access. There is deliberately no
HTTP endpoint accepting grants, system URLs, executable names or shell commands.
"""
from pathlib import Path
import ctypes
import json
import os
import platform
import shutil
import subprocess
from core.app_paths import runtime_root
from core.credentials import read_config, update_config
from core.integration_config import load_integrations, save_integrations

ONBOARDING_VERSION = 1
MAC_PANES = {
    'accessibility': 'Privacy_Accessibility', 'screen': 'Privacy_ScreenCapture',
    'files': 'Privacy_AllFiles', 'automation': 'Privacy_Automation',
    'microphone': 'Privacy_Microphone', 'camera': 'Privacy_Camera',
}
WINDOWS_PANES = {'files': 'privacy-broadfilesystemaccess', 'microphone': 'privacy-microphone',
                 'camera': 'privacy-webcam', 'screen': 'privacy-screenshotborders'}


def onboarding_path():
    return runtime_root() / 'config' / 'onboarding.json'


def needs_onboarding():
    return read_config(onboarding_path()).get('version') != ONBOARDING_VERSION


def complete_onboarding():
    update_config({'version': ONBOARDING_VERSION}, onboarding_path())


def set_computer_access(enabled):
    if type(enabled) is not bool:
        raise ValueError('Explicit boolean required')
    save_integrations({'codex': {'access_mode': 'full' if enabled else 'workspace'}})


def _mac_bool(library, symbol):
    try:
        function = getattr(ctypes.CDLL(library), symbol)
        function.restype = ctypes.c_bool
        function.argtypes = []
        return 'granted' if function() else 'required'
    except (OSError, AttributeError):
        return 'unknown'


def capabilities():
    """No private paths, app identities, credentials or claims of global access."""
    system = platform.system()
    full = load_integrations().get('codex', {}).get('access_mode') == 'full'
    result = {'platform': system, 'access_mode': 'full' if full else 'workspace',
              'codex_installed': bool(shutil.which('codex')),
              'accessibility': 'not_applicable', 'screen': 'on_request',
              'files': 'os_managed', 'automation': 'on_request',
              'microphone': 'on_request', 'camera': 'on_request',
              'onboarding_required': needs_onboarding(),
              'network': 'not_checked'}
    if system == 'Darwin':
        result['accessibility'] = _mac_bool('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices', 'AXIsProcessTrusted')
        result['screen'] = _mac_bool('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics', 'CGPreflightScreenCaptureAccess')
        # No public Full Disk Access check. Do not read protected user data to probe it.
        result['files'] = 'manual_check'
        result['automation'] = 'per_application'
    elif system == 'Linux':
        result['screen'] = 'portal_required' if os.environ.get('WAYLAND_DISPLAY') else 'session_managed'
        result['accessibility'] = 'session_managed'
    return result


def open_system_permission(kind):
    """Fixed settings destinations only; called from a physical native button."""
    system = platform.system()
    if system == 'Darwin' and kind in MAC_PANES:
        subprocess.Popen(['open', 'x-apple.systempreferences:com.apple.preference.security?' + MAC_PANES[kind]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if system == 'Windows' and kind in WINDOWS_PANES:
        os.startfile('ms-settings:' + WINDOWS_PANES[kind])
        return True
    return False


def show_permissions(parent, first_run=False):
    from PySide6.QtCore import Qt, QTimer, QUrl, QCoreApplication, QMicrophonePermission, QCameraPermission
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QScrollArea, QWidget
    dialog = QDialog(parent)
    dialog.setWindowTitle('JARVIS · גישה למחשב')
    dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dialog.resize(760, 680)
    dialog.setStyleSheet('''QDialog,QWidget {background:#101820;color:#eaf2f6;font-size:15px;}
        QLabel {background:transparent;} QPushButton {background:#20303d;border:1px solid #354653;border-radius:8px;padding:12px 18px;min-height:20px;}
        QPushButton:hover {background:#2b4353;} QPushButton:focus {border:2px solid #76dfd2;}
        QCheckBox {spacing:12px;padding:12px;} QScrollArea {border:0;}''')
    layout = QVBoxLayout(dialog); layout.setContentsMargins(28,24,28,24);layout.setSpacing(16)
    title = QLabel('מכינים את ג׳רוויס לעבודה' if first_run else 'גישה למחשב');title.setStyleSheet('font-size:28px;font-weight:600;');layout.addWidget(title)
    intro = QLabel('בחר במה ג׳רוויס יוכל להשתמש. מערכת ההפעלה עשויה לבקש אישור נפרד לכל הרשאה. אפשר לחזור למסך הזה מההגדרות.');intro.setWordWrap(True);layout.addWidget(intro)
    full = QCheckBox('גישה לקבצים, לרשת ולהפעלת כלים במשימות מחשב')
    full.setChecked(capabilities()['access_mode'] == 'full');layout.addWidget(full)
    detail = QLabel('גישה רחבה מאפשרת לסוכן להריץ פקודות ולשנות קבצים בהרשאות המשתמש שלך. הרשאות מערכת וחיבורי חשבונות נשארים באחריות מערכת ההפעלה.');detail.setWordWrap(True);detail.setStyleSheet('color:#a8bac5;font-size:13px;');layout.addWidget(detail)
    scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();rows=QVBoxLayout(content);rows.setSpacing(14);scroll.setWidget(content);layout.addWidget(scroll)
    labels={}
    entries=[('accessibility','שליטה בעכבר ובמקלדת','ב־macOS יש להוסיף את JARVIS לרשימת הנגישות.'),
             ('files','קבצים ותיקיות','ב־macOS: גישה מלאה לכונן. בחר את האפליקציה המותקנת, ואז פתח אותה מחדש.'),
             ('automation','דפדפן ותוכנות אחרות','macOS מבקש הרשאה עבור כל תוכנה בעת הפעלת כלי השליטה הראשון.'),
             ('screen','צפייה במסך','שיתוף מסך דורש בחירת מסך מפורשת. ההרשאה אינה מתחילה שיתוף.'),
             ('microphone','מיקרופון','האישור אינו מפעיל האזנה. כפתור האוזן מפעיל אותה.'),
             ('camera','מצלמה','האישור אינו מפעיל מצלמה. הפעלה מתבצעת במסך המצלמה.')]
    message=QLabel('');message.setWordWrap(True)
    def request(kind):
        if kind in {'microphone','camera'}:
            permission = QMicrophonePermission() if kind=='microphone' else QCameraPermission()
            app=QCoreApplication.instance()
            app.requestPermission(permission, dialog, lambda p: refresh())
        elif not open_system_permission(kind):
            message.setText('במערכת הזו הגישה ניתנת דרך חשבון המשתמש ובוחר השיתוף בעת השימוש. אין הרשאת־על אחת לכל התוכנות.')
        else:
            message.setText('הגדרות המערכת נפתחו. הפעל את JARVIS ברשימה וחזור לכאן לבדיקה. ייתכן שתידרש פתיחה מחדש.')
    names={'granted':'אושר בתהליך הזה','required':'נדרש אישור','manual_check':'בדיקה בהגדרות המערכת','unknown':'לא ניתן לאמת','on_request':'אישור בעת השימוש','per_application':'אישור לכל תוכנה','os_managed':'לפי הרשאות המשתמש','not_applicable':'לא נדרש במערכת הזו','portal_required':'בחירה דרך חלון השיתוף','session_managed':'לפי סביבת שולחן העבודה'}
    for kind,label,description in entries:
        row=QHBoxLayout();text=QVBoxLayout();heading=QLabel(label);heading.setStyleSheet('font-weight:600;');text.addWidget(heading)
        status=QLabel();status.setStyleSheet('color:#a8bac5;font-size:13px;');status.setWordWrap(True);labels[kind]=status;text.addWidget(status)
        button=QPushButton('פתיחת הרשאה');button.clicked.connect(lambda checked=False,k=kind:request(k));button.setAccessibleName('פתיחת הרשאה: '+label)
        button.setToolTip(description);row.addLayout(text,1);row.addWidget(button);rows.addLayout(row)
    rows.addStretch();layout.addWidget(message)
    cli=QLabel();cli.setWordWrap(True);layout.addWidget(cli)
    footer=QHBoxLayout();help_button=QPushButton('התקנת Codex / התחברות');help_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://developers.openai.com/codex/cli')));footer.addWidget(help_button)
    save=QPushButton('שמירה והמשך');save.setStyleSheet('background:#76dfd2;color:#09201e;font-weight:600;');footer.addWidget(save);layout.addLayout(footer)
    def refresh():
        facts=capabilities()
        for kind,label in labels.items():
            value=facts[kind]
            if kind in {'microphone','camera'}:
                p=QMicrophonePermission() if kind=='microphone' else QCameraPermission()
                grant=QCoreApplication.instance().checkPermission(p)
                value='granted' if grant==Qt.PermissionStatus.Granted else 'required' if grant==Qt.PermissionStatus.Denied else 'on_request'
            label.setText(names.get(value,value))
        cli.setText('Codex מותקן. התחברות לחשבון נבדקת בעת ביצוע משימה.' if facts['codex_installed'] else 'Codex CLI אינו מותקן או לא נמצא. יש להתקין ולהתחבר לחשבון, או לבחור Gemini בהגדרות.')
    def finish():
        set_computer_access(full.isChecked());complete_onboarding();dialog.accept()
    save.clicked.connect(finish)
    timer=QTimer(dialog);timer.timeout.connect(refresh);timer.start(2000);refresh()
    # Non-blocking native modal, retains its owner; no nested event-loop on startup.
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.show()
    return dialog
