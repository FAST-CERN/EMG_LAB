import threading
import time


class DdsBroadcast:
    """10 Hz heartbeat; timeout sends REST through the original class mapping."""

    def __init__(self, domain=0, interface="", adapter=None, clock=time.monotonic):
        if adapter is None:
            from bsi_robot_base import UnitreeDdsHumanoidRobotAdapter

            adapter = UnitreeDdsHumanoidRobotAdapter(domain_id=domain, interface=interface)
        self.adapter, self.clock = adapter, clock
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.event = {"filtered_class": 0, "probabilities": [1.0, 0.0, 0.0, 0.0]}
        self.updated = 0.0
        self.error = ""
        self.thread = None
        self.connected = False

    def start(self, source, device):
        if source != "live" or device not in ("Cometa", "Delsys"):
            raise ValueError("控制真实机器人前，请连接真实肌电设备，并使用实时信号进行推理。")
        self.connect()
        self.enable(source, device)

    def connect(self):
        if self.connected:
            return
        if not self.adapter.connect():
            raise RuntimeError(self.adapter.last_error)
        self.connected = True

    def enable(self, source, device):
        if source != "live" or device not in ("Cometa", "Delsys"):
            raise ValueError("真实机器人控制需要真实肌电设备的实时信号。")
        if not self.connected:
            raise ValueError("请先连接机器人 DDS。")
        if self.thread:
            return
        self.error = ""
        self.stop_event.clear()
        self.updated = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def update(self, event):
        with self.lock:
            self.event = dict(event)
            self.updated = self.clock()

    def publish_once(self):
        with self.lock:
            event = (
                self.event
                if self.clock() - self.updated < 1.0
                else {"filtered_class": 0, "probabilities": [1.0, 0.0, 0.0, 0.0]}
            )
            if not self.adapter.send_direction(event):
                raise RuntimeError(self.adapter.last_error or "DDS 发布失败。")

    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.publish_once()
                self.stop_event.wait(0.1)
        except Exception as exc:
            self.error = str(exc)
            self.stop_event.set()

    def disable(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
            if not self.adapter.send_direction(
                {"filtered_class": 0, "probabilities": [1.0, 0.0, 0.0, 0.0]}
            ):
                raise RuntimeError(self.adapter.last_error or "停止指令发送失败。")

    def close(self):
        try:
            self.disable()
        finally:
            self.adapter.disconnect()
            self.connected = False
