"""Classroom physical scene and the original, optional DDS adapter."""

from PySide6 import QtCore


class RobotScene(QtCore.QObject):
    ready = QtCore.Signal()
    failed = QtCore.Signal(str)
    closed = QtCore.Signal()
    competition_finished = QtCore.Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.window = None
        self._error = ""
        self.source = "live"
        self.competition = None

    def start(self, mode):
        self.stop()
        if mode not in ("sample", "open"):
            raise ValueError("未知的机器人场景模式。")
        from emg_lab.frontend.robot_scene import SceneWindow

        window = self.window = SceneWindow(
            mode,
            self.parent(),
            source=self.source,
            competition=self.competition if mode == "open" else None,
        )
        window.ready.connect(lambda: self.ready.emit() if self.window is window else None)
        window.failed.connect(lambda message: self._failed(window, message))
        window.dismissed.connect(lambda: self._dismissed(window))
        window.competition_finished.connect(self.competition_finished)
        window.start()

    def _failed(self, window, message):
        if self.window is window:
            self._error = message
            self.failed.emit(message)

    def _dismissed(self, window):
        if self.window is window:
            self.window = None
            self.closed.emit()

    def sample(self, status):
        if self.window:
            self.window.show_capture(status)

    def command(self, command):
        if self.window:
            self.window.show_command(command)

    def velocity(self, velocity):
        if self.window:
            self.window.show_velocity(velocity)

    def arm_competition(self):
        if self.window:
            self.window.arm_competition()

    def end_competition(self, reason):
        if self.window:
            self.window.worker.end_competition(reason)

    @property
    def error(self):
        return self._error

    def stop(self):
        window, self.window = self.window, None
        self._error = ""
        if window:
            window.shutdown()
