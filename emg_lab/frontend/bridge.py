"""Queued Qt adapters. Backend callbacks never call widgets directly."""

from PySide6 import QtCore as C
from PySide6 import QtGui as G

from emg_lab.contracts.events import LatestFrame


class FrameBridge(C.QObject):
    frame = C.Signal(G.QImage)
    frame_available = C.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mailbox = LatestFrame()
        self.frame_available.connect(self._image)

    def receive(self, pixels):
        if self.mailbox.put(pixels):
            self.frame_available.emit()

    @C.Slot()
    def _image(self):
        pixels = self.mailbox.take()
        if pixels is not None:
            self.frame.emit(
                G.QImage(
                    pixels.data,
                    pixels.shape[1],
                    pixels.shape[0],
                    pixels.strides[0],
                    G.QImage.Format_RGB888,
                ).copy()
            )


class WorkerAdapter(FrameBridge):
    ready = C.Signal()
    failed = C.Signal(str)
    telemetry = C.Signal(dict)
    competition_finished = C.Signal(str)

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        worker.frame.connect(self.receive)
        for name in ("ready", "failed", "telemetry", "competition_finished"):
            if hasattr(worker, name):
                getattr(worker, name).connect(getattr(self, name).emit)

    def __getattr__(self, name):
        worker = self.__dict__.get("worker")
        if worker is None:
            raise AttributeError(name)
        return getattr(worker, name)


class SimulationWorker(WorkerAdapter):
    def __init__(self, service, competition=None):
        super().__init__(service.create_robot_worker(competition))


class HandOutput(C.QObject):
    changed = C.Signal(str)
    failed = C.Signal(str)
    sample = C.Signal(dict)

    def __init__(self, parent, **kwargs):
        super().__init__(parent)
        self.output = parent.backend.create_hand_output(**kwargs)
        self.service = parent.backend
        for name in ("changed", "failed", "sample"):
            getattr(self.output, name).connect(getattr(self, name).emit)

    def __getattr__(self, name):
        output = self.__dict__.get("output")
        if output is None:
            raise AttributeError(name)
        return getattr(output, name)

    def connect_hand(self):
        self.service.connect_hand()
