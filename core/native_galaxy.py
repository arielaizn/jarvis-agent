"""The knowledge galaxy embedded in Jarvis's existing Python window."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QFile, QIODevice, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings, QWebEnginePermission
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QDialog, QListView, QDialogButtonBox, QMessageBox
from PySide6.QtMultimedia import QSoundEffect, QMediaDevices

from core.app_paths import runtime_root
ROOT = runtime_root()
LOCAL_HOST = '127.0.0.1'
LOCAL_PORT = int(os.environ.get('JARVIS_PORT', '4700'))
MAX_SPEECH_CHARACTERS = 2400
NATIVE_ATTACH_INTERVAL_MS = 10000


def local_origin(url):
    return url.scheme() == 'http' and url.host() == LOCAL_HOST and url.port() == LOCAL_PORT


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, main_frame):
        allowed = ('', '/', '/index.html', '/command/index.html') if main_frame else ('/index.html', '/holo/holo.html')
        return bool(local_origin(url) and url.path() in allowed)

    def createWindow(self, window_type):
        return None

    def chooseFiles(self, mode, old_files, accepted):
        return []

    def javaScriptConsoleMessage(self, level, message, line, source):
        # JS errors may contain note text or spoken distraction labels.
        if level == self.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print('[Galaxy] A viewer script reported an error (content omitted).', flush=True)


class NativeBridge(QObject):
    earsChanged = Signal(bool)
    utterance = Signal(str)
    speakingChanged = Signal(bool)
    _speechFinished = Signal(int)
    speechError = Signal(str)

    def __init__(self, owner, muted_test=False):
        super().__init__(owner)
        self.owner = owner
        self.muted_test = muted_test
        self.process = None
        self.lock = threading.RLock()
        self.generation = 0
        self.speakingChanged.connect(self._speaking)
        self._speechFinished.connect(self._finished)
        self.ack = QSoundEffect(self)
        from memory.config_manager import get_output_device
        selected_output = get_output_device()
        for device in QMediaDevices.audioOutputs():
            if selected_output and device.description() == selected_output:
                self.ack.setAudioDevice(device)
                break
        from core.acknowledgment import path
        self.ack.setSource(QUrl.fromLocalFile(str(path())))
        self.ack.playingChanged.connect(self._ack_changed)

    def _ack_changed(self):
        if not self.ack.isPlaying() and (self.process is None or self.process.poll() is not None):
            self._speaking(False)

    @Slot()
    def acknowledge(self):
        if self.muted_test:
            return
        from core.acknowledgment import TEXT
        if self.ack.status() == QSoundEffect.Status.Ready:
            self.stop()
            self._speaking(True)
            self.ack.play()
        else:
            self.say(TEXT, 'ack')

    def _speaking(self, speaking):
        self.owner.window._galaxy_speaking = speaking

    def _finished(self, generation):
        with self.lock:
            if generation == self.generation:
                self._speaking(False)

    @Slot()
    def showPermissions(self):
        from core.permissions import show_permissions
        self.owner.window._permission_dialog = show_permissions(self.owner.window)

    @Slot(result=bool)
    def earState(self):
        return not self.owner.window._muted

    @Slot(bool)
    def setEarsEnabled(self, enabled):
        # Web content has no authority to enable the microphone. The physical
        # Qt header button owns it; the bridge exposes its current state only.
        self.earsChanged.emit(not self.owner.window._muted)

    @Slot(str, str)
    def say(self, text, kind='answer'):
        if self.muted_test or not text or len(text) > MAX_SPEECH_CHARACTERS:
            return
        from core.native_voice import live_speech_request
        from core.acknowledgment import address
        from core.acknowledgment import path
        source = QUrl.fromLocalFile(str(path()))
        if self.ack.source() != source:
            self.ack.setSource(source)
        command, speech = live_speech_request(address(text)[:MAX_SPEECH_CHARACTERS])
        self._start_speech(command, speech)

    @Slot(str)
    def playAudio(self, audio):
        if self.muted_test or not audio.isascii() or not audio.startswith('data:audio/wav;base64,') or len(audio) > 16_000_000:
            return
        self._start_speech([sys.executable, '-m', 'core.live_speech', '--audio'], audio.encode('ascii'))

    def _start_speech(self, command, speech):
        # Private stdin only. No transcript, audio file or replay queue on disk.
        with self.lock:
            self.ack.stop()
            self.generation += 1
            generation = self.generation
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self._speaking(True)
            try:
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
                process = self.process
            except OSError:
                self._speaking(False)
                self.speechError.emit('הפעלת הקול נכשלה. התשובה עדיין מוצגת בחלון.')
                return
        def wait():
            try:
                process.stdin.write(speech)
                process.stdin.close()
            except (OSError, ValueError):
                pass
            code = process.wait()
            if code and generation == self.generation:
                self.speechError.emit('הקול של Gemini 3.8 Live אינו זמין כרגע. התשובה מוצגת בחלון.')
            self._speechFinished.emit(generation)
        threading.Thread(target=wait, daemon=True).start()

    @Slot()
    def stopSpeech(self):
        self.stop()

    def stop(self):
        with self.lock:
            self.ack.stop()
            self.generation += 1
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self.process = None
            self._speaking(False)


class GalaxyPanel(QWidget):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, window, *, muted_test=False, probe=False):
        super().__init__(window)
        self.window = window
        self.muted_test = muted_test
        self.probe = probe
        self.attaching = False
        self.status = QLabel('מחבר את ההערות לג׳רוויס…')
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status)
        self.web = QWebEngineView(self)
        self.profile = QWebEngineProfile(self.web)  # no disk cookies/cache
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.page = LocalPage(self.profile, self.web)
        self.web.setPage(self.page)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.profile.downloadRequested.connect(lambda request: request.cancel())
        settings = self.page.settings()
        for attribute, enabled in (
            (QWebEngineSettings.WebAttribute.WebGLEnabled, True),
            (QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, True),
            (QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False),
            (QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False),
            (QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False),
        ):
            settings.setAttribute(attribute, enabled)
        self.bridge = NativeBridge(self, muted_test)
        self.bridge.speechError.connect(self.show_error)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject('jarvisNative', self.bridge)
        self.page.setWebChannel(self.channel)
        resource = QFile(':/qtwebchannel/qwebchannel.js')
        if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError('Qt WebChannel resource is missing')
        source = bytes(resource.readAll()).decode('utf-8')
        resource.close()
        script = QWebEngineScript()
        script.setName('jarvis-native-bridge')
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(source + '\nwindow.jarvisNativeReady = new Promise(resolve => { new QWebChannel(qt.webChannelTransport, channel => { window.jarvisNative = channel.objects.jarvisNative; resolve(); }); });')
        self.page.scripts().insert(script)
        self.page.desktopMediaRequested.connect(self.select_screen)
        self.page.permissionRequested.connect(self.permission)
        self.page.loadFinished.connect(self.loaded)
        layout.addWidget(self.web, 1)
        self.ready.connect(self.load)
        self.failed.connect(self.show_error)
        self.attach_timer = QTimer(self)
        self.attach_timer.timeout.connect(self.attach)
        self.attach_timer.start(NATIVE_ATTACH_INTERVAL_MS)
        threading.Thread(target=self.start_service, daemon=True).start()

    def start_service(self):
        try:
            from core.galaxy_service import ensure_running, call
            directory = ROOT / '.galaxy-runtime'
            directory.mkdir(mode=0o700, exist_ok=True)
            path = directory / 'native.pid'
            path.write_text(str(os.getpid()))
            path.chmod(0o600)
            ensure_running()
            call('/native/attach', {}, timeout=3)
            self.ready.emit()
        except Exception:
            self.failed.emit('החיבור לגלקסיה לא עלה. בדוק את שרת ההערות בפורט 4700.')

    def attach(self):
        if self.attaching:
            return
        self.attaching = True
        def send():
            try:
                from core.galaxy_service import call
                call('/native/attach', {}, timeout=3)
            except Exception:
                pass  # viewer displays server connection state
            finally:
                self.attaching = False
        threading.Thread(target=send, daemon=True).start()

    def load(self):
        suffix = '&mute=1' if self.muted_test else ''
        suffix += '&focusprobe=1' if self.probe else ''
        self.web.setUrl(QUrl(f'http://127.0.0.1:{LOCAL_PORT}/?embedded=1' + suffix))

    def loaded(self, ok):
        self.status.setVisible(not ok)
        if not ok:
            self.status.setText('הגלקסיה לא נטענה. בדוק את החיבור לשרת המקומי.')

    def show_error(self, message):
        self.status.setText(message)
        self.status.show()

    def permission(self, request):
        if not local_origin(request.origin()):
            request.deny()
            return
        kind = request.permissionType()
        if kind == QWebEnginePermission.PermissionType.DesktopVideoCapture:
            request.grant()  # desktopMediaRequested presents the actual picker
        elif kind == QWebEnginePermission.PermissionType.MediaVideoCapture:
            result = QMessageBox.question(self, 'מצלמה', 'להפעיל מצלמה לזיהוי תנוחה מקומי? תמונה נשלחת למודל רק כשמבקשים במפורש.',
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                           QMessageBox.StandardButton.No)
            request.grant() if result == QMessageBox.StandardButton.Yes else request.deny()
        else:
            request.deny()  # microphone belongs exclusively to native Jarvis

    def select_screen(self, request):
        if not local_origin(self.page.url()):
            request.cancel()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('בחירת מסך לשיתוף עם ג׳רוויס')
        dialog.setMinimumSize(440, 260)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('בחר מסך שלם. השיתוף נשאר פעיל עד שתכבה אותו.'))
        choices = QListView(dialog)
        choices.setModel(request.screensModel())
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('שתף מסך')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('ביטול')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if request.screensModel().rowCount():
            choices.setCurrentIndex(request.screensModel().index(0, 0))
        if dialog.exec() == QDialog.DialogCode.Accepted and choices.currentIndex().isValid():
            request.selectScreen(choices.currentIndex())
        else:
            request.cancel()

    def close(self):
        self.bridge.stop()
        self.attach_timer.stop()
        self.page.deleteLater()
        self.profile.deleteLater()
        return super().close()
