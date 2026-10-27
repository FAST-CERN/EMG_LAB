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
事件参数包装。

为 .NET 事件（状态变化、数据到达、内存数据到达）提供 Python 友好的
属性访问方法，便于在回调中直接读取所需数据。
"""

from typing import Iterable
import clr
import os
dir_path = os.path.dirname(__file__)

clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSys')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSysInterface')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'CyUSB')) # type: ignore

from .constants import DeviceErrorEnum, DeviceStateEnum, SensorStateEnum

from Waveplus.DaqSys import * # type: ignore
from Waveplus.DaqSysInterface import * # type: ignore
from Waveplus.DaqSys.Definitions import * # type: ignore
from Waveplus.DaqSys.Exceptions import * # type: ignore
from CyUSB import * # type: ignore


class CometaCommandProgressEventArgs(CommandProgressEventArgs):  # type: ignore
  """命令进度事件参数包装。"""
  def get_progress(self) -> int:
    """返回进度百分比。"""
    return self.ProgressInPercent 


class CometaDeviceStateChangedEventArgs(DeviceStateChangedEventArgs):  # type: ignore
  """设备状态变化事件参数包装。"""
  def get_state(self) -> DeviceStateEnum:
    """返回新的设备状态。"""
    return self.State


class CometaDataAvailableEventArgs(DataAvailableEventArgs):  # type: ignore
  """数据到达事件参数包装（在线采集）。"""
  def scan_number(self) -> int:
    """当前扫描/帧序号。"""
    return self.ScanNumber
  
  def get_emg_samples(self) -> Iterable[Iterable[float]]:
    """EMG 数据：维度为 [通道][样本]。"""
    return self.Samples

  def get_orientation_samples(self) -> Iterable[Iterable[tuple[float, float, float, float]]]:
    """IMU 四元数（仅 FUSED/MIXED_6DOF_142HZ 可用）。"""
    return self.ImuSamples

  def get_accelerometer_samples(self) -> Iterable[Iterable[tuple[float, float, float]]]:
    """IMU 加速度计原始数据（仅 RAW/MIXED_6DOF_142HZ 可用）。"""
    return self.AccelerometerSamples

  def get_gyroscope_samples(self) -> Iterable[Iterable[tuple[float, float, float]]]:
    """IMU 陀螺仪原始数据（仅 RAW/MIXED_6DOF_142HZ 可用）。"""
    return self.GyroscopeSamples

  def get_magnetometer_samples(self) -> Iterable[Iterable[tuple[float, float, float]]]:
    """IMU 磁力计原始数据（仅 RAW/MIXED_6DOF_142HZ 可用）。"""
    return self.MagnetometerSamples

  def get_sync_samples(self):
    """同步通道数据。"""
    return self.SyncSamples

  def get_sensor_states(self) -> Iterable[Iterable[SensorStateEnum]]:
    """传感器电量/状态（FUSED 模式不可用）。"""
    return self.SensorStates

  def get_fsw_samples(self) -> Iterable[tuple[int, int]]:
    """足底开关（FSW）样本。"""
    return self.FootSwSamples

  def get_fsw_raw_samples(self) -> Iterable[tuple[int, int]]:
    """足底开关（FSW）原始样本。"""
    return self.FootSwRawSamples

  def get_fsw_sensor_states(self) -> Iterable[Iterable[SensorStateEnum]]:
    """FSW 传感器状态。"""
    return self.FootSwSensorStates

  def is_start_trigger_detected(self) -> bool:
    """是否检测到开始触发。"""
    return self.StartTriggerDetected

  def is_stop_trigger_detected(self) -> bool:
    """是否检测到停止触发。"""
    return self.StopTriggerDetected

  def start_trigger_scan(self) -> int:
    """开始触发对应的扫描序号。"""
    return self.StartTriggerScan

  def stop_trigger_scan(self) -> int:
    """停止触发对应的扫描序号。"""
    return self.StopTriggerScan

  def get_transfer_rate(self) -> int:
    """数据传输速率。"""
    return self.DataTransferRate

  def get_sensor_rf_lost_packets(self) -> Iterable[int]:
    """各传感器 RF 丢包计数。"""
    return self.SensorRFLostPackets

  def get_usb_lost_packets(self) -> int:
    """USB 丢包计数。"""
    return self.USBLostPackets


class CometaSensorMemoryDataAvailableEventArgs(SensorMemoryDataAvailableEventArgs):  # type: ignore
  """传感器内存数据事件参数包装（离线/回放）。"""
  def get_num_samples(self) -> int:
    """本次到达的样本帧数量。"""
    return self.SamplesNumber

  def get_emg_samples(self) -> Iterable[Iterable[float]]:
    """EMG 数据：维度为 [通道][样本]。"""
    return self.Samples

  def get_orientation_samples(self) -> Iterable[Iterable[tuple[float, float, float, float]]]:
    """IMU 四元数。"""
    return self.ImuSamples

  def get_accelerometer_samples(self) -> Iterable[Iterable[tuple[float, float, float]]]:
    """IMU 加速度计原始数据。"""
    return self.AccelerometerSamples

  def get_gyroscope_samples(self) -> Iterable[Iterable[tuple[float, float, float]]]:
    """IMU 陀螺仪原始数据。"""
    return self.GyroscopeSamples

  def get_magnetometer_samples(self) -> Iterable[Iterable[tuple[float, float, float]]]:
    """IMU 磁力计原始数据。"""
    return self.MagnetometerSamples

  def get_sensor_states(self) -> Iterable[Iterable[SensorStateEnum]]:
    """传感器状态。"""
    return self.SensorStates

  def get_fsw_samples(self) -> Iterable[tuple[int, int]]:
    """足底开关（FSW）样本。"""
    return self.FootSwSamples

  def get_fsw_raw_samples(self) -> Iterable[tuple[int, int]]:
    """足底开关（FSW）原始样本。"""
    return self.FootSwRawSamples

  def get_fsw_sensor_states(self) -> Iterable[Iterable[SensorStateEnum]]:
    """FSW 传感器状态。"""
    return self.FootSwSensorStates

  def is_trial_end(self) -> bool:
    """是否为试次/段落结束标记。"""
    return self.TrialEnd
  
  def get_num_saved_trials(self) -> int:
    """已保存的试次数。"""
    return self.SavedTrialsNumber
  
  def get_transfer_progress(self) -> int:
    """整体传输进度（百分比）。"""
    return self.TransferredSamplesInPercent

  def get_current_trial_transfer_progress(self) -> int:
    """当前试次的传输进度（百分比）。"""
    return self.CurrentTrialTransferredSamplesInPercent

  def get_current_trial_id(self) -> int:
    """当前试次 ID。"""
    return self.CurrentTrial
  
  def get_transfer_rate(self) -> int:
    """数据传输速率。"""
    return self.DataTransferRate

  def get_sensor_lost_packets(self) -> Iterable[int]:
    """各传感器丢包计数。"""
    return self.SensorLostPackets
  
  def get_error_code(self) -> DeviceErrorEnum:
    """错误码（若发生错误）。"""
    return self.ErrorCode
  
  def get_lost_packets(self) -> int:
    """总丢包计数。"""
    return self.LostPackets
