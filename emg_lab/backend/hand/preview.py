"""Hand simulation lifecycle and motion, independent of the desktop presentation."""

import time

from emg_lab.contracts.events import EventHook, HandMotionState, PeriodicTask
from emg_lab.contracts.tasks import HAND, HAND5, HAND_RATE

from .model import HandMotion
from .poses import PoseMotion
from .render import HandRenderWorker

RELAXED_PROGRESS = 0.5


class HandPreview:
    def __init__(self, task=HAND):
        self.task = task
        self.frame, self.ready, self.failed, self.changed = [EventHook() for _ in range(4)]
        self.motion = PoseMotion() if task == HAND5 else HandMotion()
        self.worker = None
        self.mode = None
        self._error = ""
        self.last_command = self.last_tick = time.monotonic()
        self.timer = PeriodicTask(self.tick)

    def start(self, mode):
        self.stop()
        if mode not in ("sample", "open"):
            raise ValueError("未知的灵巧手显示模式。")
        self.mode = mode
        self.motion = PoseMotion() if self.task == HAND5 else HandMotion()
        if mode == "sample":
            self.motion.progress = RELAXED_PROGRESS
        self._error = ""
        self.last_command = self.last_tick = time.monotonic()
        worker = self.worker = HandRenderWorker()
        if self.task == HAND5:
            worker.set_angles(self.motion.angles)
        else:
            worker.set_progress(self.motion.progress)
        worker.frame.connect(
            lambda frame: self.frame.emit(frame) if self.worker is worker else None
        )
        worker.ready.connect(lambda: self.ready.emit() if self.worker is worker else None)
        worker.failed.connect(lambda text: self._failed(worker, text))
        self.timer.start()
        worker.start()

    def _failed(self, worker, text):
        if self.worker is worker:
            self._error = text
            self.failed.emit(text)

    def sample(self, status):
        if self.mode != "sample":
            return
        if status.get("done") or status["phase"] != "动作" or status["cue"] == 0:
            self.motion.progress = RELAXED_PROGRESS
        self.command(status.get("command", 0))

    def command(self, command):
        if self.mode is None:
            return
        self.motion.set_command(command)
        self.last_command = time.monotonic()

    def tick(self):
        now = time.monotonic()
        if now - self.last_command > 1:
            self.motion.set_command(0)
        self.motion.advance(now - self.last_tick)
        self.last_tick = now
        worker = self.worker
        if worker:
            if self.task == HAND5:
                worker.set_angles(self.motion.angles)
            else:
                worker.set_progress(self.motion.progress)
        self.changed.emit(
            dict(
                command=self.motion.command,
                progress=100 * self.motion.progress,
                positions=self.motion.positions,
                source="simulation",
                rate=HAND_RATE,
            )
        )

    @property
    def error(self):
        return self._error

    def snapshot(self):
        return HandMotionState(
            self.motion.progress, self.motion.command, tuple(self.motion.positions)
        )

    def stop(self):
        self.timer.stop()
        self.mode = None
        self.motion.set_command(0)
        worker, self.worker = self.worker, None
        if worker:
            worker.stop_event.set()
            worker.wait()
