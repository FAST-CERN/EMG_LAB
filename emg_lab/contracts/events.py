"""Qt-independent event and worker primitives shared across application ports."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


class EventHook:
    """Thread-safe callback list. UI consumers must cross their own queued bridge."""

    def __init__(self):
        self._callbacks: list[Callable] = []
        self._lock = threading.RLock()

    def connect(self, callback):
        with self._lock:
            self._callbacks.append(callback)
        return callback

    def disconnect(self, callback):
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def emit(self, *args):
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback(*args)

    __call__ = emit


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)

    def wait(self, milliseconds=None):
        if self.ident is not None and threading.current_thread() is not self:
            self.join(None if milliseconds is None else milliseconds / 1000)
        return not self.is_alive()

    def deleteLater(self):
        """Legacy worker API; Python owns the worker's memory."""

    def isRunning(self):
        return self.is_alive()


class LatestFrame:
    """Bounded display-only mailbox. Acquisition streams must never use this policy."""

    def __init__(self):
        self._value = None
        self._lock = threading.Lock()

    def put(self, value):
        with self._lock:
            notify = self._value is None
            self._value = value
            return notify

    def take(self):
        with self._lock:
            value, self._value = self._value, None
            return value


class PeriodicTask:
    def __init__(self, callback, interval=0.03):
        self.callback = callback
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def run():
            deadline = time.monotonic()
            while not self._stop.is_set():
                self.callback()
                deadline += self.interval
                self._stop.wait(max(0, deadline - time.monotonic()))

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


@dataclass(frozen=True)
class ApplicationEvent:
    kind: str
    payload: dict


@dataclass(frozen=True)
class TrainingRequest:
    recordings: tuple[str, ...]
    name: str
    epochs: int = 30
    architecture: str = "LiteCNN1D_channels_v2"
    model_config: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceConfig:
    device: str
    channel_ids: tuple[int, ...]
    action: str = "connect"
    pair_number: int = 1


@dataclass(frozen=True)
class CaptureState:
    identity: str
    completed: bool
    status_value: dict
    metadata: dict

    def status(self):
        return dict(self.status_value)


@dataclass(frozen=True)
class HandMotionState:
    progress: float
    command: int
    positions: tuple
