from __future__ import annotations

"""Delsys Trigno EMG backend.

This module wraps the Delsys AeroPy API behind the same small runtime contract used
by the existing EMG device abstraction: connect, configure, start, stop, disconnect,
and publish EMG frames to ``EMG_DATA_TOPIC``.

The Delsys demo includes a full PySide/Vispy application. This integration keeps the
SDK calls but removes demo UI dependencies so the upper application can control
pairing, scanning, and streaming from its own hardware configuration page.
"""

import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Optional

import numpy as np

try:
    from utils.bus.bus_data import BusData
    from utils.bus.event_bus import EventBus
    from resource.hardware.topics import EMG_DATA_TOPIC
except Exception:  # pragma: no cover - allows importing in isolated SDK tests
    BusData = None  # type: ignore
    EventBus = None  # type: ignore
    EMG_DATA_TOPIC = "emg.data"


DELSYS_KEY = os.environ.get('DELSYS_KEY', "")

DELSYS_LICENSE = os.environ.get('DELSYS_LICENSE', "")


class DelsysStationType(Enum):
    UNKNOWN = "Unknown"
    LITE = "Trigno Lite"
    CENTRO = "Trigno Centro"
    BASESTATION = "Trigno Base Station"


@dataclass
class DelsysChannel:
    name: str
    enabled: bool
    channel_type: str
    sample_rate: float
    guid: str
    unit: str = ""

    @property
    def normalized_type(self) -> str:
        return _normalize_delsys_channel_type(self.channel_type)

    @property
    def axis(self) -> str:
        return _axis_from_channel_name(self.name)


@dataclass
class DelsysSensor:
    index: int
    name: str
    pair_number: int
    mode: str
    channels: list[DelsysChannel] = field(default_factory=list)

    @property
    def emg_channels(self) -> list[DelsysChannel]:
        return [
            channel
            for channel in self.channels
            if channel.enabled and channel.normalized_type == "EMG"
        ]

    @property
    def imu_channels(self) -> list[DelsysChannel]:
        return [
            channel
            for channel in self.channels
            if channel.enabled and channel.normalized_type in {"ACC", "GYRO"}
        ]


@dataclass
class DelsysIMUChannelRecord:
    pair_number: int
    sensor_name: str
    channel_name: str
    channel_type: str
    axis: str
    sample_rate: float
    guid: str
    unit: str = ""


ParsedCallback = Callable[[dict[str, Any]], None]


_SDK_LOADED = False
_SDK_LOAD_ERROR: Optional[Exception] = None
_AEROPY_FACTORY: Optional[Callable[[], Any]] = None


def _sdk_resource_dir() -> Path:
    return Path(__file__).resolve().parent / "resources"


def _sdk_runtime_config_path() -> Path:
    return Path(__file__).resolve().parent / "delsys.runtimeconfig.json"


def _unblock_sdk_resources(resources_dir: Path) -> None:
    """Remove Windows Mark-of-the-Web streams from SDK files when present.

    Delsys DLLs copied from a downloaded ZIP may carry a Zone.Identifier alternate
    data stream. pythonnet/.NET then rejects AddReference with HRESULT 0x80131515.
    Removing the stream is equivalent to PowerShell's Unblock-File.
    """
    if os.name != "nt":
        return
    try:
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            (
                "Get-ChildItem -LiteralPath $args[0] -File | "
                "ForEach-Object { Remove-Item -LiteralPath $_.FullName "
                "-Stream Zone.Identifier -ErrorAction SilentlyContinue }"
            ),
            str(resources_dir),
        ]
        subprocess.run(command, check=False, capture_output=True, timeout=10)
    except Exception:
        pass


def _find_aeropy_type() -> Any:
    import System  # type: ignore

    for assembly in System.AppDomain.CurrentDomain.GetAssemblies():
        with suppress(Exception):
            aero_type = assembly.GetType("Aero.AeroPy")
            if aero_type is not None:
                return aero_type
    raise ModuleNotFoundError("No module named 'Aero' and Aero.AeroPy type was not found")


def _create_aeropy_from_reflection() -> Any:
    import System  # type: ignore

    aero_type = _find_aeropy_type()
    return System.Activator.CreateInstance(aero_type)


def _collect_dotnet_gc() -> None:
    """Ask Python and .NET to release wrapper objects before reusing the receiver."""
    with suppress(Exception):
        import gc

        gc.collect()
    with suppress(Exception):
        import System  # type: ignore

        System.GC.Collect()
        System.GC.WaitForPendingFinalizers()


def _load_coreclr_runtime() -> None:
    from pythonnet import load

    runtime_config = _sdk_runtime_config_path()
    if not runtime_config.exists():
        raise FileNotFoundError(f"Delsys runtime config not found: {runtime_config}")

    load("coreclr", runtime_config=str(runtime_config))

    import System  # type: ignore

    runtime_version = System.Environment.Version
    if int(runtime_version.Major) != 8:
        raise RuntimeError(
            "DelsysAPI.dll targets .NET 8, but the current process loaded "
            f".NET {runtime_version}. Restart the app before using Delsys, and avoid "
            "loading another pythonnet backend first."
        )


def _load_sdk() -> Any:
    """Load pythonnet and DelsysAPI once, then return an AeroPy factory."""
    global _SDK_LOADED, _SDK_LOAD_ERROR, _AEROPY_FACTORY

    if _SDK_LOAD_ERROR is not None:
        raise RuntimeError(f"Delsys SDK failed to load: {_SDK_LOAD_ERROR}") from _SDK_LOAD_ERROR
    if _AEROPY_FACTORY is not None:
        return _AEROPY_FACTORY

    try:
        resources_dir = _sdk_resource_dir()
        if not resources_dir.exists():
            raise FileNotFoundError(f"Delsys resources directory not found: {resources_dir}")

        _unblock_sdk_resources(resources_dir)
        os.environ["PATH"] = str(resources_dir) + os.pathsep + os.environ.get("PATH", "")
        if not _SDK_LOADED:
            _load_coreclr_runtime()
            import clr

            clr.AddReference(str(resources_dir / "DelsysAPI.dll"))
            clr.AddReference("System.Collections")
            clr.AddReference("System")
            _SDK_LOADED = True

        try:
            from Aero import AeroPy  # type: ignore

            _AEROPY_FACTORY = AeroPy
        except ModuleNotFoundError:
            _AEROPY_FACTORY = _create_aeropy_from_reflection
        return _AEROPY_FACTORY
    except Exception as exc:
        _SDK_LOAD_ERROR = exc
        raise


