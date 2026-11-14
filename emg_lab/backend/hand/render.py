import threading

from emg_lab.backend.hand.model import HandModel
from emg_lab.contracts.events import EventHook, Worker


class HandRenderWorker(Worker):
    def __init__(self, parent=None):
        super().__init__()
        self.frame, self.ready, self.failed = EventHook(), EventHook(), EventHook()
        self.lock = threading.Lock()
        self.progress = 0.0
        self.angles = None
        self.stop_event = threading.Event()

    def set_progress(self, progress):
        with self.lock:
            self.progress = progress
            self.angles = None

    def set_angles(self, angles):
        with self.lock:
            self.angles = angles.copy()

    def run(self):
        renderer = None
        try:
            hand = HandModel()
            renderer = hand.renderer()
            first = True
            while not self.stop_event.is_set():
                with self.lock:
                    progress, angles = self.progress, self.angles
                if angles is None:
                    hand.set_progress(progress)
                else:
                    hand.set_angles(angles)
                renderer.update_scene(hand.data, camera=hand.camera)
                pixels = renderer.render()
                height, width, _ = pixels.shape
                self.frame.emit(pixels.copy())
                if first:
                    self.ready.emit()
                    first = False
                self.stop_event.wait(0.04)
        except Exception as exc:
            self.failed.emit(f"灵巧手 3D 画面无法加载：{exc}")
        finally:
            if renderer is not None:
                renderer.close()
