"""Separate collection demonstration and embedded inference preview."""

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

from emg_lab.contracts.tasks import HAND
from emg_lab.contracts.timing import preparation_countdown
from emg_lab.frontend.bridge import FrameBridge

# The existing neutral collection pose: four fingers half curled, default thumb.
RELAXED_PROGRESS = 0.5


class HandView(W.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.picture = None
        self.setMinimumHeight(240)
        self.setMaximumHeight(340)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Expanding)

    def set_frame(self, picture):
        self.picture = picture
        self.update()

    def paintEvent(self, event):
        painter = G.QPainter(self)
        painter.fillRect(self.rect(), G.QColor("#eef5fa"))
        if self.picture is None:
            painter.setPen(G.QColor("#60758a"))
            painter.drawText(self.rect(), C.Qt.AlignCenter, "Revo2 3D 示范将在实验开始时显示")
        else:
            size = self.picture.size().scaled(self.size(), C.Qt.KeepAspectRatio)
            rect = C.QRect(
                (self.width() - size.width()) // 2,
                (self.height() - size.height()) // 2,
                size.width(),
                size.height(),
            )
            painter.drawImage(rect, self.picture)


class HandCaptureWindow(W.QWidget):
    dismissed = C.Signal()

    def __init__(self, parent=None, task=HAND):
        super().__init__(parent, C.Qt.Window)
        self.task = task
        self.setAttribute(C.Qt.WA_DeleteOnClose)
        self.setWindowTitle("灵巧手 · 采集动作示范")
        self.resize(800, 680)
        self.setMinimumSize(560, 520)
        self.controlled_close = False
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.cue = W.QLabel("放松肌肉，准备开始")
        self.cue.setAlignment(C.Qt.AlignCenter)
        self.cue.setObjectName("cueBanner")
        layout.addWidget(self.cue)
        self.detail = W.QLabel("初始和准备阶段均显示放松姿态。")
        self.detail.setAlignment(C.Qt.AlignCenter)
        layout.addWidget(self.detail)
        self.view = HandView()
        self.view.setMaximumHeight(16777215)
        layout.addWidget(self.view, 1)
        hint = W.QLabel(
            "动作：保持约定的肌肉动作直到倒计时结束。\n停止保持：放松／静息。此窗口仅作采集示范。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        finish = W.QPushButton("结束采集并保存")
        finish.setMinimumHeight(40)
        finish.clicked.connect(self.close)
        layout.addWidget(finish)

    def show_capture(self, status):
        if status.get("done"):
            self.cue.setText("采集完成，放松肌肉")
            return
        if status["phase"] != "动作":
            self.cue.setText(
                f"放松 · 准备{self.task.names[status['cue']]}  {preparation_countdown(status)}"
            )
        else:
            action = "停止 · 放松肌肉" if status["cue"] == 0 else self.task.names[status["cue"]]
            self.cue.setText(f"{action}  {status['remaining']:.1f} 秒")
        self.detail.setText(
            f"第 {status['trial']} / {status['trial_count']} 组 · 第 {status['action_index']} / {len(self.task.classes)} 个动作"
        )

    def closeEvent(self, event):
        if not self.controlled_close:
            self.dismissed.emit()
        event.accept()

    def shutdown(self):
        self.controlled_close = True
        self.close()


class HandScene(C.QObject):
    ready = C.Signal()
    failed = C.Signal(str)
    closed = C.Signal()
    changed = C.Signal(dict)

    def __init__(self, parent, views=(), task=HAND):
        super().__init__(parent)
        self.task = task
        self.views = views
        self.window = None
        self.preview = parent.backend.create_hand_scene(task)
        self.preview.ready.connect(self.ready.emit)
        self.preview.failed.connect(self.failed.emit)
        self.preview.changed.connect(self.changed.emit)
        self.frames = FrameBridge(self)
        self.preview.frame.connect(self.frames.receive)
        self.frames.frame.connect(self._frame)

    def start(self, mode):
        self.stop()
        if mode == "sample":
            self.window = HandCaptureWindow(self.parent(), self.task)
            self.window.dismissed.connect(self._dismissed)
            self.window.show()
        self.preview.start(mode)

    def _frame(self, picture):
        if self.window:
            self.window.view.set_frame(picture)
        else:
            for view in self.views:
                view.set_frame(picture)

    def _dismissed(self):
        self.window = None
        self.closed.emit()

    def sample(self, status):
        if self.window:
            self.window.show_capture(status)

    def command(self, command):
        self.preview.command(command)

    def tick(self):
        self.preview.tick()

    @property
    def motion(self):
        return self.preview.snapshot()

    @property
    def worker(self):
        return self.preview.worker

    @property
    def mode(self):
        return self.preview.mode

    @property
    def error(self):
        return self.preview.error

    def stop(self):
        self.preview.stop()
        window, self.window = self.window, None
        if window:
            window.shutdown()