def _station_type_from_text(text: str) -> DelsysStationType:
    for station_type in DelsysStationType:
        if station_type.value == text:
            return station_type
    return DelsysStationType.UNKNOWN


def _normalize_delsys_channel_type(channel_type: Any) -> str:
    text = str(channel_type or "").strip().upper().replace(" ", "")
    text = text.replace("-", "").replace("_", "")
    if text in {"EMG"}:
        return "EMG"
    if text in {"ACC", "ACCEL", "ACCELERATION", "ACCELEROMETER"}:
        return "ACC"
    if text in {"GYRO", "GYR", "GYROSCOPE"}:
        return "GYRO"
    return text


def _axis_from_channel_name(name: Any) -> str:
    text = str(name or "").strip().upper()
    if not text:
        return ""
    tokens = [token for token in re.split(r"[^A-Z0-9]+", text) if token]
    for token in reversed(tokens):
        if token in {"X", "Y", "Z"}:
            return token.lower()
    compact = re.sub(r"[^A-Z0-9]", "", text)
    for suffix in ("X", "Y", "Z"):
        if compact.endswith(suffix):
            return suffix.lower()
    return ""


def _normalize_imu_channel_type_filter(values: Optional[list[str] | str]) -> set[str]:
    if values is None:
        return {"ACC", "GYRO"}
    if isinstance(values, str):
        values = [values]
    normalized = {
        _normalize_delsys_channel_type(value)
        for value in values
        if _normalize_delsys_channel_type(value) in {"ACC", "GYRO"}
    }
    return normalized


def _normalize_sensor_mode_map(values: Optional[dict[Any, Any]]) -> dict[int, str]:
    normalized: dict[int, str] = {}
    for raw_pair_number, raw_mode in (values or {}).items():
        try:
            pair_number = int(raw_pair_number)
        except (TypeError, ValueError):
            continue
        mode = str(raw_mode or "").strip()
        if pair_number > 0 and mode:
            normalized[pair_number] = mode
    return normalized


def _mapping_value(item: Any, *keys: str, default: Any = "") -> Any:
    for key in keys:
        try:
            return item[key]
        except Exception:
            continue
    return default


def _as_task_result(value: Any) -> Any:
    """Resolve .NET Task-like objects while tolerating synchronous return values."""
    return getattr(value, "Result", value)


def _is_no_rf_error(text: Any) -> bool:
    message = str(text).lower()
    return (
        "no rf subsystem found" in message
        or "failed to initalize rf data source" in message
        or "failed to initialize rf data source" in message
        or "centros detected: 0" in message
    )


def _print_no_rf_hint() -> None:
    print(
        "[Delsys] No RF subsystem was detected. Close other Delsys processes, "
        "replug or power-cycle the Trigno receiver, then retry."
    )


def _pair_sensor_in_current_process(
    pair_number: int,
    timeout_s: float,
    *,
    key: str = DELSYS_KEY,
    license_text: str = DELSYS_LICENSE,
) -> bool:
    """Pair once using the same sequence as the vendor demo."""
    pair_number = int(pair_number)
    if pair_number <= 0:
        raise ValueError("Delsys pair number must be positive")

    base = None
    try:
        AeroPy = _load_sdk()
        base = AeroPy()
        base.ValidateBase(key, license_text)
        return _pair_sensor_on_base(base, pair_number, timeout_s)
    except Exception as exc:
        print(f"[Delsys] Pair failed: {exc}")
        if base is not None:
            with suppress(Exception):
                base.CancelPair()
        return False
    finally:
        base = None
        _collect_dotnet_gc()


def _pair_sensor_on_base(base: Any, pair_number: int, timeout_s: float) -> bool:
    """Pair on an already validated AeroPy instance."""
    pair_number = int(pair_number)
    if pair_number <= 0:
        raise ValueError("Delsys pair number must be positive")

    try:
        pair_errors: list[Exception] = []

        def _pair_target() -> None:
            try:
                base.PairSensor(pair_number)
            except Exception as exc:
                pair_errors.append(exc)

        pair_thread = Thread(target=_pair_target, name="DelsysPairSensor", daemon=True)
        pair_thread.start()

        deadline = time.monotonic() + max(1.0, float(timeout_s))
        time.sleep(1.0)
        while time.monotonic() < deadline:
            if pair_errors:
                raise pair_errors[0]
            if not bool(base.CheckPairStatus()):
                pair_thread.join(timeout=1.0)
                return True
            time.sleep(0.2)

        with suppress(Exception):
            base.CancelPair()
        pair_thread.join(timeout=1.0)
        return False
    except Exception as exc:
        print(f"[Delsys] Pair failed: {exc}")
        with suppress(Exception):
            base.CancelPair()
        return False


def _pair_sensor_in_subprocess(pair_number: int, timeout_s: float) -> bool:
    """Run pairing in a child process because CLR fatal errors bypass Python exceptions."""
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "vendor.delsys.delsys_emg",
        "--pair",
        str(int(pair_number)),
        "--timeout",
        str(float(timeout_s)),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            command,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(15.0, float(timeout_s) + 8.0),
        )
    except subprocess.TimeoutExpired:
        print("[Delsys] Pair subprocess timed out.")
        return False

    if result.returncode == 0:
        return True

    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part and part.strip())
    if output:
        print(f"[Delsys] Pair subprocess failed(returncode={result.returncode}):\n{output}")
    else:
        print(f"[Delsys] Pair subprocess failed(returncode={result.returncode}).")
    if _is_no_rf_error(output):
        _print_no_rf_hint()
    return False


