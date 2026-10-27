"""Interruptible host-side open/fist controller, independent of Tk and EMG.

Uses the positions exported from this left hand. Factory timing is deliberately
replaced by position/speed commands and feedback-based stage advancement.
No current thresholds or motion timeouts are imposed by this controller.
"""
from __future__ import annotations
import json
from pathlib import Path
import queue
import struct
import threading
import time

import usb.core
from .revo2_control import UsbHand, AXES, HANDS, valid_ack
from .revo2_windows_probe import READS, crc16, decode_usb_packet, DLC_LENGTHS, EFF, FD, BRS

BASE = Path(__file__).resolve().parent
LABELS = {"open": "张开", "fist": "握合"}
STAGE_LABELS = {"open": ("拇指调整，四指保持", "六路展开", "拇指回到张开姿态"),
                "fist": ("拇指准备，四指保持", "六路握合")}
ARRIVAL_TOLERANCE = 5  # 0.5% of travel; stage completion only, not a motion limit.


def group_packet(channel, slave, register, words):
    words = list(words)
    if register == 1022:
        if (len(words) != 12 or any(type(w) is not int for w in words)
                or any(not 0 <= w <= 1000 for w in words[::2])
                or any(not 1 <= w <= 1000 for w in words[1::2])):
            raise ValueError("无效的六路位置/速度参数")
    elif register == 1034:
        if words != [0] * 6:
            raise ValueError("速度控制仅用于全部停止")
    else:
        raise ValueError("此控制器不写入其他寄存器")
    body = struct.pack(">BBHHB", slave, 0x10, register, len(words), 2 * len(words))
    body += struct.pack(">" + "H" * len(words), *words)
    payload = body + struct.pack("<H", crc16(body))
    dlc = next(i for i, length in enumerate(DLC_LENGTHS) if length >= len(payload))
    can_id = EFF | slave << 16 | 1 << 8 | len(payload)
    return struct.pack("<IIBBBB", 0, can_id, dlc, channel, FD | BRS, 0) + payload.ljust(64, b"\0")


class GestureUsbHand(UsbHand):
    def __init__(self, side="left"):
        READS.update({(3, 946, 6), (3, 952, 6), (3, 958, 6)})
        super().__init__(side)
        try:
            self.limits = {name: list(struct.unpack(">6H", self.read(3, reg, 6)))
                           for name, reg in (("minimum", 946), ("maximum", 952), ("speed", 958))}
        except Exception:
            self.close()
            raise

    def _group_write(self, register, words):
        packet = group_packet(self.spec["channel"], self.spec["slave"], register, words)
        self.adapter.device.write(self.adapter.ep_out, packet, timeout=250)
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            try:
                raw = bytes(self.adapter.device.read(self.adapter.ep_in, 512, timeout=25))
            except usb.core.USBTimeoutError:
                continue
            try:
                frame = decode_usb_packet(raw)
            except ValueError:
                continue
            if valid_ack(frame, self.spec["channel"], self.spec["slave"], register, len(words)):
                return
        raise TimeoutError("控制确认超时；不重发运动命令")

    def move_all(self, positions, speed_deg_s, weights=None):
        speeds = normalized_speeds(speed_deg_s, self.limits, weights)
        self._group_write(1022, [w for pair in zip(positions, speeds) for w in pair])

    def stop_all(self):
        self._group_write(1034, [0] * 6)


def normalized_speeds(speed_deg_s, limits, weights=None):
    if not 1 <= speed_deg_s <= min(limits["speed"]):
        raise ValueError("速度超出设备支持范围")
    weights = [1] * 6 if weights is None else weights
    if len(weights) != 6 or any(not 0 <= w <= 1 for w in weights):
        raise ValueError("无效的驱动速度比例")
    return [max(1, round(1000 * speed_deg_s * weight / maximum))
            for maximum,weight in zip(limits["speed"],weights)]


