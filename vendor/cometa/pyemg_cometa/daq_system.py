############
#
# Copyright (c) 2024 Maxim Yudayev and KU Leuven eMedia Lab
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Created 2024-2025 for the KU Leuven AidWear, AidFOG, and RevalExo projects
# by Maxim Yudayev [https://yudayev.com].
#
# ############

"""
Cometa Waveplus 采集系统 Python 封装。

本模块通过 pythonnet 加载随包分发的 .NET DLL，对原始 DaqSystem
进行“薄封装”，以更符合 Python 习惯的命名与返回值形式提供接口。

注意：该封装不改变底层行为，仅做方法名与数据结构的 Python 化。
"""

from typing import Any, Callable, Iterable
import clr
import os
dir_path = os.path.dirname(__file__)

clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSys')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSysInterface')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'CyUSB')) # type: ignore

from .constants import DataAvailableEventPeriodEnum, RFChannelEnum
from .constants import DeviceErrorEnum, DeviceStateEnum
from .constants import SensorCheckReportEnum, SensorTypeEnum
from .capture_configuration import CometaCaptureConfiguration
from .device_dependent_functionalities import CometaDeviceDependentFunctionalities
from .event_args import CometaDataAvailableEventArgs, CometaDeviceStateChangedEventArgs, CometaSensorMemoryDataAvailableEventArgs
from .sensor_configuration import CometaSensorConfiguration
from .version import CometaExtVersion, CometaVersion

from Waveplus.DaqSys import * # type: ignore
from Waveplus.DaqSysInterface import * # type: ignore
from Waveplus.DaqSys.Definitions import * # type: ignore
from Waveplus.DaqSys.Exceptions import * # type: ignore
from CyUSB import * # type: ignore


