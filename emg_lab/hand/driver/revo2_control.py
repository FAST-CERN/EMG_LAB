"""Revo2 calibration backend. USB I/O is owned by one worker thread.

Protocol: https://www.brainco-hz.com/docs/revolimb-hand/revo2/modbus_foundation.html
Only normalized position/speed (1055) and zero velocity (1058) are written.
No persistent hand configuration, built-in gestures, PWM or current commands.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import struct
import threading
import time

from .revo2_windows_probe import Damiao, crc16, decode_usb_packet, motor_status, EFF, ERR, FD, BRS
import usb.core

ADAPTER_SERIAL = "21108DD0DA8E090B800000008888AD8D"
HANDS = {
    "left": dict(label="左手", channel=0, slave=0x7E, identity=2, serial="BCXTL2206J260000D"),
    "right": dict(label="右手", channel=1, slave=0x7F, identity=1, serial="BCXTR2206J2600002"),
}
AXES = ("thumb_flex", "thumb_aux", "index", "middle", "ring", "little")
AXIS_LABELS = ("拇指尖部 FLEX", "拇指根部 AUX", "食指", "中指", "无名指", "小指")
STATE_LABELS = {0: "静止", 1: "运动", 2: "堵转", 3: "Turbo"}
MIN_SPEED, MAX_SPEED = 1, 1000  # Manufacturer's normalized position/speed command range.


def position_words(finger, target, speed):
    if type(finger) is not int or not 0 <= finger <= 5:
        raise ValueError("驱动编号应为 0–5")
    if type(target) is not int or not 0 <= target <= 1000:
        raise ValueError("目标位置应为 0–1000 的整数")
    if type(speed) is not int or not MIN_SPEED <= speed <= MAX_SPEED:
        raise ValueError(f"速度应为 {MIN_SPEED}–{MAX_SPEED}")
    return finger, target, speed


def write_packet(channel, slave, register, words):
    if register == 1055:
        position_words(*words)
    elif register == 1058:
        if len(words) != 2 or type(words[0]) is not int or not 0 <= words[0] <= 5 or words[1] != 0:
            raise ValueError("速度命令仅允许指定驱动停止")
    else:
        raise ValueError("禁止写入此寄存器")
    body = struct.pack(">BBHHB", slave, 0x10, register, len(words), 2 * len(words))
    body += struct.pack(">" + "H" * len(words), *words)
    data = body + struct.pack("<H", crc16(body))
    can_id = EFF | slave << 16 | 1 << 8 | len(data)
    return struct.pack("<IIBBBB", 0, can_id, 10, channel, FD | BRS, 0) + data.ljust(64, b"\0")


def valid_ack(frame, channel, slave, register, count):
    can_id = frame["can_id"]
    if (frame["echo"] != 0xFFFFFFFF or frame["channel"] != channel
            or can_id & ERR or not can_id & EFF
            or ((can_id >> 16) & 255) != slave or ((can_id >> 8) & 255) != 1):
        return False
    length = can_id & 255
    data = frame["data"][:length]
    if length not in (5, 8) or len(data) != length or data[0] != slave:
        return False
    if crc16(data[:-2]) != int.from_bytes(data[-2:], "little"):
        return False
    if data[1] == 0x90:
        raise RuntimeError(f"灵巧手拒绝指令：Modbus 异常 {data[2]}")
    return data[:-2] == struct.pack(">BBHH", slave, 0x10, register, count)


class UsbHand:
    def __init__(self, side):
        self.spec = HANDS[side]
        self.adapter = Damiao(ADAPTER_SERIAL, sample_point="75")
        try:
            self.adapter.start(self.spec["channel"])
            identity = int.from_bytes(self.read(3, 901, 1), "big")
            serial = self.read(4, 3010, 10).rstrip(b"\0").decode("ascii")
            unit = int.from_bytes(self.read(3, 937, 1), "big")
            if (identity, serial, unit) != (self.spec["identity"], self.spec["serial"], 0):
                raise RuntimeError("手型、序列号或单位模式与已验证设备不符；未启用控制")
            self.info = dict(side=side, serial=serial, channel=self.spec["channel"], unit_mode=unit,
                             firmware=self.read(4, 3000, 10).rstrip(b"\0").decode("ascii"))
        except BaseException:
            self.adapter.close()
            raise

    def read(self, function, register, count):
        # Keep probe traffic bounded during a long GUI session.
        if len(self.adapter.traffic) > 300:
            del self.adapter.traffic[:-100]
        return self.adapter.read_registers(self.spec["channel"], self.spec["slave"],
                                           function, register, count, timeout=0.18)

    def status(self):
        raw = motor_status(self.read(4, 2000, 24))
        # With unit_mode=0 these are raw normalized readbacks, not calibrated force.
        raw["currents_raw"] = raw.pop("currents_mA")
        return raw

    def write(self, register, words):
        channel, slave = self.spec["channel"], self.spec["slave"]
        packet = write_packet(channel, slave, register, words)
        self.adapter.device.write(self.adapter.ep_out, packet, timeout=250)
        deadline = time.monotonic() + 0.22
        while time.monotonic() < deadline:
            try:
                raw = bytes(self.adapter.device.read(self.adapter.ep_in, 512, timeout=25))
            except usb.core.USBTimeoutError:
                continue
            try:
                frame = decode_usb_packet(raw)
            except ValueError:
                continue
            if valid_ack(frame, channel, slave, register, len(words)):
                return
        # A write is never retried: lost ACK does not mean no motion.
        raise TimeoutError("未收到控制确认；指令可能已到达，已进入停止流程")

    def move(self, finger, target, speed):
        self.write(1055, position_words(finger, target, speed))

    def stop(self, finger):
        self.write(1058, (finger, 0))

    def close(self):
        self.adapter.close()


class SimHand:
    """Deterministic GUI/testing backend; never constructs a USB adapter."""
    def __init__(self, side):
        self.info = dict(side=side, serial="SIMULATED-" + side, channel=HANDS[side]["channel"],
                         unit_mode=0, firmware="simulation")
        self.positions = [400.0, 400.0, 50.0, 50.0, 50.0, 50.0]
        self.targets = self.positions.copy()
        self.speed = [100] * 6
        self.last = time.monotonic()
        self.writes = []

    def status(self):
        now = time.monotonic()
        dt, self.last = min(now - self.last, 0.1), now
        speeds, states = [], []
        for i in range(6):
            delta = self.targets[i] - self.positions[i]
            step = min(abs(delta), self.speed[i] * 2 * dt)
            self.positions[i] += step if delta > 0 else -step
            moving = abs(self.targets[i] - self.positions[i]) > 0.5
            speeds.append((self.speed[i] if delta > 0 else -self.speed[i]) if moving else 0)
            states.append(1 if moving else 0)
        return dict(positions=[round(p) for p in self.positions], speeds=speeds,
                    currents_raw=[65 if s else 0 for s in states], motor_states=states)

    def move(self, finger, target, speed):
        position_words(finger, target, speed)
        self.writes.append((finger, target, speed))
        self.targets[finger], self.speed[finger] = target, speed

    def stop(self, finger):
        self.writes.append((finger, None, 0))
        self.targets[finger] = self.positions[finger]

    def close(self):
        pass


class PoseStore:
    def __init__(self, path):
        self.path = Path(path)
        self.data = dict(schema_version=1, unit_mode="normalized", axis_order=list(AXES), hands={})
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (value.get("schema_version") != 1 or value.get("axis_order") != list(AXES)
                    or value.get("unit_mode") != "normalized" or not isinstance(value.get("hands"), dict)):
                raise ValueError("姿态文件版本、单位或驱动顺序不符")
            for side, hand in value["hands"].items():
                if (side not in HANDS or not isinstance(hand, dict) or not isinstance(hand.get("serial"), str)
                        or not isinstance(hand.get("poses"), dict)):
                    raise ValueError("姿态文件的设备信息不完整")
                for key, pose in hand["poses"].items():
                    if (key not in ("open", "grasp") or not isinstance(pose, dict)
                            or not isinstance(pose.get("positions"), list) or len(pose["positions"]) != 6
                            or not isinstance(pose.get("label"), str) or "speed" not in pose):
                        raise ValueError("姿态文件的目标参数不完整")
                    for i, target in enumerate(pose["positions"]):
                        position_words(i, target, pose["speed"])
            self.data = value

    def save(self, side, serial, key, positions, speed):
        if side not in HANDS or key not in ("open", "grasp") or len(positions) != 6:
            raise ValueError("姿态信息不完整")
        for i, value in enumerate(positions):
            position_words(i, value, speed)
        previous = self.data["hands"].get(side)
        if previous and previous["serial"] != serial:
            raise ValueError("姿态文件属于另一只手，拒绝覆盖")
        # Build a copy so an unsuccessful disk write does not change in-memory state.
        updated = json.loads(json.dumps(self.data))
        hand = updated["hands"].setdefault(side, dict(serial=serial, channel=HANDS[side]["channel"], poses={}))
        hand["poses"][key] = dict(label="张开" if key == "open" else "轻握",
            positions=list(positions), speed=speed, source="settled_readback",
            recorded_at=datetime.now(timezone.utc).isoformat())
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        self.data = updated

    def load(self, side, serial, key):
        hand = self.data["hands"].get(side)
        if not hand or hand["serial"] != serial or key not in hand["poses"]:
            raise ValueError("当前设备尚未记录这组姿态")
        pose = hand["poses"][key]
        if len(pose["positions"]) != 6:
            raise ValueError("姿态文件位置数目错误")
        for i, value in enumerate(pose["positions"]):
            position_words(i, value, pose["speed"])
        return pose


class Controller(threading.Thread):
    """Serialized I/O with latest-target coalescing and priority STOP.

    Dragging overwrites unsent targets per axis, including during motion.
    No step/current/travel-time heuristics stop otherwise valid commands.
    UI heartbeat is required while armed. Shutdown/STOP clears pending targets.
    An interrupted command cannot execute later on a reconnect or re-arm.
    """
    def __init__(self, factory=UsbHand):
        super().__init__(name="revo2-usb", daemon=True)
        self.factory = factory
        self.requests = queue.Queue(maxsize=8)
        self.target_lock = threading.Lock()
        self.latest_targets = {}
        self.last_send = 0.0
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.disconnect_event = threading.Event()
        self.quit_event = threading.Event()
        self.heartbeat = time.monotonic()
        self.hand = None
        self.armed = False
        self.active = {}
        self.controlled = set()
        self.history = deque(maxlen=3)
        self.last_sample = None
        self.last_read = 0.0
        self.faulted = False

    def emit(self, kind, **data):
        self.events.put(dict(kind=kind, **data))

    def submit(self, action, **data):
        if action == "move":
            finger, target, speed = position_words(data["finger"], data["target"], data["speed"])
            with self.target_lock:
                if (not self.armed or self.stop_event.is_set() or self.disconnect_event.is_set()
                        or self.quit_event.is_set()):
                    raise ValueError("控制未启用或已停止")
                self.latest_targets[finger] = dict(finger=finger, target=target, speed=speed)
        else:
            self.requests.put_nowait((action, data))

    def take_latest_target(self):
        with self.target_lock:
            if not self.latest_targets:
                return None
            finger = next(iter(self.latest_targets))
            return self.latest_targets.pop(finger)

    def heartbeat_tick(self):
        self.heartbeat = time.monotonic()

    def clear_requests(self):
        with self.target_lock:
            self.latest_targets.clear()
        while True:
            try:
                self.requests.get_nowait()
            except queue.Empty:
                return

    def sample(self):
        sample = self.hand.status()
        for name in ("positions", "speeds", "currents_raw", "motor_states"):
            if len(sample[name]) != 6:
                raise ValueError("不完整的状态回读")
        if any(not 0 <= p <= 1000 for p in sample["positions"]):
            raise ValueError("位置回读超出归一化范围")
        self.last_read = time.monotonic()
        sample["received_at"] = self.last_read
        self.last_sample = sample
        self.history.append(sample)
        self.emit("sample", sample=sample)
        return sample

    def ensure_idle(self, sample):
        if any(sample["motor_states"]) or any(abs(s) > 5 for s in sample["speeds"]):
            raise ValueError("请等待所有驱动静止后操作")

    def settled(self):
        with self.target_lock:
            if self.latest_targets:
                return False
        if not self.hand or self.active or len(self.history) < 3 or time.monotonic() - self.last_read > 0.3:
            return False
        try:
            for sample in self.history:
                self.ensure_idle(sample)
        except ValueError:
            return False
        return all(max(s["positions"][i] for s in self.history) - min(s["positions"][i] for s in self.history) <= 3
                   for i in range(6))

    def halt(self, reason, all_axes=False):
        self.armed = False
        self.clear_requests()
        failed = []
        axes = list(range(6)) if all_axes and self.hand else sorted(self.controlled)
        for finger in axes:
            try:
                self.hand.stop(finger)
            except Exception as exc:
                failed.append(f"{AXIS_LABELS[finger]}: {exc}")
        self.controlled = set() if not failed else set(axes)
        self.active.clear()
        self.history.clear()
        if failed:
            self.faulted = True
            reason += "；停止未获确认，请切断手部电源。" + " / ".join(failed)
        self.emit("mode", armed=False, moving=False, faulted=self.faulted, message=reason)

    def close_hand(self):
        if self.hand:
            # Even settled position control may keep holding; explicitly stop touched axes.
            if self.controlled:
                self.halt("停止已控制驱动并断开")
            try:
                self.hand.close()
            except Exception as exc:
                self.emit("error", message=f"USB 关闭失败：{exc}")
        self.hand = None
        self.armed = False
        self.active.clear()
        self.controlled.clear()
        self.history.clear()
        self.clear_requests()
        self.emit("disconnected")

    def handle(self, action, data):
        if action == "connect":
            if self.hand:
                raise ValueError("请先断开当前设备")
            self.hand = self.factory(data["side"])
            self.faulted = False
            self.sample()
            self.emit("connected", info=self.hand.info)
            return
        if not self.hand:
            raise ValueError("请先连接设备")
        if action == "arm":
            if self.faulted:
                raise ValueError("故障已锁定，请排查后断开重连")
            self.sample()
            self.armed = True
            self.emit("mode", armed=True, moving=bool(self.active), faulted=False,
                      message="直接控制已启用：拖动滑块即更新目标位置")
        elif action == "move":
            if not self.armed or self.faulted or self.stop_event.is_set() or self.disconnect_event.is_set():
                raise ValueError("控制未启用或已停止")
            finger, target, speed = position_words(data["finger"], data["target"], data["speed"])
            if self.stop_event.is_set() or self.disconnect_event.is_set() or self.quit_event.is_set():
                return
            previous = self.active.get(finger)
            if previous and (previous["target"], previous["speed"]) == (target, speed):
                return
            self.controlled.add(finger)  # Must be set BEFORE a potentially successful write.
            self.active[finger] = dict(target=target, speed=speed, settled=0)
            self.hand.move(finger, target, speed)
            self.last_send = time.monotonic()
            self.emit("target_sent", finger=finger, target=target, speed=speed,
                      message=f"{AXIS_LABELS[finger]}：目标 {target}，速度 {speed}")
        elif action == "capture":
            self.sample()
            if self.faulted or not self.settled():
                raise ValueError("姿态未稳定或存在故障，暂不能保存")
            self.emit("captured", key=data["key"], speed=data["speed"],
                      positions=list(self.last_sample["positions"]), info=dict(self.hand.info))
        else:
            raise ValueError("未知操作")

    def monitor(self, sample):
        if not self.armed:
            return
        # These comparisons only label arrival. They never prevent a new target.
        for finger, active in list(self.active.items()):
            position = sample["positions"][finger]
            reached = (abs(position - active["target"]) <= 5
                       and abs(sample["speeds"][finger]) <= 5 and sample["motor_states"][finger] == 0)
            active["settled"] = active["settled"] + 1 if reached else 0
            if active["settled"] >= 3:
                del self.active[finger]
                self.emit("arrived", finger=finger, position=position, moving=bool(self.active),
                          message=f"{AXIS_LABELS[finger]} 已到位：{position}")

    def run(self):
        try:
            while not self.quit_event.is_set():
                if self.disconnect_event.is_set():
                    self.close_hand()
                    self.disconnect_event.clear()
                if self.stop_event.is_set():
                    self.halt("停止指令已确认；重新启用后才能继续", all_axes=True)
                    self.stop_event.clear()
                try:
                    if self.armed and time.monotonic() - self.heartbeat > 0.6:
                        raise RuntimeError("界面心跳中断")
                    try:
                        action, data = self.requests.get_nowait()
                    except queue.Empty:
                        action = None
                    if action:
                        try:
                            self.handle(action, data)
                        except ValueError as exc:
                            self.emit("rejected", message=str(exc))
                    # At most one write every 50 ms; intermediate drag events are replaced,
                    # not queued. The final release target is preserved until transmitted.
                    if self.hand and self.armed and time.monotonic() - self.last_send >= 0.05:
                        target = self.take_latest_target()
                        if target:
                            try:
                                self.handle("move", target)
                            except ValueError as exc:
                                self.emit("rejected", message=str(exc))
                    if self.hand and time.monotonic() - self.last_read >= 0.05:
                        self.monitor(self.sample())
                except Exception as exc:
                    self.faulted = True
                    self.halt(f"故障：{exc}")
                    self.emit("error", message=str(exc))
                    self.close_hand()
                time.sleep(0.005)
        finally:
            self.close_hand()
            self.emit("closed")
