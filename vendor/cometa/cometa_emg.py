from __future__ import annotations

"""Cometa EMG 核心模块.

核心职责:
- 管理 CometaDaqSystem 的生命周期 (创建/启动/停止/释放)
- 将 .NET 回调参数转换为 Python 友好的结构
- 可选地在 EventBus 上发布 `emg.data` 主题的帧

简化后的核心假设:
- 输入的 EMG 包是一维的; 保留前半部分; 将其等分为 16 个通道.
- 始终将回调数据入队，并在后台线程中解析.
- 可选地将解析后的帧以 JSONL 格式持久化.
"""

from contextlib import suppress
from dataclasses import dataclass
from threading import Thread
from queue import Queue, Empty
from typing import Any, Callable, Dict, Optional, Tuple
from datetime import datetime
import time
import json

# SDK 包装器
from .pyemg_cometa.capture_configuration import CometaCaptureConfiguration
from .pyemg_cometa.constants import (
    DataAvailableEventPeriodEnum,
    DeviceErrorEnum,
    DeviceStateEnum,
    SamplingRateEnum,
    SensorCheckReportEnum,
    SensorTypeEnum,
)
from .pyemg_cometa.daq_system import CometaDaqSystem
from .pyemg_cometa.event_args import CometaDataAvailableEventArgs
from .pyemg_cometa.sensor_configuration import CometaSensorConfiguration

# 可选的 EventBus
try:
    from utils.bus.event_bus import EventBus  # type: ignore
    from utils.bus.bus_data import BusData  # type: ignore
    from resource.hardware.topics import EMG_DATA_TOPIC
except Exception:  # pragma: no cover
    EventBus = None  # type: ignore
    BusData = None  # type: ignore
    EMG_DATA_TOPIC = "emg.data"


@dataclass
class EmgFrame:
    """EMG 数据帧 (一次回调事件的载体)."""
    timestamp: float  # 格式: time.time()
    sensor_samples: list[list[float]]


def _wrap_event_args(raw: Any) -> Any:
    """确保事件参数是 CometaDataAvailableEventArgs 类型."""
    if isinstance(raw, CometaDataAvailableEventArgs):
        return raw
    try:
        import clr  # type: ignore
        return clr.Convert(raw, CometaDataAvailableEventArgs)  # type: ignore[attr-defined]
    except Exception:
        return raw


def _get_event_value(obj: Any, method_name: str, attr_name: str, default: Any = None) -> Any:
    """尝试通过方法或属性获取 .NET 事件参数的值."""
    if hasattr(obj, method_name):
        fn = getattr(obj, method_name)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    return getattr(obj, attr_name, default)


def _now_bus_timestamp() -> str:
    """获取当前时间戳，用于总线发布."""
    return datetime.now().strftime("%Y.%m.%d %H.%M.%S.%f")


def _split_flat_samples(flat_samples: list[float], channel_count: int) -> list[list[float]]:
    """将扁平化的样本列表拆分为多通道矩阵."""
    if not channel_count or not flat_samples:
        return []
    total_len = len(flat_samples)
    if total_len % channel_count != 0:
        print(f"[WARN] 数据总长={total_len} 无法被 {channel_count} 个通道整除.")
        return []
    per_channel = total_len // channel_count
    return [flat_samples[i * per_channel:(i + 1) * per_channel] for i in range(channel_count)]


def _preprocess_for_publish(frame: EmgFrame) -> Dict[str, Any]:
    """发布前的预处理占位符 (例如，降采样、合并等)."""
    return {
        "timestamp": frame.timestamp,
        "sensor_samples": frame.sensor_samples,
    }


ParsedCallback = Callable[[EmgFrame], None]


