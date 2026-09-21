"""Small non-activating desktop companion, driven by real server task state."""
from __future__ import annotations
import math
import threading
import time
from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QBrush, QCursor
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QApplication
from core.avatar import HoloAvatar

POLL_MS = 650
CARD_WIDTH = 496
CARD_HEIGHT = 216
EDGE_MARGIN = 24
MOVE_DURATION_MS = 360
MOVE_COOLDOWN_SECONDS = 2.0
AUTO_RETURN_SECONDS = 0  # Keep the desktop visible until the user asks to return.


def paint_reactor(p, center, radius, phase, amp=0.0, active=False):
    """Orbital reactor: one luminous body, depth-separated rings and real level."""
    x,y=center
    p.save();p.translate(x,y)
    glow=QRadialGradient(0,0,radius*1.35)
    glow.setColorAt(0,QColor(91,236,217,72+int(amp*55)))
    glow.setColorAt(.48,QColor(42,142,147,28));glow.setColorAt(1,QColor(5,13,19,0))
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QBrush(glow));p.drawEllipse(QRectF(-radius*1.35,-radius*1.35,radius*2.7,radius*2.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i,angle in enumerate((-32,32,90)):
        p.save();p.rotate(angle+math.sin(phase*.35+i)*8)
        p.setPen(QPen(QColor(107,225,210,80+i*25),1.3))
        rect=QRectF(-radius,-radius*.35,radius*2,radius*.7)
        p.drawEllipse(rect)
        a=phase*(.6+i*.17)+i*2.1
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#c3fff1'))
        p.drawEllipse(QRectF(math.cos(a)*radius-3,math.sin(a)*radius*.35-3,6,6));p.restore()
    r=radius*(.24+.04*amp)
    core=QRadialGradient(-r*.3,-r*.35,r*1.6)
    core.setColorAt(0,QColor('#edfff9'));core.setColorAt(.32,QColor('#7bead2'))
    core.setColorAt(.72,QColor('#248f94'));core.setColorAt(1,QColor('#0a293c'))
    p.setPen(QPen(QColor('#adfce5'),1));p.setBrush(QBrush(core));p.drawEllipse(QRectF(-r,-r,r*2,r*2))
    p.restore()


class Portrait(QWidget):
    def __init__(self, owner, parent=None):
        super().__init__(parent);self.owner=owner;self.phase=0
        try:self.avatar=HoloAvatar()
        except (OSError,ValueError):self.avatar=None
        self.setFixedSize(132,144)
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)

    def tick(self):
        if not self.isVisible(): return
        hud=self.owner.hud
        self.phase+=.05
        if self.avatar:self.avatar.step(.05,hud._amp_disp,speaking=hud.speaking,muted=False,state=hud.state)
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.owner.hud.hud_style=='core' or self.avatar is None:
            paint_reactor(p,(66,72),47,self.phase,self.owner.hud._amp_disp)
        else:
            self.avatar.paint(p,66,51,47,QColor('#84dfd0'),QColor('#b6fff1'),QColor('#0b171e'))
        p.end()


class DesktopCompanion(QWidget):
    refreshed = Signal(object,object)
    command_done = Signal(str)

    def __init__(self,owner):
        super().__init__(None,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.owner=owner
        self.setObjectName('desktopCompanion')
        self.setWindowTitle('Jarvis Agent · חלונית עבודה')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(CARD_WIDTH,CARD_HEIGHT)
        self._busy=False;self._task=None;self._focus={};self._dismissed=set();self._last_move=0.;self._drag=None
        self._manual=False;self._closed=False
        self.setStyleSheet('QLabel{color:#d4e8e9;background:transparent;border:0;font-family:Arial;} QPushButton{background:#192d37;color:#c2dadc;border:1px solid #243f49;border-radius:17px;padding:9px 12px;font-family:Arial;font-size:12px;} QPushButton:hover{background:#24434a;color:#efffff;border-color:#68cabd;} QPushButton:focus{border:2px solid #8fe9d5;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(20,16,20,16);layout.setSpacing(9)
        top=QHBoxLayout();top.setSpacing(15);top.setDirection(QHBoxLayout.Direction.LeftToRight)
        labels=QVBoxLayout();labels.setSpacing(4)
        self.eyebrow=QLabel('JARVIS  /  לצדך');self.eyebrow.setStyleSheet('color:#70adab;font-size:10px;letter-spacing:2px;');labels.addWidget(self.eyebrow)
        self.timer_label=QLabel('00:00');self.timer_label.setAlignment(Qt.AlignmentFlag.AlignLeft);self.timer_label.setStyleSheet('font-size:37px;font-weight:700;color:#e6fff8;');labels.addWidget(self.timer_label)
        self.status_label=QLabel('לצדך, אדוני');self.status_label.setWordWrap(True);self.status_label.setMaximumHeight(42)
        self.status_label.setStyleSheet('color:#a4c2c7;font-size:13px;');labels.addWidget(self.status_label)
        top.addLayout(labels,1);self.portrait=Portrait(owner,self);top.addWidget(self.portrait)
        layout.addLayout(top,1)
        buttons=QHBoxLayout();buttons.setSpacing(8);buttons.setDirection(QHBoxLayout.Direction.LeftToRight)
        self.stop_button=QPushButton('עצור');self.stop_button.clicked.connect(self.stop_task)
        self.middle_button=QPushButton('פתח ג׳רוויס');self.middle_button.clicked.connect(self.middle)
        self.last_button=QPushButton('מיקרופון כבוי');self.last_button.clicked.connect(self.last)
        for button in (self.stop_button,self.middle_button,self.last_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor);buttons.addWidget(button,1)
        layout.addLayout(buttons)
        self.refreshed.connect(self.apply);self.command_done.connect(self.feedback)
        self.poller=QTimer(self);self.poller.timeout.connect(self.poll);self.poller.start(POLL_MS)
        self.mover=QTimer(self);self.mover.timeout.connect(self.avoid_pointer);self.mover.start(200)
        self.animation=QPropertyAnimation(self,b'pos',self);self.animation.setDuration(MOVE_DURATION_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor('#0b171e'));p.setPen(QPen(QColor('#579f9c') if not self._focus.get('drifting') else QColor('#dbb485'),1.2))
        p.drawRoundedRect(QRectF(1,1,self.width()-2,self.height()-2),24,24);p.end()

    def poll(self):
        if self._busy or self._closed: return
        self._busy=True
        def read():
            try:
                from core.galaxy_service import call
                tasks=call('/tasks',timeout=2);focus=call('/focus/state',timeout=2)
                self.refreshed.emit(tasks,focus)
            except Exception:
                self.refreshed.emit(None,None)
        threading.Thread(target=read,daemon=True,name='jarvis-companion-state').start()

    def apply(self,tasks,focus):
        self._busy=False
        if self._closed: return
        if tasks is None:
            if self.isVisible(): self.status_label.setText('ממתין לחיבור לג׳רוויס')
            return
        self._focus=focus.get('focus',focus)
        jobs=tasks.get('tasks',[])
        active=next((t for t in jobs if t.get('desktop') and t.get('status')=='running'),None)
        if active:
            self._task=active
            self.status_label.setText(active.get('progress','עובד על הבקשה')[:78])
            elapsed=max(0,int(time.time()-active.get('started_at',time.time())))
            self.timer_label.setText(f'{elapsed//60:02}:{elapsed%60:02}')
            self.eyebrow.setText('JARVIS  /  עובד במחשב')
            if active['id'] not in self._dismissed and not self.isVisible():self.enter()
        elif self._task:
            latest=next((t for t in jobs if t['id']==self._task['id']),None)
            if latest and latest.get('status') not in {'running','queued'}:
                self._task=latest
                self.status_label.setText({'completed':'המשימה הסתיימה, אדוני','failed':'המשימה נעצרה. הפרטים בג׳רוויס','cancelled':'המשימה בוטלה, אדוני'}.get(latest['status'],'מוכן לבקשה הבאה'))
                self.stop_button.setEnabled(False)
        if self._focus.get('on') and not active:
            remaining=int(self._focus.get('seconds_remaining',0));self.timer_label.setText(f'{remaining//60:02}:{remaining%60:02}')
            self.status_label.setText('ממתין ללשונית העבודה' if self._focus.get('deferred') else 'בהשהיה' if self._focus.get('paused') else 'חוזרים לעבודה' if self._focus.get('drifting') else 'איתך עד סוף המפגש')
            self.eyebrow.setText('JARVIS  /  ריכוז')
        focusing=self._focus.get('on') and not active
        self.middle_button.setText(('המשך' if self._focus.get('paused') else 'השהה') if focusing else 'פתח ג׳רוויס')
        self.last_button.setText('נעל על הלשונית' if focusing else ('מיקרופון כבוי' if self.owner._muted else 'מקשיב לפנייה'))
        self.stop_button.setEnabled(bool(focusing or active))
        self.update()

    def enter(self,manual=False):
        self._manual=manual
        self._previous_window_state=self.owner.windowState()
        if manual:self._dismissed.clear()
        screen=QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        area=screen.availableGeometry()
        self.move(area.right()-self.width()-EDGE_MARGIN,area.top()+EDGE_MARGIN)
        self.owner.hide();self.show();self._last_move=time.monotonic()

    def restore(self):
        if self._task:self._dismissed.add(self._task['id'])
        self.hide()
        previous=getattr(self,'_previous_window_state',Qt.WindowState.WindowNoState)
        if previous & Qt.WindowState.WindowFullScreen:self.owner.showFullScreen()
        elif previous & Qt.WindowState.WindowMaximized:self.owner.showMaximized()
        else:self.owner.showNormal()
        self.owner.raise_();self.owner.activateWindow()

    def avoid_pointer(self):
        if not self.isVisible() or self._drag or time.monotonic()-self._last_move < MOVE_COOLDOWN_SECONDS:return
        point=QCursor.pos()
        # Keep controls reachable: entering the card is deliberate, so never flee
        # while hovered. Move when the pointer approaches its outside edge.
        if self.geometry().contains(point): return
        screen=QApplication.screenAt(point) or self.screen();area=screen.availableGeometry()
        if self.screen()==screen and not self.geometry().adjusted(-70,-70,70,70).contains(point): return
        corners=[QPoint(x,y) for x in (area.left()+EDGE_MARGIN,area.right()-self.width()-EDGE_MARGIN)
                 for y in (area.top()+EDGE_MARGIN,area.bottom()-self.height()-EDGE_MARGIN)]
        target=max(corners,key=lambda p:(p.x()+self.width()/2-point.x())**2+(p.y()+self.height()/2-point.y())**2)
        self.animation.stop();self.animation.setStartValue(self.pos());self.animation.setEndValue(target);self.animation.start()
        self._last_move=time.monotonic()

    def request(self,path,payload):
        def run():
            try:
                from core.galaxy_service import call
                call(path,payload,timeout=3);self.command_done.emit('עודכן')
            except Exception:self.command_done.emit('הפעולה לא אושרה. נסה שוב')
        threading.Thread(target=run,daemon=True).start()

    def feedback(self,text):
        if not self._closed:self.status_label.setText(text)

    def stop_task(self):
        if self._task and self._task.get('status')=='running':
            self.request('/tasks/'+self._task['id']+'/cancel',{})
            self.owner._do_interrupt()
        elif self._focus.get('on'):self.request('/focus/abort',{})

    def middle(self):
        if self._focus.get('on') and not (self._task and self._task.get('status')=='running'):
            self.request('/focus/resume' if self._focus.get('paused') else '/focus/pause',{})
        else:self.restore()

    def last(self):
        if self._focus.get('on') and not (self._task and self._task.get('status')=='running'):
            self.request('/focus/retarget',{'from_card':True})
        else:self.owner._toggle_mute();self.poll()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self._drag=event.globalPosition().toPoint()-self.pos()

    def mouseMoveEvent(self,event):
        if self._drag is not None:self.move(event.globalPosition().toPoint()-self._drag)

    def mouseReleaseEvent(self,event):self._drag=None;self._last_move=time.monotonic()
    def mouseDoubleClickEvent(self,event):self.restore()

    def shutdown(self):
        self._closed=True;self.poller.stop();self.mover.stop();self.portrait.timer.stop();self.hide()