class GestureSimHand:
    """Deterministic kinematics with the measured device's angle/speed mapping."""
    def __init__(self, side="left"):
        self.info = dict(side=side, serial=HANDS[side]["serial"], firmware="SIMULATION", unit_mode=0)
        self.limits = dict(minimum=[0]*6, maximum=[60, 89, 81, 81, 81, 81], speed=[145, 160, 130, 130, 130, 130])
        self.positions = [400., 337., 0., 0., 0., 0.]
        self.targets = self.positions.copy()
        self.speed = 30
        self.weights = [1] * 6
        self.last = time.monotonic()
        self.writes = []
        self.closed = False

    def status(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        speeds, states = [], []
        for i in range(6):
            delta = self.targets[i] - self.positions[i]
            step = self.speed * self.weights[i] * 1000 / (self.limits["maximum"][i] - self.limits["minimum"][i]) * dt
            self.positions[i] += max(-step, min(step, delta))
            moving = abs(self.targets[i] - self.positions[i]) > 0.5
            states.append(int(moving))
            speeds.append(round((1 if delta > 0 else -1) * self.speed * self.weights[i] / self.limits["speed"][i] * 1000) if moving else 0)
        return dict(positions=[round(p) for p in self.positions], speeds=speeds,
                    currents_raw=[90 if s else 0 for s in states], motor_states=states)

    def move_all(self, positions, speed_deg_s, weights=None):
        normalized_speeds(speed_deg_s, self.limits, weights)
        self.status()
        self.targets, self.speed = list(positions), speed_deg_s
        self.weights = [1]*6 if weights is None else list(weights)
        self.writes.append(("move", list(positions), speed_deg_s))

    def stop_all(self):
        self.status()
        self.targets = self.positions.copy()
        self.writes.append(("stop",))

    def close(self):
        self.closed = True


class GesturePlanner:
    def __init__(self, limits, serial, path=BASE / "revo2_builtin_sequences.json"):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not data.get("completed") or data.get("errors") or data["axis_order"] != list(AXES)
                or data["device"]["serial"] != serial):
            raise ValueError("动作序列文件不属于当前设备或导出不完整")
        if any(b <= a for a, b in zip(limits["minimum"], limits["maximum"])):
            raise ValueError("设备位置量程无效")
        self.arrival_tolerances = [ARRIVAL_TOLERANCE] * 6
        # Measured on this hand: AUX rebounds to 13/1000 (~1.16 degrees)
        # after reaching zero, while reporting idle and zero speed. A 2-degree
        # AUX arrival band accommodates this holding behavior. It changes
        # stage recognition only, not target positions or hardware protection.
        self.arrival_tolerances[1] = max(ARRIVAL_TOLERANCE,
            round(2000 / (limits["maximum"][1] - limits["minimum"][1])))
        self.limits = limits
        self.steps, self.durations = {}, {}
        for seq in data["sequences"]:
            name = seq["name"]
            if name not in LABELS:
                continue
            result, durations = [], []
            for step in seq["steps"]:
                values = step["positions_deg"]
                if step["mode"] != 1 or len(values) != 6:
                    raise ValueError("不支持此动作步骤格式")
                target = []
                for i, value in enumerate(values):
                    lo, hi = limits["minimum"][i], limits["maximum"][i]
                    if value == -1:
                        target.append(None)
                    elif lo <= value <= hi:
                        target.append(round(1000 * (value-lo) / (hi-lo)))
                    else:
                        raise ValueError("动作目标超出当前设备量程")
                result.append(target)
                timing = step["durations_ms"]
                if len(timing) != 6 or any(t <= 0 for t in timing):
                    raise ValueError("无效的动作到位时间")
                durations.append(list(timing))
            self.steps[name] = result
            self.durations[name] = durations
        if set(self.steps) != set(LABELS) or any(not s for s in self.steps.values()):
            raise ValueError("缺少张开/握合步骤")
        # Host-side adaptation for continuous EMG direction changes: the factory
        # fist preparation opens four fingers. Hold them instead, just as in the
        # exported OPEN preparation, so a partial close need not reset to zero.
        # Thumb preparation and both final poses are unchanged.
        self.steps["fist"][0][2:] = [None] * 4
        self.cancel()

    def cancel(self):
        self.intent = None
        self.index = 0
        self.active = False
        self.targets = None
        self.streak = 0

    def _stage(self, positions):
        self.targets = [p if t is None else t for t, p in zip(self.steps[self.intent][self.index], positions)]
        self.start_positions = list(positions)
        # Retain the factory's coordination: e.g. fist thumb axes use 2000 ms,
        # four fingers use 100 ms (bounded by their physical maximum speeds).
        # Derive constant per-axis speed ratios ONCE at stage entry. A later
        # speed-slider update scales these ratios without restarting the stage.
        base_speeds = [min(vmax, abs(t-p) * (hi-lo) / duration)
                       for t,p,lo,hi,duration,vmax in zip(self.targets,positions,
                           self.limits["minimum"],self.limits["maximum"],
                           self.durations[self.intent][self.index],self.limits["speed"])]
        fastest = max(base_speeds) or 1
        self.weights = [v/fastest for v in base_speeds]
        self.streak = 0
        return list(self.targets)

    def begin(self, intent, positions):
        if intent not in LABELS:
            raise ValueError("未知动作")
        if self.intent == intent:
            return None  # Also ignore repeats after completion.
        self.intent, self.index, self.active = intent, 0, True
        return self._stage(positions)

    def observe(self, sample):
        if not self.active:
            return None
        reached = all(abs(p-t) <= tolerance and abs(v) <= 5 and state == 0
                      for p,t,v,state,tolerance in zip(sample["positions"], self.targets, sample["speeds"],
                                                       sample["motor_states"], self.arrival_tolerances))
        self.streak = self.streak + 1 if reached else 0
        if self.streak < 3:
            return None
        if self.index + 1 == len(self.steps[self.intent]):
            self.active = False
            return "done"
        self.index += 1
        return self._stage(sample["positions"])

    def view(self, positions):
        if self.intent is None:
            return dict(intent=None, active=False, targets=None, weights=[0]*6, stage=0, count=0, progress=0, stage_label="等待指令")
        count = len(self.steps[self.intent])
        travel = sum(abs(t-s) for t,s in zip(self.targets, self.start_positions))
        remaining = sum(abs(t-p) for t,p in zip(self.targets, positions))
        fraction = max(0, min(1, 1-remaining/travel)) if travel else 1
        progress = 100 * (self.index + fraction) / count if self.active else 100
        return dict(intent=self.intent, active=self.active, targets=self.targets, weights=self.weights, stage=self.index+1,
                    count=count, progress=progress,
                    stage_label=STAGE_LABELS[self.intent][self.index])


