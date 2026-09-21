"""Optional macOS desktop companion. The service itself remains standard library."""
import argparse
import json
import os
import sys
import threading
import time
from urllib.request import Request, urlopen

if sys.platform == 'darwin':
    # Qt otherwise turns this accessory into a foreground application during
    # QApplication startup, before WA_ShowWithoutActivating can help.
    os.environ['QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM'] = '1'

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout

CARD_WIDTH = 348
CARD_HEIGHT = 146
POLL_SECONDS = 1.0
REQUEST_TIMEOUT = 3
LOCK_FLASH_MS = 1000
FRAME_MS = 50
MENU_LEVEL_OFFSET = 1
LAYOUT_MARGIN_X = 12
LAYOUT_MARGIN_Y = 10
LAYOUT_SPACING = 6


class Bridge(QObject):
    state = Signal(dict)
    result = Signal(str, bool, dict)


class Face(QWidget):
    def __init__(self):
        super().__init__()
        from core.avatar import HoloAvatar
        self.avatar = HoloAvatar()
        self.setFixedSize(70, 86)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(FRAME_MS)

    def animate(self):
        if self.isVisible():
            self.avatar.step(FRAME_MS / 1000, 0, speaking=False, muted=True)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.avatar.paint(p, 35, 42, 35, QColor('#5ce7dc'), QColor('#9d8bff'), QColor('#081118'))
        p.end()


class Card(QWidget):
    def __init__(self, port):
        super().__init__(flags=Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.base = 'http://127.0.0.1:%d' % port
        self.setWindowTitle('Jarvis focus card')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.bridge = Bridge()
        self.bridge.state.connect(self.render)
        self.bridge.result.connect(self.result)
        self.paused = False
        self.native_pinned = False
        self._connected = False
        self.stop = threading.Event()
        root = QVBoxLayout(self)
        root.setContentsMargins(LAYOUT_MARGIN_X, LAYOUT_MARGIN_Y, LAYOUT_MARGIN_X, LAYOUT_MARGIN_Y)
        root.setSpacing(LAYOUT_SPACING)
        row = QHBoxLayout()
        self.face = Face()
        row.addWidget(self.face)
        text = QVBoxLayout()
        self.clock = QLabel('ג׳רוויס')
        self.clock.setStyleSheet('font-size:26px; font-weight:bold; color:#edfffc')
        self.status = QLabel('המיקוד מוכן')
        text.addWidget(self.clock)
        text.addWidget(self.status)
        row.addLayout(text)
        root.addLayout(row)
        controls = QHBoxLayout()
        self.lock = QPushButton('נעל על הלשונית')
        self.pause = QPushButton('השהה')
        self.abort = QPushButton('בטל')
        for button in (self.lock, self.pause, self.abort):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            controls.addWidget(button)
        self.lock.clicked.connect(lambda: self.command('retarget', {'from_card': True}))
        self.pause.clicked.connect(lambda: self.command('resume' if self.paused else 'pause'))
        self.abort.clicked.connect(lambda: self.command('abort'))
        root.addLayout(controls)
        self.thread = threading.Thread(target=self.poll, daemon=True)
        self.thread.start()

    def request(self, route, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base + route, data=data, headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            return json.load(response)

    def poll(self):
        while not self.stop.is_set():
            try:
                self.bridge.state.emit(self.request('/state'))
            except Exception:
                self.bridge.state.emit({'connection_error': True})
            self.stop.wait(POLL_SECONDS)

    def command(self, action, body=None):
        def send():
            try:
                state = self.request('/focus/' + action, body or {})
                self.bridge.result.emit(action, True, state)
            except Exception:
                self.bridge.result.emit(action, False, {})
        threading.Thread(target=send, daemon=True).start()

    def result(self, action, ok, state):
        if not ok:
            self.status.setText('הפעולה נכשלה. בדוק את חלון ג׳רוויס.')
        elif action == 'retarget':
            # A deferred acknowledgement is not a lock. The card's flash must
            # agree with the server, especially while returning from Jarvis.
            locked = bool(state.get('app_target') and not state.get('deferred'))
            self.lock.setText('ננעל' if locked else 'ממתין ללשונית')
            QTimer.singleShot(LOCK_FLASH_MS, lambda: self.lock.setText('נעל על הלשונית'))

    def pin(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.right() - CARD_WIDTH - 10, screen.top() + 4)
        if sys.platform == 'darwin':
            try:
                import objc
                import AppKit
                view = objc.objc_object(c_void_p=int(self.winId()))
                window = view.window()
                window.setLevel_(AppKit.NSMainMenuWindowLevel + MENU_LEVEL_OFFSET)
                window.setCollectionBehavior_(1 | 16 | 64 | 256)
                window.setHidesOnDeactivate_(False)
                self.native_pinned = True
            except Exception:
                self.status.setText('כרטיס פעיל; ההצמדה לכל שולחנות העבודה נכשלה')

    def render(self, state):
        if state.get('connection_error'):
            self._connected = False
            if self.isVisible():
                self.clock.setText('--:--')
                self.status.setText('החיבור לשרת נותק. ממתין לחיבור מחדש.')
                for button in (self.lock, self.pause, self.abort):
                    button.setEnabled(False)
            return
        self._connected = True
        focus = state.get('focus', {})
        watching = state.get('watch', {}).get('enabled', False)
        on = focus.get('on', False)
        if not on and not watching:
            self.hide()
            return
        self.paused = focus.get('paused', False)
        remaining = max(0, int(focus.get('seconds_remaining', 0)))
        self.clock.setText('%02d:%02d' % divmod(remaining, 60) if on else 'צופה במסך')
        status = ('ממתין ללשונית העבודה' if focus.get('deferred') else
                  'מושהה' if self.paused else 'יצאת מהמשימה' if focus.get('drifting') else
                  'במיקוד' if on else 'שיתוף מסך פעיל')
        self.status.setText(status)
        self.pause.setText('המשך' if self.paused else 'השהה')
        for button in (self.lock, self.pause, self.abort):
            button.setEnabled(on)
        border = '#ed846a' if focus.get('drifting') else '#4ddbd0'
        self.setStyleSheet('QWidget{background:#081118;color:#bcd8d8;border-radius:12px}'
                           'Card{border:1px solid %s} QPushButton{padding:6px;background:#162a34;}' % border)
        if not self.isVisible():
            self.show()
            self.pin()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4700)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == 'darwin':
        try:
            import AppKit
            AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        except ImportError:
            pass
    card = Card(args.port)
    app.aboutToQuit.connect(card.stop.set)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
