"""Separate collection demonstration and embedded inference preview."""
import threading
import time
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from ..tasks import HAND, HAND5, HAND_RATE
from .model import HandMotion, HandModel
from .poses import PoseMotion
from ..capture import preparation_countdown

# The existing neutral collection pose: four fingers half curled, default thumb.
RELAXED_PROGRESS = .5


class HandView(W.QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.picture=None
        self.setMinimumHeight(240)
        self.setMaximumHeight(340)
        self.setSizePolicy(W.QSizePolicy.Expanding,W.QSizePolicy.Expanding)

    def set_frame(self,picture):
        self.picture=picture
        self.update()

    def paintEvent(self,event):
        painter=G.QPainter(self)
        painter.fillRect(self.rect(),G.QColor('#eef5fa'))
        if self.picture is None:
            painter.setPen(G.QColor('#60758a'))
            painter.drawText(self.rect(),C.Qt.AlignCenter,'Revo2 3D 示范将在实验开始时显示')
        else:
            size=self.picture.size().scaled(self.size(),C.Qt.KeepAspectRatio)
            rect=C.QRect((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height())
            painter.drawImage(rect,self.picture)


class HandRenderWorker(C.QThread):
    frame=C.Signal(G.QImage)
    ready=C.Signal()
    failed=C.Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.lock=threading.Lock()
        self.progress=0.
        self.angles=None
        self.stop_event=threading.Event()

    def set_progress(self,progress):
        with self.lock:
            self.progress=progress
            self.angles=None

    def set_angles(self,angles):
        with self.lock:
            self.angles=angles.copy()

    def run(self):
        renderer=None
        try:
            hand=HandModel()
            renderer=hand.renderer()
            first=True
            while not self.stop_event.is_set():
                with self.lock: progress,angles=self.progress,self.angles
                if angles is None: hand.set_progress(progress)
                else: hand.set_angles(angles)
                renderer.update_scene(hand.data,camera=hand.camera)
                pixels=renderer.render()
                height,width,_=pixels.shape
                self.frame.emit(G.QImage(pixels.data,width,height,pixels.strides[0],G.QImage.Format_RGB888).copy())
                if first:
                    self.ready.emit(); first=False
                self.stop_event.wait(.04)
        except Exception as exc:
            self.failed.emit(f'灵巧手 3D 画面无法加载：{exc}')
        finally:
            if renderer is not None: renderer.close()


class HandCaptureWindow(W.QWidget):
    dismissed = C.Signal()

    def __init__(self, parent=None, task=HAND):
        super().__init__(parent, C.Qt.Window)
        self.task=task
        self.setAttribute(C.Qt.WA_DeleteOnClose)
        self.setWindowTitle('灵巧手 · 采集动作示范')
        self.resize(800, 680)
        self.setMinimumSize(560, 520)
        self.controlled_close = False
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.cue = W.QLabel('放松肌肉，准备开始')
        self.cue.setAlignment(C.Qt.AlignCenter)
        self.cue.setObjectName('cueBanner')
        layout.addWidget(self.cue)
        self.detail = W.QLabel('初始和准备阶段均显示放松姿态。')
        self.detail.setAlignment(C.Qt.AlignCenter)
        layout.addWidget(self.detail)
        self.view = HandView()
        self.view.setMaximumHeight(16777215)
        layout.addWidget(self.view, 1)
        hint = W.QLabel('动作：保持约定的肌肉动作直到倒计时结束。\n停止保持：放松／静息。此窗口仅作采集示范。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        finish = W.QPushButton('结束采集并保存')
        finish.setMinimumHeight(40)
        finish.clicked.connect(self.close)
        layout.addWidget(finish)

    def show_capture(self, status):
        if status.get('done'):
            self.cue.setText('采集完成，放松肌肉')
            return
        if status['phase'] != '动作':
            self.cue.setText(f"放松 · 准备{self.task.names[status['cue']]}  {preparation_countdown(status)}")
        else:
            action = '停止 · 放松肌肉' if status['cue'] == 0 else self.task.names[status['cue']]
            self.cue.setText(f"{action}  {status['remaining']:.1f} 秒")
        self.detail.setText(f"第 {status['trial']} / {status['trial_count']} 组 · 第 {status['action_index']} / {len(self.task.classes)} 个动作")

    def closeEvent(self, event):
        if not self.controlled_close:
            self.dismissed.emit()
        event.accept()

    def shutdown(self):
        self.controlled_close = True
        self.close()


class HandScene(C.QObject):
    ready=C.Signal()
    failed=C.Signal(str)
    closed=C.Signal()
    changed=C.Signal(dict)

    def __init__(self,parent=None,views=(),task=HAND):
        super().__init__(parent)
        self.task=task
        self.views=views
        self.worker=None
        self.window=None
        self.motion=PoseMotion() if task==HAND5 else HandMotion()
        self.mode=None
        self._last_cue=None
        self._error=''
        self.last_command=0.
        self.last_tick=time.monotonic()
        self.timer=C.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.tick)

    def start(self,mode):
        self.stop()
        if mode not in ('sample','open'): raise ValueError('未知的灵巧手显示模式。')
        self.mode=mode
        self.motion=PoseMotion() if self.task==HAND5 else HandMotion()
        if mode == 'sample':
            self.motion.progress = RELAXED_PROGRESS
            self.window = HandCaptureWindow(self.parent(),self.task)
            self.window.dismissed.connect(self._dismissed)
            self.window.show()
        self._last_cue=None
        self._error=''
        self.last_command=self.last_tick=time.monotonic()
        worker=self.worker=HandRenderWorker(self)
        if self.task==HAND5: worker.set_angles(self.motion.angles)
        else: worker.set_progress(self.motion.progress)
        worker.frame.connect(self._frame)
        worker.ready.connect(lambda:self.ready.emit() if self.worker is worker else None)
        worker.failed.connect(lambda message:self._failed(worker,message))
        self.timer.start()
        worker.start()

    def _frame(self,picture):
        if self.worker is None: return
        if self.mode == 'sample':
            if self.window: self.window.view.set_frame(picture)
        else:
            for view in self.views: view.set_frame(picture)

    def _dismissed(self):
        self.window = None
        self.closed.emit()

    def _failed(self,worker,message):
        if self.worker is worker:
            self._error=message
            self.failed.emit(message)

    def sample(self,status):
        if self.mode!='sample': return
        if self.window: self.window.show_capture(status)
        if status.get('done'):
            self.motion.progress = RELAXED_PROGRESS
            self.command(0); return
        if status['phase'] != '动作' or status['cue'] == 0:
            self.motion.progress = RELAXED_PROGRESS
        self.command(status['command'])

    def command(self,command):
        if self.mode is None: return
        self.motion.set_command(command)
        self.last_command=time.monotonic()

    def tick(self):
        now=time.monotonic()
        if now-self.last_command>1.:
            self.motion.set_command(0)
        self.motion.advance(now-self.last_tick)
        self.last_tick=now
        if self.worker:
            if self.task==HAND5: self.worker.set_angles(self.motion.angles)
            else: self.worker.set_progress(self.motion.progress)
        self.changed.emit(dict(command=self.motion.command,progress=100*self.motion.progress,
                               positions=self.motion.positions,source='simulation',rate=HAND_RATE))

    @property
    def error(self): return self._error

    def stop(self):
        self.timer.stop()
        self.mode=None
        self.motion.set_command(0)
        worker,self.worker=self.worker,None
        if worker:
            worker.stop_event.set()
            worker.wait()  # Renderer owns its GL context and releases it before destruction.
            worker.deleteLater()
        window, self.window = self.window, None
        if window: window.shutdown()