class CometaDaqSystem(DaqSystem):  # type: ignore
  """Cometa 采集系统包装类。

  主要能力：
  - 设备状态与错误查询
  - 采集配置读写与采集控制（启动/停止/触发）
  - 传感器通道管理（启停、配置、LED 控制、阻抗检测等）
  - 事件订阅（状态变化、数据到达、内存数据到达）
  - 版本信息与 RF 通道读写
  """
  def get_state(self) -> DeviceStateEnum:
    """获取当前设备状态。"""
    return self.get_State()

  def get_initial_error(self) -> DeviceErrorEnum:
    """获取设备初始化时的错误码（若有）。"""
    return self.get_InitialError()
  
  def get_type(self) -> Iterable[SensorTypeEnum]:
    """获取已安装传感器的类型集合。""" 
    return self.get_Type()

  def set_capture_configuration(self, capture_config: CometaCaptureConfiguration) -> None:
    """设置采集配置。"""
    self.ConfigureCapture(capture_config)

  def get_capture_configuration(self) -> CometaCaptureConfiguration:
    """读取当前采集配置。"""
    return self.CaptureConfiguration()

  def start_capturing(self, event_period: DataAvailableEventPeriodEnum) -> None:
    """按指定事件周期开始采集并触发 DataAvailable 事件。"""
    self.StartCapturing(event_period)

  def stop_capturing(self) -> None:
    """停止采集。"""
    self.StopCapturing()

  def generate_start_trigger(self) -> None:
    """生成内部开始触发（用于同步）。"""
    self.GenerateInternalStartTrigger()

  def generate_stop_trigger(self) -> None:
    """生成内部停止触发（用于同步）。"""
    self.GenerateInternalStopTrigger()

  def get_firmware_version(self) -> Iterable[CometaVersion]:
    """获取固件版本信息。"""
    return self.get_FirmwareVersion()

  def get_hardware_version(self) -> Iterable[CometaVersion]:
    """获取硬件版本信息。"""
    return self.get_HardwareVersion()

  def get_software_version(self) -> CometaExtVersion:
    """获取软件/SDK 版本信息（含构建与修订）。"""
    return self.get_SoftwareVersion()

  def get_num_installed_sensors(self) -> int:
    """读取已安装传感器数量。"""
    return self.get_InstalledSensors()

  def get_num_installed_fsw_sensors(self) -> int:
    """读取已安装足底开关（FSW）传感器数量。"""
    return self.get_InstalledFootSwSensors()

  def enable_sensor(self, sensor_id: int) -> None:
    """启用指定 `sensor_id` 的传感器通道。"""
    self.EnableSensor(sensor_id)

  def disable_sensor(self, sensor_id: int) -> None:
    """禁用指定 `sensor_id` 的传感器通道。"""
    self.DisableSensor(sensor_id)

  def enable_fsw_sensors(self) -> None:
    """启用全部足底开关（FSW）通道。"""
    self.EnableFootSwSensors()

  def disable_fsw_sensors(self) -> None:
    """禁用全部足底开关（FSW）通道。"""
    self.DisableFootSwSensors()

  def set_sensor_configuration(self, sensor_config: CometaSensorConfiguration, sensor_id: int) -> None:
    """为指定 `sensor_id` 设置传感器配置。"""
    self.ConfigureSensor(sensor_config, sensor_id)

  def get_sensor_configuration(self, sensor_id: int) -> CometaSensorConfiguration:
    """读取指定 `sensor_id` 的传感器配置。"""
    return self.SensorConfiguration(sensor_id)

  def detect_accelerometer_offset(self, sensor_id: int) -> None:
    """执行加速度计零偏检测/校准。"""
    self.DetectAccelerometerOffset(sensor_id)

  def check_impedance(self, sensor_id: int) -> Iterable[SensorCheckReportEnum]:
    """检测电极阻抗，返回报告结果。"""
    return self.CheckElectrodeImpedance(sensor_id)

  def turn_led_on(self, sensor_id: int) -> None:
    """点亮指定 `sensor_id` 传感器的 LED。"""
    self.TurnSensorLedOn(sensor_id)

  def turn_all_leds_on(self) -> None:
    """点亮所有传感器的 LED。"""
    self.TurnAllSensorLedsOn()

  def turn_all_leds_off(self) -> None:
    """关闭所有传感器的 LED。"""
    self.TurnAllSensorLedsOff()

  def get_device_dependent_functionalities(self) -> Iterable[CometaDeviceDependentFunctionalities]:
    """查询设备依赖功能的可用性。"""
    return self.get_DeviceDependentFunctionalities()

  def add_on_state_changed_handler(self, callback: Callable[[Any, CometaDeviceStateChangedEventArgs], None]) -> None:
    """注册设备状态变化回调。"""
    self.StateChanged += callback

  def remove_on_state_changed_handler(self, callback: Callable[[Any, CometaDeviceStateChangedEventArgs], None]) -> None:
    """移除设备状态变化回调。"""
    self.remove_StateChanged(callback)

  def add_on_data_available_handler(self, callback: Callable[[Any, CometaDataAvailableEventArgs], None]) -> None:
    """注册数据到达回调。"""
    self.DataAvailable += callback

  def remove_on_data_available_handler(self, callback: Callable[[Any, CometaDataAvailableEventArgs], None]) -> None:
    """移除数据到达回调。"""
    self.remove_DataAvailable(callback)

  def add_on_sensor_memory_data_available_handler(self, callback: Callable[[Any, CometaSensorMemoryDataAvailableEventArgs], None]) -> None:
    """注册传感器内存数据到达回调（离线读取）。"""
    self.SensorMemoryDataAvailable += callback

  def remove_on_sensor_memory_data_available_handler(self, callback: Callable[[Any, CometaSensorMemoryDataAvailableEventArgs], None]) -> None:
    """移除传感器内存数据到达回调。"""
    self.remove_SensorMemoryDataAvailable(callback)

  def start_selective_memory_reading(self, trial_id: int) -> None:
    """按 `trial_id` 开始选择性内存读取。"""
    self.StartSensorSelectiveMemoryReading(trial_id)

  def stop_selective_memory_reading(self) -> None:
    """停止传感器内存读取。"""
    self.StopSensorMemoryReading()

  def dispose(self) -> None:
    """释放底层资源（与 .NET Dispose 对应）。"""
    self.Dispose()

  def get_master_device_rf_channel(self, device_id: int) -> RFChannelEnum:
    """读取主设备 RF 信道。"""
    return self.DeviceRFChannel(device_id)

  def set_master_device_rf_channel(self, channel: RFChannelEnum, device_id: int) -> None:
    """设置主设备 RF 信道。"""
    self.ChangeDeviceRFChannel(channel, device_id)

  def set_semsor_rf_channel(self, channel: RFChannelEnum, device_id) -> None:
    """设置所有传感器 RF 信道。"""
    self.ChangeSensorsRFChannel(channel, device_id)

  def write_sync_data(self, data: float, absolute_value: bool) -> None:
    """写入同步通道数据。

    参数：
    - data: 同步值。
    - absolute_value: 是否使用绝对值。
    """
    self.WriteSyncData(data, absolute_value)