class DelsysEMGCore:
    """Core controller for Delsys Trigno EMG acquisition."""

    def __init__(
        self,
        *,
        sensors: Optional[list[int]] = None,
        ports_config: Optional[dict[str, int]] = None,
        enable_bus: bool = True,
        on_frame: Optional[ParsedCallback] = None,
        on_error: Optional[Callable[[str], None]] = None,
        stream_yt_data: bool = False,
        delsys_imu_enabled: bool = False,
        delsys_imu_channel_types: Optional[list[str]] = None,
        sensor_modes: Optional[dict[Any, Any]] = None,
        poll_interval_s: float = 0.002,
        key: str = DELSYS_KEY,
        license_text: str = DELSYS_LICENSE,
    ) -> None:
        self.sensors = sorted({int(sensor) for sensor in sensors or [] if int(sensor) > 0})
        self.ports_config = dict(ports_config or {})
        self.enable_bus = bool(enable_bus)
        self._on_frame = on_frame
        self._on_error = on_error
        self.stream_yt_data = bool(stream_yt_data)
        self.delsys_imu_enabled = bool(delsys_imu_enabled)
        self.delsys_imu_channel_types = _normalize_imu_channel_type_filter(
            delsys_imu_channel_types
        )
        self.sensor_modes = _normalize_sensor_mode_map(sensor_modes)
        self.poll_interval_s = max(0.001, float(poll_interval_s))
        self.key = key
        self.license_text = license_text

        self._base: Any = None
        self.station_type = DelsysStationType.UNKNOWN
        self.scanned_sensors: list[DelsysSensor] = []
        self._selected_sensors: list[DelsysSensor] = []
        self._emg_channel_guids: list[str] = []
        self._emg_channel_sample_rates: list[float] = []
        self._imu_channel_records: list[DelsysIMUChannelRecord] = []
        self._running = False
        self._poll_thread: Optional[Thread] = None
        self._on_sensor_offline: Optional[Callable[[], None]] = None
        self._last_data_time = 0.0
        self._offline_timeout_s = 2.0
        self._detect_offline_on_no_data = False
        self.last_error = ""
        self._last_stop_time = 0.0
        self._yt_host_time_offset_s: Optional[float] = None
        self._raw_imu_last_timestamps: dict[str, float] = {}

    # -------------------- lifecycle --------------------
    def _open_base(self) -> bool:
        """Validate the receiver without scanning sensors."""
        if self._base is not None:
            try:
                self.station_type = _station_type_from_text(str(self._base.GetTrignoReceiverType()))
                if self.station_type == DelsysStationType.UNKNOWN:
                    self.last_error = "Delsys receiver type is unknown after ValidateBase()."
                    self._base = None
                    return False
                return True
            except Exception as exc:
                self.last_error = f"Delsys receiver is no longer available: {exc}"
                print(f"[Delsys] 连接状态异常: {exc}")
                self._base = None
                self.station_type = DelsysStationType.UNKNOWN
                return False
        try:
            self.last_error = ""
            AeroPy = _load_sdk()
            self._base = AeroPy()
            self._base.ValidateBase(self.key, self.license_text)
            self.station_type = _station_type_from_text(str(self._base.GetTrignoReceiverType()))
            if self.station_type == DelsysStationType.UNKNOWN:
                self.last_error = "Delsys receiver type is unknown after ValidateBase()."
                print(f"[Delsys] 连接失败: {self.last_error}")
                self._base = None
                return False
            return True
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[Delsys] 连接失败: {exc}")
            if _is_no_rf_error(exc):
                _print_no_rf_hint()
                self.last_error = (
                    f"{exc}\n\nNo RF subsystem was detected. Close other Delsys processes, "
                    "replug or power-cycle the Trigno receiver, then retry."
                )
            self._base = None
            self.station_type = DelsysStationType.UNKNOWN
            return False

    def connect_base_only(self) -> bool:
        """Connect to the receiver only; used by the pairing/config dialog."""
        return self._open_base()

    def connect(self) -> bool:
        """Connect, scan, and select the configured Delsys sensors."""
        if not self._open_base():
            return False
        if not self._prepare_for_scan_or_pair("连接扫描"):
            return False

        sensors = self._scan_sensors_connected(select_pair_numbers=self.sensors, retry=2)
        if self.sensors:
            selected_pairs = {sensor.pair_number for sensor in self._selected_sensors}
            missing_pairs = [pair_number for pair_number in self.sensors if pair_number not in selected_pairs]
            if missing_pairs:
                self.last_error = f"连接扫描未找到已配置的 pair number: {missing_pairs}"
                print(f"[Delsys] {self.last_error}")
                return False
        if not self._validate_selected_emg_sample_rates():
            return False
        self.last_error = ""
        return bool(sensors or not self.sensors)

    def disconnect(self) -> bool:
        """Stop streaming and release local state.

        AeroPy does not expose a dedicated disconnect method in the demo. Dropping the
        instance after Stop is the safest common path.
        """
        self.stop()
        self._base = None
        self.station_type = DelsysStationType.UNKNOWN
        self.scanned_sensors.clear()
        self._selected_sensors.clear()
        self._emg_channel_guids.clear()
        self._emg_channel_sample_rates.clear()
        self._imu_channel_records.clear()
        _collect_dotnet_gc()
        return True

    def is_running(self) -> bool:
        return self._running

    # -------------------- configuration --------------------
    def configure(
        self,
        *,
        sensors: Optional[list[int]] = None,
        ports_config: Optional[dict[str, int]] = None,
        enable_bus: Optional[bool] = None,
        on_frame: Optional[ParsedCallback] = None,
        stream_yt_data: Optional[bool] = None,
        delsys_imu_enabled: Optional[bool] = None,
        delsys_imu_channel_types: Optional[list[str]] = None,
        sensor_modes: Optional[dict[Any, Any]] = None,
    ) -> bool:
        if self._running:
            print("[Delsys] 采集运行时不允许配置，请先停止。")
            return False
        if sensors is not None:
            self.sensors = sorted({int(sensor) for sensor in sensors if int(sensor) > 0})
        if ports_config is not None:
            self.ports_config = dict(ports_config or {})
        if enable_bus is not None:
            self.enable_bus = bool(enable_bus)
        if on_frame is not None:
            self._on_frame = on_frame
        if stream_yt_data is not None:
            self.stream_yt_data = bool(stream_yt_data)
        if delsys_imu_enabled is not None:
            self.delsys_imu_enabled = bool(delsys_imu_enabled)
        if delsys_imu_channel_types is not None:
            self.delsys_imu_channel_types = _normalize_imu_channel_type_filter(
                delsys_imu_channel_types
            )
        if sensor_modes is not None:
            self.sensor_modes = _normalize_sensor_mode_map(sensor_modes)
        return True

    # -------------------- pairing and scanning --------------------
    def _pair_sensor_inline_legacy(self, pair_number: int, timeout_s: float = 20.0) -> bool:
        """Pair one sensor to a given Delsys pair number."""
        if not self.connect() or self._base is None:
            return False
        pair_number = int(pair_number)
        if pair_number <= 0:
            raise ValueError("Delsys pair number must be positive")

        try:
            _as_task_result(self._base.PairSensor(pair_number))
            deadline = time.monotonic() + max(1.0, float(timeout_s))
            while time.monotonic() < deadline:
                if not bool(self._base.CheckPairStatus()):
                    return True
                time.sleep(0.2)
            with suppress(Exception):
                self._base.CancelPair()
            return False
        except Exception as exc:
            print(f"[Delsys] 配对失败: {exc}")
            with suppress(Exception):
                self._base.CancelPair()
            return False

    def pair_sensor(self, pair_number: int, timeout_s: float = 20.0, *, isolated: bool = True) -> bool:
        """Pair one sensor to a given Delsys pair number.

        Pairing is isolated by default because DelsysAPI can raise CLR fatal errors
        inside PairSensor that bypass Python exception handling and terminate the
        current process.
        """
        pair_number = int(pair_number)
        if pair_number <= 0:
            raise ValueError("Delsys pair number must be positive")

        if isolated and self._base is None:
            return _pair_sensor_in_subprocess(pair_number, timeout_s)

        if self._base is None and not self._open_base():
            return False
        if not self._prepare_for_scan_or_pair("配对"):
            return False
        ok = _pair_sensor_on_base(self._base, pair_number, timeout_s)
        if not ok and not self.last_error:
            self.last_error = "Delsys sensor pairing failed or timed out."
        return ok

    def scan_sensors(
        self,
        *,
        use_ant: bool = False,
        link_device_types: Optional[list[str]] = None,
        select_pair_numbers: Optional[list[int]] = None,
        retry: int = 1,
    ) -> list[DelsysSensor]:
        """Scan paired sensors and select requested pair numbers for streaming."""
        if not self._open_base() or self._base is None:
            return []
        if not self._prepare_for_scan_or_pair("扫描"):
            return []

        return self._scan_sensors_connected(
            use_ant=use_ant,
            link_device_types=link_device_types,
            select_pair_numbers=select_pair_numbers,
            retry=retry,
        )

    def _scan_sensors_connected(
        self,
        *,
        use_ant: bool = False,
        link_device_types: Optional[list[str]] = None,
        select_pair_numbers: Optional[list[int]] = None,
        retry: int = 1,
    ) -> list[DelsysSensor]:
        if self._base is None:
            return []

        link_device_types = link_device_types or []
        last_exc: Optional[Exception] = None
        for attempt in range(max(1, int(retry))):
            try:
                _as_task_result(self._base.ScanSensors(bool(use_ant), link_device_types))
                break
            except Exception as exc:
                last_exc = exc
                if attempt + 1 >= max(1, int(retry)):
                    print(f"[Delsys] 扫描失败: {exc}")
                    self.last_error = str(exc)
                    return []
                time.sleep(1.0)
        if last_exc is not None and not self._has_connected_sensors():
            self.last_error = str(last_exc)
            return []

        self.scanned_sensors = self._read_sensors_from_base()
        if not self._restore_sensor_modes_after_scan():
            return []
        self._select_scanned_sensors(select_pair_numbers or self.sensors)
        self.last_error = ""
        return list(self.scanned_sensors)

    def get_available_sensor_modes(self, sensor_index: int) -> list[str]:
        if self._base is None:
            self.last_error = "Delsys receiver is not connected."
            return []
        try:
            modes = [str(mode) for mode in self._base.AvailableSensorModes(int(sensor_index))]
            self.last_error = ""
            return modes
        except Exception as exc:
            self.last_error = f"读取 Delsys 传感器可用模式失败: {exc}"
            return []

    def set_sample_mode(
        self,
        sensor_index: int,
        sample_mode: str,
        *,
        timeout_s: float = 5.0,
    ) -> bool:
        if self._base is None:
            self.last_error = "Delsys receiver is not connected."
            return False
        if self._running:
            self.last_error = "采集运行中不能切换 Delsys 传感器模式。"
            return False
        if not self._prepare_for_scan_or_pair("设置采样模式"):
            return False

        sensor_index = int(sensor_index)
        requested_mode = str(sample_mode or "").strip()
        if not requested_mode:
            self.last_error = "Delsys 传感器模式不能为空。"
            return False

        try:
            ok, sdk_mode = self._apply_sample_mode_connected(
                sensor_index,
                requested_mode,
                timeout_s=timeout_s,
            )
            if not ok or sdk_mode is None:
                return False

            pair_number = self._pair_number_for_sensor_index(sensor_index)
            if pair_number > 0:
                # ScanSensors rebuilds Delsys sensor objects and may restore their
                # default modes. Remember the desired mode by stable pair number so
                # every subsequent scan can reapply it.
                self.sensor_modes[pair_number] = sdk_mode

            # Channel layout and sampling rates are mode-dependent. Refresh them
            # immediately so recorders created before Start() use the correct rates.
            time.sleep(0.1)
            self.scanned_sensors = self._read_sensors_from_base()
            self._select_scanned_sensors(self.sensors)
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = f"设置 Delsys 采样模式失败: {exc}"
            print(f"[Delsys] {self.last_error}")
            return False

    def _apply_sample_mode_connected(
        self,
        sensor_index: int,
        requested_mode: str,
        *,
        timeout_s: float,
    ) -> tuple[bool, Optional[str]]:
        if self._base is None:
            self.last_error = "Delsys receiver is not connected."
            return False, None

        available_modes = [
            str(mode) for mode in self._base.AvailableSensorModes(int(sensor_index))
        ]
        mode_by_key = {
            mode.strip().casefold(): mode
            for mode in available_modes
            if mode.strip()
        }
        sdk_mode = mode_by_key.get(str(requested_mode).strip().casefold())
        if sdk_mode is None:
            self.last_error = (
                f"模式 {requested_mode!r} 不在传感器可用模式列表中: "
                f"{available_modes}"
            )
            return False, None

        current_mode = str(self._base.GetCurrentSensorMode(int(sensor_index)))
        if current_mode.strip().casefold() != sdk_mode.strip().casefold():
            self._base.SelectSensor(int(sensor_index))
            self._base.SetSampleMode(int(sensor_index), sdk_mode)

            deadline = time.monotonic() + max(0.5, float(timeout_s))
            current_mode = str(self._base.GetCurrentSensorMode(int(sensor_index)))
            while (
                current_mode.strip().casefold() != sdk_mode.strip().casefold()
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
                current_mode = str(self._base.GetCurrentSensorMode(int(sensor_index)))

        if current_mode.strip().casefold() != sdk_mode.strip().casefold():
            self.last_error = (
                f"Delsys 模式切换未生效：请求 {sdk_mode!r}，"
                f"传感器仍为 {current_mode!r}。"
            )
            return False, None
        return True, sdk_mode

    def _pair_number_for_sensor_index(self, sensor_index: int) -> int:
        for sensor in self.scanned_sensors:
            if sensor.index == int(sensor_index):
                return int(sensor.pair_number)
        try:
            return int(self._base.GetSensorPairNumber(int(sensor_index)))
        except Exception:
            return 0

    def _restore_sensor_modes_after_scan(self) -> bool:
        if not self.sensor_modes:
            return True

        changed = False
        for sensor in list(self.scanned_sensors):
            desired_mode = self.sensor_modes.get(sensor.pair_number)
            if not desired_mode:
                continue
            if sensor.mode.strip().casefold() == desired_mode.strip().casefold():
                continue
            try:
                ok, _sdk_mode = self._apply_sample_mode_connected(
                    sensor.index,
                    desired_mode,
                    timeout_s=5.0,
                )
            except Exception as exc:
                self.last_error = (
                    f"扫描后恢复 pair {sensor.pair_number} 模式失败: {exc}"
                )
                return False
            if not ok:
                detail = self.last_error
                self.last_error = (
                    f"扫描后无法恢复 pair {sensor.pair_number} 的模式 "
                    f"{desired_mode!r}: {detail}"
                )
                return False
            changed = True

        if changed:
            time.sleep(0.1)
            self.scanned_sensors = self._read_sensors_from_base()
        return True

    # -------------------- streaming --------------------
    def start(self) -> bool:
        if self._running:
            return True
        self.last_error = ""
        if self._base is None:
            self.last_error = "设备尚未连接，请先在硬件页连接设备。"
            print(f"[Delsys] {self.last_error}")
            return False
        if not self._selected_sensors:
            self.last_error = "尚未完成传感器扫描，请先在硬件页连接设备。"
            print(f"[Delsys] {self.last_error}")
            return False
        selected_pairs = {sensor.pair_number for sensor in self._selected_sensors}
        missing_pairs = [pair_number for pair_number in self.sensors if pair_number not in selected_pairs]
        if missing_pairs:
            self.last_error = f"未扫描到已选择的 pair number: {missing_pairs}"
            print(f"[Delsys] {self.last_error}")
            return False

        self._wait_after_recent_stop()
        if not self._configure_output():
            return False

        try:
            self._base.Start(self.stream_yt_data)
        except Exception as exc:
            self.last_error = f"启动采集失败: {exc}"
            print(f"[Delsys] {self.last_error}")
            with suppress(Exception):
                state = self._pipeline_state()
                if state == "Running":
                    self._base.Stop()
            return False

        self._running = True
        self._last_data_time = time.monotonic()
        self._yt_host_time_offset_s = None
        self._raw_imu_last_timestamps.clear()
        self._poll_thread = Thread(target=self._poll_loop, name="DelsysEMGCorePoller", daemon=True)
        self._poll_thread.start()
        return True

    def stop(self) -> bool:
        was_running = self._running
        self._running = False
        if self._poll_thread is not None and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)
        self._poll_thread = None
        if self._base is not None and was_running:
            state = self._pipeline_state()
            if state == "Running":
                try:
                    self._base.Stop()
                except Exception as exc:
                    self.last_error = f"停止采集失败: {exc}"
                    print(f"[Delsys] {self.last_error}")
                    return False
                self._wait_for_pipeline_state({"Armed", "Connected"}, timeout_s=3.0)
            elif state not in {"Armed", "Connected"}:
                settled_state = self._wait_for_pipeline_state({"Armed", "Connected"}, timeout_s=1.5)
                if settled_state not in {"Armed", "Connected"} and settled_state:
                    print(f"[Delsys] 停止时 Pipeline 状态为 {settled_state}，未重复调用 Stop。")
            self._last_stop_time = time.monotonic()
        return True

    def set_sensor_offline_callback(self, callback: Callable[[], None]) -> None:
        self._on_sensor_offline = callback

    # -------------------- internal helpers --------------------
    def _has_connected_sensors(self) -> bool:
        try:
            return self._base is not None and len(self._base.GetSensors()) > 0
        except Exception:
            return False

    def _pipeline_state(self) -> str:
        if self._base is None:
            return ""
        try:
            return str(self._base.GetPipelineState())
        except Exception as exc:
            self.last_error = f"读取 Delsys Pipeline 状态失败: {exc}"
            print(f"[Delsys] {self.last_error}")
            return ""

    def _wait_for_pipeline_state(self, expected_states: set[str], timeout_s: float = 3.0) -> str:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        state = self._pipeline_state()
        while state and state not in expected_states and time.monotonic() < deadline:
            time.sleep(0.1)
            state = self._pipeline_state()
        return state

    def _wait_after_recent_stop(self) -> None:
        if self._last_stop_time <= 0.0:
            return
        elapsed = time.monotonic() - self._last_stop_time
        if elapsed < 0.25:
            time.sleep(0.25 - elapsed)

    def _prepare_for_scan_or_pair(self, action_name: str) -> bool:
        """Move an armed-but-idle pipeline back to Connected before scan/pair."""
        state = self._pipeline_state()
        if state == "Running":
            self.last_error = f"采集运行中不能执行 Delsys {action_name}。"
            print(f"[Delsys] {self.last_error}")
            return False
        if state == "Armed":
            try:
                self._base.ResetPipeline()
            except Exception as exc:
                self.last_error = f"Delsys {action_name}前重置 Pipeline 失败: {exc}"
                print(f"[Delsys] {self.last_error}")
                return False
            state = self._wait_for_pipeline_state({"Connected"}, timeout_s=2.0)
        if state not in {"Off", "Connected"}:
            self.last_error = f"Delsys {action_name}需要 Pipeline 处于 Off/Connected，当前为 {state or 'Unknown'}。"
            print(f"[Delsys] {self.last_error}")
            return False
        return True

    def _read_sensors_from_base(self) -> list[DelsysSensor]:
        if self._base is None:
            return []
        sensors: list[DelsysSensor] = []
        aero_sensors = self._base.GetSensors()
        for sensor_index in range(len(aero_sensors)):
            channels: list[DelsysChannel] = []
            channel_objects: list[Any] = []
            with suppress(Exception):
                channel_objects = list(
                    self._base.GetSensorObject(sensor_index).TrignoChannels
                )
            for channel_index, item in enumerate(
                self._base.GetSensorChannelInfo(sensor_index)
            ):
                try:
                    unit = str(_mapping_value(item, "Unit", "Units"))
                    if not unit and channel_index < len(channel_objects):
                        unit = str(channel_objects[channel_index].Unit)
                    channels.append(
                        DelsysChannel(
                            name=str(_mapping_value(item, "Name")),
                            enabled=str(_mapping_value(item, "Enabled")).casefold() == "true",
                            channel_type=str(_mapping_value(item, "Type")),
                            sample_rate=float(_mapping_value(item, "Sample Rate", default=0.0)),
                            guid=str(_mapping_value(item, "Guid")),
                            unit=unit,
                        )
                    )
                except Exception:
                    continue
            sensors.append(
                DelsysSensor(
                    index=sensor_index,
                    name=str(aero_sensors[sensor_index].FriendlyName),
                    pair_number=int(self._base.GetSensorPairNumber(sensor_index)),
                    mode=str(self._base.GetCurrentSensorMode(sensor_index)),
                    channels=channels,
                )
            )
        return sensors

    def _select_scanned_sensors(self, pair_numbers: list[int]) -> None:
        if self._base is None:
            return

        pair_set = {int(number) for number in pair_numbers if int(number) > 0}
        self._selected_sensors = [
            sensor for sensor in self.scanned_sensors if not pair_set or sensor.pair_number in pair_set
        ]
        self._selected_sensors.sort(key=lambda sensor: sensor.pair_number)
        selected_indices = {sensor.index for sensor in self._selected_sensors}

        try:
            for sensor in self.scanned_sensors:
                if sensor.index in selected_indices:
                    self._base.SelectSensor(sensor.index)
        except Exception:
            # Older AeroPy builds expose SelectAllSensors but not a clear-selection method.
            # In that case the GUID filtering below still restricts published EMG channels.
            with suppress(Exception):
                self._base.SelectAllSensors()

    def _selected_sensors_for_metadata(self) -> list[DelsysSensor]:
        pair_set = {int(number) for number in self.sensors if int(number) > 0}
        source = self._selected_sensors or self.scanned_sensors
        sensors = [
            sensor
            for sensor in source
            if not pair_set or sensor.pair_number in pair_set
        ]
        return sorted(sensors, key=lambda sensor: sensor.pair_number)

    def _selected_emg_sample_rates(self) -> list[float]:
        rates: list[float] = []
        for sensor in self._selected_sensors_for_metadata():
            if sensor.emg_channels:
                rates.append(float(sensor.emg_channels[0].sample_rate))
        return rates

    def _validate_selected_emg_sample_rates(self) -> bool:
        rates = self._selected_emg_sample_rates()
        if not rates:
            self.last_error = "当前选中的 Delsys 传感器没有可用 EMG 通道。"
            return False
        reference = rates[0]
        if any(abs(rate - reference) > 0.5 for rate in rates[1:]):
            self.last_error = (
                "当前选中的 Delsys 传感器 EMG 采样率不一致: "
                f"{[round(rate, 3) for rate in rates]}。"
                "现有 EMG 文件格式要求所有通道使用相同采样率，请将所选传感器设置为兼容模式。"
            )
            return False
        return True

    @property
    def has_selected_imu_channels(self) -> bool:
        for sensor in self._selected_sensors_for_metadata():
            for channel in sensor.imu_channels:
                if channel.normalized_type in self.delsys_imu_channel_types:
                    return True
        return False

    @property
    def delsys_sensor_metadata(self) -> list[dict[str, Any]]:
        metadata: list[dict[str, Any]] = []
        for sensor in self._selected_sensors_for_metadata():
            channels = []
            for channel in sensor.channels:
                if not channel.enabled or channel.normalized_type == "SKINCHECK":
                    continue
                channels.append(
                    {
                        "name": channel.name,
                        "type": channel.normalized_type,
                        "axis": channel.axis,
                        "sample_rate": channel.sample_rate,
                        "unit": channel.unit,
                        "guid": channel.guid,
                    }
                )
            metadata.append(
                {
                    "pair_number": sensor.pair_number,
                    "sensor_name": sensor.name,
                    "mode": sensor.mode,
                    "channels": channels,
                }
            )
        return metadata

    def _configure_output(self) -> bool:
        if self._base is None:
            return False
        try:
            state = self._wait_for_pipeline_state({"Armed", "Connected"}, timeout_s=3.0)
            if state == "Armed":
                pass
            elif state == "Connected":
                if self.station_type == DelsysStationType.BASESTATION:
                    self._base.Configure(False, False)
                elif self.station_type == DelsysStationType.CENTRO:
                    self._configure_centro_default_triggers()
                    self._base.Configure()
                else:
                    self._base.Configure()
            else:
                self.last_error = f"Pipeline 当前状态不支持启动: {state or 'Unknown'}"
                print(f"[Delsys] {self.last_error}")
                return False
            configured = bool(self._base.IsPipelineConfigured())
            if not configured:
                time.sleep(0.2)
                configured = bool(self._base.IsPipelineConfigured())
            if not configured:
                self.last_error = "Pipeline 配置失败。"
                print(f"[Delsys] {self.last_error}")
                return False
        except Exception as exc:
            self.last_error = f"Pipeline 配置异常: {exc}"
            print(f"[Delsys] {self.last_error}")
            return False

        refreshed_sensors = self._read_sensors_from_base()
        if refreshed_sensors:
            self.scanned_sensors = refreshed_sensors
            selected_pairs = {sensor.pair_number for sensor in self._selected_sensors}
            if not selected_pairs:
                selected_pairs = {int(pair_number) for pair_number in self.sensors if int(pair_number) > 0}
            self._selected_sensors = [
                sensor for sensor in self.scanned_sensors if not selected_pairs or sensor.pair_number in selected_pairs
            ]
            self._selected_sensors.sort(key=lambda sensor: sensor.pair_number)
        self._emg_channel_guids.clear()
        self._emg_channel_sample_rates.clear()
        self._imu_channel_records.clear()

        selected_by_pair = {sensor.pair_number: sensor for sensor in self._selected_sensors}
        ordered_pairs = sorted(selected_by_pair.keys())
        for pair_number in ordered_pairs:
            emg_channels = selected_by_pair[pair_number].emg_channels
            if not emg_channels:
                print(f"[Delsys] 传感器 pair {pair_number} 没有启用 EMG 通道。")
                continue
            channel = emg_channels[0]
            self._emg_channel_guids.append(channel.guid)
            self._emg_channel_sample_rates.append(channel.sample_rate)

        if not self._emg_channel_guids:
            self.last_error = "未发现可发布的 Delsys EMG 通道。"
            print(f"[Delsys] {self.last_error}")
            return False
        if not self._validate_selected_emg_sample_rates():
            print(f"[Delsys] {self.last_error}")
            return False
        self._imu_channel_records = self._build_imu_channel_records(
            [selected_by_pair[pair_number] for pair_number in ordered_pairs]
        )
        if self.delsys_imu_enabled and not self._imu_channel_records:
            self.last_error = (
                "Delsys IMU recording is enabled, but no enabled ACC/GYRO channels "
                "were found in the current sensor mode. Change the Delsys sample "
                "mode to one that includes ACC/GYRO, then scan again."
            )
            print(f"[Delsys] {self.last_error}")
            return False
        return True

    def _build_imu_channel_records(self, sensors: list[DelsysSensor]) -> list[DelsysIMUChannelRecord]:
        records: list[DelsysIMUChannelRecord] = []
        fallback_axis_index: dict[tuple[int, str], int] = {}
        axes = ("x", "y", "z")
        for sensor in sensors:
            for channel in sensor.imu_channels:
                channel_type = channel.normalized_type
                if channel_type not in self.delsys_imu_channel_types:
                    continue
                axis = channel.axis
                if axis not in axes:
                    key = (sensor.pair_number, channel_type)
                    index = fallback_axis_index.get(key, 0)
                    axis = axes[index % len(axes)]
                    fallback_axis_index[key] = index + 1
                records.append(
                    DelsysIMUChannelRecord(
                        pair_number=sensor.pair_number,
                        sensor_name=sensor.name,
                        channel_name=channel.name,
                        channel_type=channel_type,
                        axis=axis,
                        sample_rate=channel.sample_rate,
                        guid=channel.guid,
                        unit=channel.unit,
                    )
                )
        return records

    def _configure_centro_default_triggers(self) -> None:
        """Apply valid disabled trigger defaults before Centro Configure()."""
        if self._base is None:
            return
        for trigger_type in range(4):
            with suppress(Exception):
                self._base.SetTrigger(False, 0, False, True, trigger_type)
        with suppress(Exception):
            self._base.SetSyncOutput(False, 0, False, 74)

    def _poll_loop(self) -> None:
        while self._running:
            try:
                frame = self._poll_once()
                if frame is not None:
                    self._last_data_time = time.monotonic()
                    self._publish_frame(frame)
                elif (
                    self._detect_offline_on_no_data
                    and time.monotonic() - self._last_data_time > self._offline_timeout_s
                ):
                    if self._on_sensor_offline is not None:
                        with suppress(Exception):
                            self._on_sensor_offline()
                    self._last_data_time = time.monotonic()
            except Exception as exc:
                print(f"[Delsys] 数据轮询异常: {exc}")
                if self._on_error:
                    self._on_error(f'Delsys 数据轮询异常：{exc}')
                time.sleep(0.05)
            time.sleep(self.poll_interval_s)

    def _poll_once(self) -> Optional[dict[str, Any]]:
        if self._base is None:
            return None
        if self.stream_yt_data:
            if not bool(self._base.CheckYTDataQueue()):
                return None
            data_out = self._base.PollYTDataByString()
            samples = self._extract_yt_samples(data_out)
        else:
            if not bool(self._base.CheckDataQueue()):
                return None
            data_out = self._base.PollDataByString()
            samples = self._extract_samples(data_out)
        packet_timestamp = time.time()
        if samples is None or samples.size == 0:
            return None
        selected_pairs = [
            sensor.pair_number for sensor in self._selected_sensors_for_metadata()
        ]
        frame = {
            "timestamp": packet_timestamp,
            "sensor_samples": samples.tolist(),
            "source": "delsys",
            "sampling_rate": self.sampling_rate,
            "sampling_rate_exact": self.sampling_rate_exact,
            "pair_numbers": selected_pairs,
        }
        if self.stream_yt_data and self._emg_channel_guids:
            try:
                device_timestamps = [
                    float(item.Item1)
                    for item in data_out[self._emg_channel_guids[0]]
                ][: samples.shape[1]]
            except Exception:
                device_timestamps = []
            if device_timestamps:
                if self._yt_host_time_offset_s is None:
                    self._yt_host_time_offset_s = packet_timestamp - device_timestamps[-1]
                frame["delsys_emg_timestamps"] = device_timestamps
                frame["sensor_timestamps"] = [
                    timestamp + self._yt_host_time_offset_s
                    for timestamp in device_timestamps
                ]
        if self.delsys_imu_enabled and self._imu_channel_records:
            imu_samples = self._extract_imu_samples(
                data_out,
                packet_timestamp=packet_timestamp,
                yt_data=self.stream_yt_data,
            )
            if imu_samples:
                frame["delsys_imu_samples"] = imu_samples
        return frame

    def _extract_samples(self, data_out: Any) -> Optional[np.ndarray]:
        rows: list[np.ndarray] = []
        min_len: Optional[int] = None
        for guid in self._emg_channel_guids:
            try:
                values = np.asarray(list(data_out[guid]), dtype=np.float32)
            except Exception:
                return None
            if values.size == 0:
                return None
            min_len = values.size if min_len is None else min(min_len, values.size)
            rows.append(values)
        if min_len is None or min_len <= 0:
            return None
        return np.vstack([row[:min_len] for row in rows])

    def _extract_yt_samples(self, data_out: Any) -> Optional[np.ndarray]:
        rows: list[np.ndarray] = []
        min_len: Optional[int] = None
        for guid in self._emg_channel_guids:
            try:
                values = np.asarray([float(item.Item2) for item in data_out[guid]], dtype=np.float32)
            except Exception:
                return None
            if values.size == 0:
                return None
            min_len = values.size if min_len is None else min(min_len, values.size)
            rows.append(values)
        if min_len is None or min_len <= 0:
            return None
        return np.vstack([row[:min_len] for row in rows])

    def _extract_imu_samples(
        self,
        data_out: Any,
        *,
        packet_timestamp: float,
        yt_data: bool,
    ) -> list[dict[str, Any]]:
        channel_samples: list[
            tuple[DelsysIMUChannelRecord, list[tuple[Optional[float], float]]]
        ] = []
        latest_device_timestamp: Optional[float] = None

        for record in self._imu_channel_records:
            try:
                if yt_data:
                    samples = [
                        (float(item.Item1), float(item.Item2))
                        for item in data_out[record.guid]
                    ]
                else:
                    values = np.asarray(list(data_out[record.guid]), dtype=np.float32)
                    timestamps = self._raw_imu_sample_timestamps(
                        record,
                        int(values.size),
                        packet_timestamp,
                    )
                    samples = [
                        (timestamp, float(value))
                        for timestamp, value in zip(timestamps, values)
                    ]
            except Exception:
                continue
            if not samples:
                continue
            if yt_data:
                channel_latest = max(timestamp for timestamp, _value in samples if timestamp is not None)
                latest_device_timestamp = (
                    channel_latest
                    if latest_device_timestamp is None
                    else max(latest_device_timestamp, channel_latest)
                )
            channel_samples.append((record, samples))

        if yt_data and latest_device_timestamp is not None and self._yt_host_time_offset_s is None:
            self._yt_host_time_offset_s = packet_timestamp - latest_device_timestamp

        rows_by_key: dict[tuple[int, int], dict[str, Any]] = {}
        for record, samples in channel_samples:
            for sample_time, value in samples:
                if yt_data and sample_time is not None:
                    host_timestamp = sample_time + float(self._yt_host_time_offset_s or 0.0)
                    timestamp_key = int(round(sample_time * 1_000_000_000))
                    device_timestamp: Optional[float] = sample_time
                else:
                    host_timestamp = (
                        float(sample_time)
                        if sample_time is not None
                        else packet_timestamp
                    )
                    timestamp_key = int(round(host_timestamp * 1_000_000_000))
                    device_timestamp = None

                row = rows_by_key.setdefault(
                    (record.pair_number, timestamp_key),
                    {
                        "timestamp": host_timestamp,
                        "delsys_timestamp": (
                            device_timestamp if device_timestamp is not None else ""
                        ),
                        "pair_number": record.pair_number,
                        "sensor_name": record.sensor_name,
                        "raw_channels": {},
                    },
                )
                key = f"{record.channel_type.lower()}_{record.axis}"
                row[key] = value
                row["raw_channels"][record.channel_name] = {
                    "type": record.channel_type,
                    "axis": record.axis,
                    "sample_rate": record.sample_rate,
                    "unit": record.unit,
                    "delsys_timestamp": (
                        device_timestamp if device_timestamp is not None else ""
                    ),
                    "value": value,
                }

        return sorted(
            rows_by_key.values(),
            key=lambda row: (float(row["timestamp"]), int(row["pair_number"])),
        )

    def _raw_imu_sample_timestamps(
        self,
        record: DelsysIMUChannelRecord,
        sample_count: int,
        packet_timestamp: float,
    ) -> list[float]:
        if sample_count <= 0:
            return []
        sample_rate = float(record.sample_rate or 0.0)
        if sample_rate <= 0.0:
            return [float(packet_timestamp)] * sample_count

        interval = 1.0 / sample_rate
        first_timestamp = float(packet_timestamp) - (sample_count - 1) * interval
        previous_timestamp = self._raw_imu_last_timestamps.get(record.guid)
        if previous_timestamp is not None:
            first_timestamp = max(first_timestamp, previous_timestamp + interval)

        timestamps = [
            first_timestamp + index * interval
            for index in range(sample_count)
        ]
        self._raw_imu_last_timestamps[record.guid] = timestamps[-1]
        return timestamps

    def _publish_frame(self, frame: dict[str, Any]) -> None:
        if callable(self._on_frame):
            with suppress(Exception):
                self._on_frame(frame)
        if self.enable_bus and EventBus is not None and BusData is not None:
            with suppress(Exception):
                EventBus.publish(EMG_DATA_TOPIC, data=BusData(data=frame))

    @property
    def sampling_rate(self) -> int:
        return int(round(self.sampling_rate_exact))

    @property
    def sampling_rate_exact(self) -> float:
        rates = self._emg_channel_sample_rates or self._selected_emg_sample_rates()
        if rates:
            return float(rates[0])
        return 2148


__all__ = [
    "DelsysChannel",
    "DelsysEMGCore",
    "DelsysIMUChannelRecord",
    "DelsysSensor",
    "DelsysStationType",
]


def _main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Delsys helper commands")
    parser.add_argument("--pair", type=int, help="Pair a Delsys sensor to this pair number.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Pairing timeout in seconds.")
    args = parser.parse_args(argv)

    if args.pair is None:
        parser.print_help()
        return 1

    ok = _pair_sensor_in_current_process(args.pair, args.timeout)
    with suppress(Exception):
        sys.stdout.flush()
    with suppress(Exception):
        sys.stderr.flush()
    os._exit(0 if ok else 2)


if __name__ == "__main__":
    raise SystemExit(_main())
