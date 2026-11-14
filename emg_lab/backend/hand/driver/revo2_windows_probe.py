"""Read-only Revo2 probe over the DM-USB2FDCAN gs_usb WinUSB interface.

Default: USB descriptors/capabilities only. --probe-readonly opens CAN FD at
1M/5M and sends only Modbus register READ requests. No motor/config writes,
no firmware/driver changes. The selected CAN channel is stopped on exit.

Protocol references:
  Linux drivers/net/can/usb/gs_usb.c (USB ABI)
  F:/teleop/brainco_bridge/crates/revo2-proto/src/lib.rs (Revo2 frames)
Dependencies: pyusb==1.3.1, libusb-package==1.0.30.0
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import time

import libusb_package
import usb.core
import usb.util

VID, PID = 0x1D50, 0x606F
FD, BRS, EFF, ERR = 2, 4, 0x80000000, 0x20000000
DLC_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)
READS = {(3, 901, 1), (3, 937, 1), (3, 1002, 2),
         (4, 2000, 24), (4, 3000, 10), (4, 3010, 10)}


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def read_request(slave: int, function: int, register: int, count: int) -> bytes:
    if (function, register, count) not in READS or slave not in (0x7E, 0x7F):
        raise ValueError("Only the documented read-only probe requests are permitted")
    body = struct.pack(">BBHH", slave, function, register, count)
    return body + struct.pack("<H", crc16(body))


def decode_usb_packet(raw: bytes) -> dict:
    if len(raw) < 12:
        raise ValueError("Short USB frame header")
    echo, can_id, dlc, channel, flags, reserved = struct.unpack_from("<IIBBBB", raw)
    if dlc > 15 or (not flags & FD and dlc > 8):
        raise ValueError("Invalid CAN DLC")
    length = DLC_LENGTHS[dlc] if flags & FD else dlc
    if len(raw) < 12 + length:
        raise ValueError("Truncated CAN payload")
    return dict(echo=echo, can_id=can_id, channel=channel, flags=flags,
                data=raw[12:12 + length], usb_length=len(raw))


def decode_reply(frame: dict, channel: int, slave: int, function: int,
                 count: int) -> bytes | None:
    can_id = frame["can_id"]
    if (frame["echo"] != 0xFFFFFFFF or frame["channel"] != channel
            or can_id & ERR or not can_id & EFF
            or ((can_id >> 16) & 255) != slave
            or ((can_id >> 8) & 255) != 1):
        return None
    raw = frame["data"]
    size = can_id & 255
    if not 5 <= size <= len(raw):
        return None
    data = raw[:size]
    if data[0] != slave or crc16(data[:-2]) != int.from_bytes(data[-2:], "little"):
        return None
    if data[1] == function | 0x80:
        raise RuntimeError(f"Hand returned Modbus exception {data[2]}")
    if data[1] != function or data[2] != count * 2 or size != 5 + 2 * count:
        return None
    return data[3:-2]


class Damiao:
    def __init__(self, serial: str | None = None, request_format: str = "fd",
                 sample_point: str = "75"):
        devices = list(libusb_package.find(find_all=True, idVendor=VID, idProduct=PID))
        if serial:
            devices = [device for device in devices if device.serial_number == serial]
        if len(devices) != 1:
            raise RuntimeError(f"Expected exactly one matching adapter, found {len(devices)}")
        self.device = devices[0]
        self.request_flags = FD | BRS if request_format == "fd" else 0
        self.sample_point = sample_point
        self.started: set[int] = set()
        self.traffic: list[dict] = []
        self.rejected_frames = 0
        cfg = self.device.get_active_configuration()
        interface = cfg[(0, 0)]
        if usb.util.get_string(self.device, interface.iInterface) != "damiao_gscan_compat":
            raise RuntimeError("Interface 0 is not the verified Damiao gs_usb interface")
        endpoints = list(interface)
        self.ep_in = next(ep.bEndpointAddress for ep in endpoints
                          if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN)
        self.ep_out = next(ep.bEndpointAddress for ep in endpoints
                           if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        raw = bytes(self.device.ctrl_transfer(0xC1, 5, 1, 0, 12, timeout=1000))
        last_channel, sw, hw = struct.unpack("<3xBII", raw)
        self.capabilities = []
        for channel in range(last_channel + 1):
            values = struct.unpack("<10I", self.device.ctrl_transfer(0xC1, 4, channel, 0, 40, timeout=1000))
            self.capabilities.append(values)
        self.info = dict(product=self.device.product, serial=self.device.serial_number,
                         vid_pid="1d50:606f", channels=last_channel + 1,
                         usb_protocol_sw=sw, usb_protocol_hw=hw,
                         endpoint_in=hex(self.ep_in), endpoint_out=hex(self.ep_out),
                         capabilities=self.capabilities)

    def control_out(self, request: int, value: int, payload: bytes):
        # These USB requests configure the adapter only, not the hand.
        if request not in (0, 1, 2, 10):
            raise ValueError("Unsupported adapter operation")
        self.device.ctrl_transfer(0x41, request, value, 0, payload, timeout=1000)

    def start(self, channel: int):
        caps = self.capabilities[channel]
        if not caps[0] & (1 << 8) or caps[1] != 80_000_000:
            raise RuntimeError("This probe requires the verified FD-capable 80 MHz adapter")
        self.control_out(0, 1, struct.pack("<I", 0xBEEF))
        self.control_out(2, channel, struct.pack("<II", 0, 0))
        # All choices yield 1 Mbps with the measured 80 MHz CAN clock.
        nominal = {"75": (1, 13, 5, 4, 4), "80": (1, 14, 4, 4, 4),
                   "87.5": (1, 12, 2, 1, 5)}[self.sample_point]
        self.control_out(1, channel, struct.pack("<5I", *nominal))
        # 80 MHz / (1 * 16) = 5 Mbps; 81.25% sample point.
        self.control_out(10, channel, struct.pack("<5I", 1, 11, 3, 3, 1))
        flags = (1 << 8) | (caps[0] & (1 << 3))  # FD + one-shot if supported
        self.started.add(channel)
        self.control_out(2, channel, struct.pack("<II", 1, flags))
        time.sleep(0.05)

    def stop(self, channel: int):
        if channel in self.started:
            self.control_out(2, channel, struct.pack("<II", 0, 0))
            self.started.remove(channel)

    def read_registers(self, channel: int, slave: int, function: int,
                       register: int, count: int, timeout: float = 0.3) -> bytes:
        data = read_request(slave, function, register, count)
        can_id = EFF | slave << 16 | 1 << 8 | len(data)
        # FD-mode gs_usb TX has a fixed 64-byte data area, even for an 8-byte request.
        packet = struct.pack("<IIBBBB", 0, can_id, len(data), channel, self.request_flags, 0)
        packet += data.ljust(64, b"\0")
        self.traffic.append(dict(direction="tx", channel=channel, can_id=hex(can_id),
                                 payload=data.hex(), function=function, register=register))
        self.device.write(self.ep_out, packet, timeout=500)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = bytes(self.device.read(self.ep_in, 512, timeout=50))
            except usb.core.USBTimeoutError:
                continue
            self.traffic.append(dict(direction="rx_usb", raw=raw.hex()))
            try:
                frame = decode_usb_packet(raw)
            except ValueError:
                self.rejected_frames += 1
                continue
            result = decode_reply(frame, channel, slave, function, count)
            if result is not None:
                return result
            self.rejected_frames += 1
        raise TimeoutError(f"No valid response: channel={channel}, slave={slave:#x}, register={register}")

    def close(self):
        try:
            for channel in tuple(self.started):
                self.stop(channel)
        finally:
            usb.util.dispose_resources(self.device)


def motor_status(data: bytes) -> dict:
    if len(data) != 48:
        raise ValueError("Motor status must contain 24 registers")
    return dict(positions=list(struct.unpack(">6H", data[:12])),
                speeds=list(struct.unpack(">6h", data[12:24])),
                currents_mA=list(struct.unpack(">6h", data[24:36])),
                motor_states=list(struct.unpack(">6H", data[36:48])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-readonly", action="store_true")
    parser.add_argument("--serial")
    parser.add_argument("--channel", choices=("all", "0", "1"), default="all")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--request-format", choices=("fd", "classic"), default="fd")
    parser.add_argument("--sample-point", choices=("75", "80", "87.5"), default="75")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 1 <= args.samples <= 200:
        parser.error("--samples must be between 1 and 200")
    report = dict(time_utc=datetime.now(timezone.utc).isoformat(),
                  read_only_hand=True, request_format=args.request_format,
                  nominal_sample_point=args.sample_point, hands=[], errors=[])
    adapter = None
    try:
        adapter = Damiao(args.serial, args.request_format, args.sample_point)
        report["adapter"] = adapter.info
        print(json.dumps(adapter.info, ensure_ascii=False), flush=True)
        if args.probe_readonly:
            channels = range(len(adapter.capabilities)) if args.channel == "all" else [int(args.channel)]
            for channel in channels:
                try:
                    adapter.start(channel)
                    for slave in (0x7E, 0x7F):
                        try:
                            identity = adapter.read_registers(channel, slave, 3, 901, 1)
                        except TimeoutError as exc:
                            print(str(exc), flush=True)
                            continue
                        identity = int.from_bytes(identity, "big")
                        hand = dict(channel=channel, slave=hex(slave), identity=identity,
                                    side={1: "right", 2: "left"}.get(identity, "unknown"), samples=[])
                        report["hands"].append(hand)
                        print("FOUND " + json.dumps(hand), flush=True)
                        unit = adapter.read_registers(channel, slave, 3, 937, 1)
                        hand["unit_mode"] = int.from_bytes(unit, "big")
                        settings = adapter.read_registers(channel, slave, 3, 1002, 2)
                        hand["canfd_baudrate_code"], hand["nominal_sample_point_code"] = struct.unpack(">2H", settings)
                        for key, register in (("firmware", 3000), ("serial", 3010)):
                            data = adapter.read_registers(channel, slave, 4, register, 10)
                            hand[key] = data.rstrip(b"\0").decode("ascii", errors="replace")
                        print("HAND " + json.dumps({k: v for k, v in hand.items() if k != "samples"}), flush=True)
                        for _ in range(args.samples):
                            started = time.monotonic()
                            raw = adapter.read_registers(channel, slave, 4, 2000, 24)
                            sample = motor_status(raw)
                            sample["round_trip_ms"] = round((time.monotonic() - started) * 1000, 3)
                            hand["samples"].append(sample)
                            print("STATUS " + json.dumps(sample), flush=True)
                            time.sleep(0.05)
                finally:
                    adapter.stop(channel)
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        print(report["errors"][-1], flush=True)
    finally:
        if adapter:
            report["traffic"] = adapter.traffic
            report["ignored_frames"] = adapter.rejected_frames
            try:
                adapter.close()
            except Exception as exc:
                report["errors"].append(f"Cleanup: {exc}")
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["errors"]:
        return 1
    return 2 if args.probe_readonly and not report["hands"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