class GestureController(threading.Thread):
    """One I/O owner; latest intent wins, STOP clears all unsent requests.

    Public input API for a future EMG decoder: request_intent, set_speed,
    request_stop. Duplicate classifications do not reset the stage planner.
    """
    def __init__(self, factory=GestureUsbHand):
        super().__init__(name="revo2-gestures", daemon=True)
        self.factory = factory
        self.events = queue.Queue()
        self.connect_event, self.stop_event = threading.Event(), threading.Event()
        self.disconnect_event, self.quit_event = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.pending_intent = None
        self.speed, self.sent_speed = 30, None
        self.hand = self.planner = None
        self.touched = False
        self.heartbeat = time.monotonic()
        self.last_read = self.last_send = 0
        self.sample_count = 0

    def emit(self, kind, **data):
        self.events.put(dict(kind=kind, **data))

    def heartbeat_tick(self):
        self.heartbeat = time.monotonic()

    def interrupted(self):
        return self.stop_event.is_set() or self.disconnect_event.is_set() or self.quit_event.is_set()

    def request_intent(self, intent):
        if intent not in LABELS:
            raise ValueError("未知动作")
        with self.lock:
            if self.hand is None or self.interrupted():
                return
            self.pending_intent = intent

    def set_speed(self, value):
        value = int(value)
        maximum = min(self.hand.limits["speed"]) if self.hand else 130
        if not 1 <= value <= maximum:
            raise ValueError(f"速度应为 1–{maximum} °/s")
        with self.lock:
            self.speed = value

    def request_stop(self):
        with self.lock:
            self.pending_intent = None
            self.stop_event.set()

    def read(self):
        sample = self.hand.status()
        if any(len(sample[k]) != 6 for k in ("positions", "speeds", "currents_raw", "motor_states")):
            raise ValueError("状态回读不完整")
        if any(not 0 <= p <= 1000 for p in sample["positions"]):
            raise ValueError("位置回读超出设备单位范围")
        self.last_read = sample["received_at"] = time.monotonic()
        self.last_sample = sample
        self.sample_count += 1
        return sample

    def send_stage(self, message):
        if self.interrupted():
            return
        self.touched = True  # A timeout can follow a successful motor write.
        with self.lock:
            speed = self.speed
        self.hand.move_all(self.planner.targets, speed, self.planner.weights)
        self.sent_speed, self.last_send = speed, time.monotonic()
        self.emit("motion", message=message, speed=speed,
                  view=self.planner.view(self.last_sample["positions"]))

    def halt(self, explicit=False):
        with self.lock:
            self.pending_intent = None
        if self.planner:
            self.planner.cancel()
        if self.hand and (self.touched or explicit):
            self.hand.stop_all()
            self.touched = False
        self.sent_speed = None

    def close_hand(self):
        try:
            self.halt()
        except Exception as exc:
            self.emit("error", message=f"停止未获确认：{exc}；必要时切断手部电源")
        finally:
            if self.hand:
                try:
                    self.hand.close()
                except Exception as exc:
                    self.emit("error", message=f"关闭 USB：{exc}")
            self.hand = self.planner = None
            self.touched = False
            self.emit("disconnected")

    def connect_hand(self):
        if self.hand:
            return
        self.hand = self.factory("left")
        self.planner = GesturePlanner(self.hand.limits, self.hand.info["serial"])
        self.set_speed(min(self.speed, min(self.hand.limits["speed"])))
        self.read()
        self.emit("connected", info=self.hand.info, limits=self.hand.limits)
        self.emit("sample", sample=self.last_sample, view=self.planner.view(self.last_sample["positions"]))

    def tick(self):
        if self.hand and self.touched and time.monotonic()-self.heartbeat > 0.8:
            raise RuntimeError("界面响应中断")
        with self.lock:
            intent, self.pending_intent = self.pending_intent, None
        if intent and self.hand and not self.interrupted() and intent != self.planner.intent:
            # Cancel previous destinations before resolving 'hold current position'.
            if self.touched:
                self.hand.stop_all()
            sample = self.read()
            self.planner.begin(intent, sample["positions"])
            self.send_stage(f"{LABELS[intent]} · 第 1 步")
        if self.hand and self.planner.active and self.speed != self.sent_speed and time.monotonic()-self.last_send >= .08:
            self.send_stage("运动速度已更新")
        if self.hand and time.monotonic()-self.last_read >= .05:
            sample = self.read()
            result = None if self.interrupted() else self.planner.observe(sample)
            if result == "done":
                self.emit("done", message=f"{LABELS[self.planner.intent]}已到位", view=self.planner.view(sample["positions"]))
            elif result is not None:
                self.send_stage(f"{LABELS[self.planner.intent]} · 第 {self.planner.index+1} 步")
            self.emit("sample", sample=sample, view=self.planner.view(sample["positions"]))

    def run(self):
        try:
            while not self.quit_event.is_set():
                try:
                    if self.disconnect_event.is_set():
                        self.connect_event.clear()
                        self.close_hand()
                        self.disconnect_event.clear()
                    if self.stop_event.is_set():
                        self.connect_event.clear()
                        self.halt(explicit=True)
                        self.stop_event.clear()
                        self.emit("stopped", message="已停止；点击张开或握合可继续")
                    if self.connect_event.is_set():
                        self.connect_event.clear()
                        self.connect_hand()
                    self.tick()
                except Exception as exc:
                    self.emit("error", message=str(exc))
                    self.close_hand()
                    self.stop_event.clear()
                    self.disconnect_event.clear()
                time.sleep(.005)
        finally:
            self.close_hand()
            self.emit("closed")