class CometaEMGCore:
    """Cometa EMG 设备核心控制器."""
    def __init__(
        self,
        *,
        sensors: Optional[list[int]] = None,
        sampling_rate: Any = None,
        event_period: Any = None,
        enable_bus: bool = True,
        on_frame: Optional[ParsedCallback] = None,
        on_error: Optional[Callable[[str], None]] = None,
        queue_maxsize: int = 16,
        save_jsonl_path: Optional[str] = None,
    ) -> None:
        # 允许无参数初始化，回退到合理的默认值
        self.sensors = sensors[:] if sensors else [1]
        self.sampling_rate = sampling_rate if sampling_rate is not None else SamplingRateEnum.HZ_2000
        self.event_period = event_period if event_period is not None else DataAvailableEventPeriodEnum.MS_25
        self.enable_bus = bool(enable_bus)
        self._on_frame = on_frame
        self._on_error = on_error
        self.last_error = ""

        self._daq: Optional[CometaDaqSystem] = None
        self._handler_ref: Optional[Callable[..., None]] = None
        self._start_time: float = 0.0
        self._running = False
        
        # 固定的后台处理机制
        self._queue: Queue[Tuple[Any, float]] = Queue(maxsize=max(1, int(queue_maxsize)))
        self._worker: Optional[Thread] = None
        self._save_jsonl_path = save_jsonl_path
        self._save_fh: Optional[Any] = None

        # 掉线检测相关状态
        self._on_sensor_offline: Optional[Callable[[], None]] = None
        self._sensor_last_values: Dict[int, float] = {}
        self._alive_sensors_in_window: set[int] = set()
        self._last_window_check_time: float = 0.0
        self._offline_triggered: bool = False

    # -------- 生命周期 --------
    def connect(self, *, timeout: float = 15.0) -> bool:
        """创建设备句柄，配置并等待所有传感器就绪."""
        if self._daq is not None:
            return True
        self.last_error = ""

        # 1. 创建 DAQ 系统实例
        daq = CometaDaqSystem()
        init_err = daq.get_initial_error()
        if init_err != DeviceErrorEnum.SUCCESS:
            self.last_error = f"Cometa 初始化失败：{init_err}。请检查基站驱动、USB 和电源，并关闭其他占用基站的软件。"
            print(self.last_error)
            with suppress(Exception):
                daq.dispose()
            return False

        state = daq.get_state()
        deadline = time.monotonic() + timeout
        while state == DeviceStateEnum.INITIALIZING and time.monotonic() < deadline:
            time.sleep(0.1)
            state = daq.get_state()
        if state == DeviceStateEnum.NOT_CONNECTED:
            self.last_error = (
                "Cometa SDK 未发现基站。请先检查 Windows 设备管理器："
                "若有黄色感叹号或代码 28，需安装 Cometa 官方 USB 驱动；"
                "再检查 USB、电源，并关闭 EMG and Motion Tools 等占用基站的软件。"
            )
        elif state != DeviceStateEnum.IDLE:
            self.last_error = f"Cometa 基站未就绪（状态：{state}）。请检查基站连接，并关闭其他占用基站的软件后重试。"
        if self.last_error:
            print(self.last_error)
            with suppress(Exception):
                daq.dispose()
            return False

        self._daq = daq

        # 2. 配置采集和传感器
        # 采集配置
        capture_conf = CometaCaptureConfiguration()
        capture_conf.set_sampling_rate(self.sampling_rate)
        daq.set_capture_configuration(capture_conf)

        # 先禁用所有已安装的传感器
        try:
            installed = int(daq.get_num_installed_sensors())
        except Exception:
            installed = 0
        for sensor_id in range(1, installed + 1):
            with suppress(Exception):
                daq.disable_sensor(sensor_id)

        # 启用请求的EMG传感器
        for sid in self.sensors:
            sensor_conf = CometaSensorConfiguration()
            sensor_conf.set_sensor_type(SensorTypeEnum.EMG_SENSOR)
            daq.set_sensor_configuration(sensor_conf, sid)
            daq.enable_sensor(sid)
            with suppress(Exception):
                daq.turn_led_on(sid)

        # 3. 通过预采集检查传感器是否就绪
        if not self._wait_for_sensors_ready(timeout=timeout):
            self.last_error = self.last_error or "Cometa 传感器未在规定时间内就绪，请检查所选编号、传感器电源和电量。"
            print(f"[ERROR] {self.last_error}")
            # 出错后关闭LED灯并断开连接
            for sid in self.sensors:
                with suppress(Exception):
                    daq.turn_all_leds_off()
            self.disconnect()
            print("[INFO] 设备已断开连接。")
            return False

        print("[INFO] 所有传感器均已准备就绪，设备连接成功。")
        # 注册正式的数据回调 (只注册一次)
        self._daq.add_on_data_available_handler(self._on_data_available)
        return True

    def disconnect(self) -> bool:
        """停止并断开设备连接."""
        self.stop()
        daq = self._daq
        if daq is not None:
            with suppress(Exception):
                daq.remove_on_data_available_handler(self._on_data_available)
            try:
                installed = int(daq.get_num_installed_sensors())
            except Exception:
                installed = 0
            for sensor_id in range(1, installed + 1):
                with suppress(Exception):
                    daq.disable_sensor(sensor_id)
            with suppress(Exception):
                daq.dispose()
            self._daq = None
        return True

    def is_running(self) -> bool:
        """检查设备是否正在采集中."""
        return self._running

    # -------- 配置 --------
    def configure(
        self,
        *,
        sensors: Optional[list[int]] = None,
        sampling_rate: Optional[Any] = None,
        event_period: Optional[Any] = None,
        enable_bus: Optional[bool] = None,
        on_frame: Optional[ParsedCallback] = None,
        save_jsonl_path: Optional[str] = None,
    ) -> bool:
        """配置设备参数 (必须在停止状态下调用)."""
        if self._running:
            print("[WARN] 采集运行时不允许配置; 请先停止.")
            return False
        if sensors is not None:
            if not sensors:
                raise ValueError("至少需要一个传感器ID")
            if min(sensors) <= 0:
                raise ValueError("传感器ID从1开始")
            self.sensors = list(sensors)
        if sampling_rate is not None:
            self.sampling_rate = sampling_rate
        if event_period is not None:
            self.event_period = event_period
        if enable_bus is not None:
            self.enable_bus = bool(enable_bus)
        if on_frame is not None:
            self._on_frame = on_frame
        if save_jsonl_path is not None:
            if self._save_fh is not None:
                with suppress(Exception):
                    self._save_fh.close()
                self._save_fh = None
            self._save_jsonl_path = save_jsonl_path
        return True

    def _wait_for_sensors_ready(self, timeout: float = 10.0) -> bool:
        """通过预采集等待所有传感器准备就绪."""
        if not self._daq:
            return False

        print("[INFO] 正在通过预采集检查传感器状态...")
        daq = self._daq
        not_ready_sensors = set(self.sensors)
        last_values: Dict[int, float] = {}
        handler_ref = None

        def pre_acq_callback(_sender, raw_args) -> None:
            """预采集回调：检查数据是否变化."""
            nonlocal not_ready_sensors, last_values
            if not not_ready_sensors:
                return

            wrapped = _wrap_event_args(raw_args)
            emg_raw_enum = _get_event_value(wrapped, "get_emg_samples", "Samples", [])
            try:
                raw_items = list(emg_raw_enum)
            except Exception:
                raw_items = []

            valid_len = len(raw_items) // 2
            valid_flat_data = [float(x) for x in raw_items[:valid_len]]
            matrix = _split_flat_samples(valid_flat_data, 16)
            if not matrix:
                return

            # 检查每个未就绪传感器的数据
            for sid in list(not_ready_sensors):
                if not (1 <= sid <= len(matrix)):
                    continue

                channel_data = matrix[sid - 1]
                if not channel_data:
                    continue

                current_val = channel_data[0]

                # 如果是第一次收到数据，则记录
                if sid not in last_values:
                    last_values[sid] = current_val
                    continue

                # 如果数据发生变化，则认为传感器已就绪
                if current_val != last_values[sid]:
                    print(f"[INFO] 传感器 {sid} 已就绪 (数据发生变化).")
                    not_ready_sensors.remove(sid)

        try:
            # 注册临时回调并开始预采集
            handler_ref = pre_acq_callback
            daq.add_on_data_available_handler(handler_ref)
            daq.start_capturing(self.event_period)

            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                if not not_ready_sensors:
                    print("[INFO] 所有传感器均已在预采集中就绪。")
                    return True
                time.sleep(0.1)

            # 超时处理
            if not_ready_sensors:
                self.last_error = f"Cometa 传感器 {sorted(not_ready_sensors)} 未收到变化的数据。请检查编号、电源、电量和无线连接。"
                print(f"[ERROR] 等待超时。未就绪的传感器: {sorted(list(not_ready_sensors))}")
                return False
            return True

        finally:
            # 清理：停止采集并移除回调
            with suppress(Exception):
                daq.stop_capturing()
            if handler_ref:
                with suppress(Exception):
                    daq.remove_on_data_available_handler(handler_ref)

    # -------- 运行控制 --------
    def start(self) -> bool:
        """启动采集 (假设设备已通过 connect 准备就绪)."""
        if self._running:
            return True
        if self._daq is None:
            print("[ERROR] 设备未连接。请先调用 connect()。")
            return False

        daq = self._daq
        self._start_time = time.monotonic()
        self._running = True

        # 重置掉线检测状态
        self._sensor_last_values.clear()
        self._alive_sensors_in_window.clear()
        self._last_window_check_time = time.monotonic()
        self._offline_triggered = False

        # 启动采集和工作线程
        daq.start_capturing(self.event_period)
        if self._worker is None or not self._worker.is_alive():
            if self._save_jsonl_path and self._save_fh is None:
                try:
                    self._save_fh = open(self._save_jsonl_path, "a", encoding="utf-8")
                except Exception:
                    self._save_fh = None
            self._worker = Thread(target=self._worker_loop, name="CometaEMGCoreWorker", daemon=True)
            self._worker.start()

        print("[INFO] EMG 采集已启动。")
        return True

    def stop(self) -> bool:
        """停止采集."""
        if not self._daq:
            self._running = False
            return True
        daq = self._daq

        # 仅在标记为运行时才尝试停止采集，避免在 connect 失败清理时重复调用 stop_capturing
        if self._running:
            with suppress(Exception):
                daq.stop_capturing()

        self._running = False

        # 短暂耗尽队列并停止工作线程
        if self._worker is not None:
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if self._queue.empty():
                    break
                time.sleep(0.02)
            self._worker = None
        if self._save_fh is not None:
            with suppress(Exception):
                self._save_fh.close()
            self._save_fh = None
        return True

    def _on_data_available(self, _sender, raw_args) -> None:
        """硬件回调：将原始事件快速入队."""
        if not self._running:
            return
        wrapped = _wrap_event_args(raw_args)
        try:
            self._queue.put_nowait((wrapped, time.monotonic()))
        except Exception as exc:
            if self._on_error:
                self._on_error(f'Cometa 原始队列溢出，不能保证标签对齐：{exc}')

    # -------- 内部方法 --------
    def _worker_loop(self) -> None:
        """后台工作线程：从队列中取出数据并处理."""
        while self._running:
            try:
                wrapped, _t = self._queue.get(timeout=0.2)
            except Empty:
                continue
            except Exception:
                break
            try:
                self._handle_event(wrapped)
            except Exception as exc:
                if self._on_error:
                    self._on_error(f'Cometa 数据解析失败：{exc}')

    def _handle_event(self, wrapped: Any) -> None:
        """处理单个事件：解析、构建帧、分发."""
        # 将原始枚举转换为 Python 列表
        emg_raw_enum = _get_event_value(wrapped, "get_emg_samples", "Samples", [])
        try:
            raw_items = list(emg_raw_enum)
        except Exception:
            raw_items = []

        # 保留前半部分，然后切分为16个通道
        valid_len = len(raw_items) // 2
        valid_flat_data = [float(x) for x in raw_items[:valid_len]]
        matrix = _split_flat_samples(valid_flat_data, 16)
        if not matrix:
            raise ValueError('Cometa 帧长度无效')
        
        # 掉线检测逻辑，时间窗口聚合检查
        if not self._offline_triggered:
            now_m = time.monotonic()
            
            # 1. 累积阶段：检查数值变化并标记活跃
            for sid in self.sensors:
                # 如果本窗口内已经标记为活跃，不再重复检查
                if sid in self._alive_sensors_in_window:
                    continue

                if not (1 <= sid <= len(matrix)): 
                    continue
                
                channel_data = matrix[sid - 1]
                if not channel_data: 
                    continue
                
                val = channel_data[0]
                # 检查变化 (如果是第一帧 old_val 为 None, 也会视为变化)
                old_val = self._sensor_last_values.get(sid)
                if old_val != val:
                    self._sensor_last_values[sid] = val
                    self._alive_sensors_in_window.add(sid)
            
            # 2. 检查阶段：每秒检查一次窗口内是否所有传感器都活跃过
            if now_m - self._last_window_check_time > 1.0:
                missing_sensors = [s for s in self.sensors if s not in self._alive_sensors_in_window]
                
                if missing_sensors:
                    print(f"[ERROR] Cometa传感器 {missing_sensors} 失效: 1秒窗口内数据无变化。")
                    self._offline_triggered = True
                    if self._on_sensor_offline:             # 调用掉线回调
                        with suppress(Exception):
                            self._on_sensor_offline()
                
                # 重置窗口状态，开启下一轮监测
                self._alive_sensors_in_window.clear()
                self._last_window_check_time = now_m

        ts = time.time()
        frame = EmgFrame(timestamp=ts, sensor_samples=matrix)

        # 外部回调
        if callable(self._on_frame):
            try:
                self._on_frame(frame)
            except Exception as e:
                import traceback
                print(f"[ERROR] 外部回调 on_frame 执行失败: {e}")
                traceback.print_exc()

        # 事件总线发布
        if self.enable_bus and EventBus is not None and BusData is not None:
            payload: Dict[str, Any] = _preprocess_for_publish(frame)
            try:
                EventBus.publish(EMG_DATA_TOPIC, data=BusData(data=payload))
            except Exception:
                pass

        # 可选的持久化
        if self._save_fh is not None:
            try:
                rec = _preprocess_for_publish(frame)
                self._save_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass
    

    def set_sensor_offline_callback(self, callback: Callable[[], None]) -> None:
        """
        设置传感器掉线回调函数，用于将顶层实例的连接状态置为 False.
        """
        self._on_sensor_offline = callback


__all__ = ["CometaEMGCore", "EmgFrame"]
