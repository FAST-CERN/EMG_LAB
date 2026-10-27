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
采集配置包装（CaptureConfiguration）。

封装采样率、外部触发、足底开关（FSW）通道开关与阈值、FSW 协议、
以及 IMU 采样模式等配置项。
"""

import clr
import os
dir_path = os.path.dirname(__file__)

from .constants import ImuAcqTypeEnum, FootSwProtocolEnum, SamplingRateEnum
from .foot_sw_transducer import CometaFootSwTransducerEnabled, CometaFootSwTransducerThreshold

clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSys')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSysInterface')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'CyUSB')) # type: ignore

from Waveplus.DaqSys import * # type: ignore
from Waveplus.DaqSysInterface import * # type: ignore
from Waveplus.DaqSys.Definitions import * # type: ignore
from Waveplus.DaqSys.Exceptions import * # type: ignore
from CyUSB import * # type: ignore


class CometaCaptureConfiguration(CaptureConfiguration):  # type: ignore
  """采集配置的 Python 包装。"""
  def get_sampling_rate(self) -> SamplingRateEnum:
    """读取 EMG 采样率设置。"""
    return self.get_SamplingRate()

  def set_sampling_rate(self, rate: SamplingRateEnum) -> None:
    """设置 EMG 采样率。"""
    self.set_SamplingRate(rate)

  def get_external_trigger_status(self) -> bool:
    """是否启用外部触发。"""
    return self.get_ExternalTriggerEnabled()

  def set_external_trigger_status(self, is_enabled: bool) -> None:
    """启用/关闭外部触发。"""
    self.set_ExternalTriggerEnabled(is_enabled)

  def get_trigger_level(self) -> int:
    """获取外部触发电平。"""
    return self.get_ExternalTriggerActiveLevel()

  def set_trigger_level(self, level: int) -> None:
    """设置外部触发电平。"""
    self.set_ExternalTriggerActiveLevel(level)

  def get_fsw_a_is_enabled(self) -> CometaFootSwTransducerEnabled:
    """读取 FSW A 通道启用状态对象。"""
    return self.get_FootSwATransducerEnabled()
  
  def set_fsw_a_is_enabled(self, fsw_transducer_enabled: CometaFootSwTransducerEnabled) -> None:
    """设置 FSW A 通道启用状态。"""
    self.set_FootSwATransducerEnabled(fsw_transducer_enabled)

  def get_fsw_a_threshold(self) -> CometaFootSwTransducerEnabled:
    """读取 FSW A 通道阈值对象。"""
    return self.get_FootSwATransducerThreshold()
  
  def set_fsw_a_threshold(self, fsw_transducer_threshold: CometaFootSwTransducerThreshold) -> None:
    """设置 FSW A 通道阈值。"""
    self.set_FootSwATransducerThreshold(fsw_transducer_threshold)

  def get_fsw_b_is_enabled(self) -> CometaFootSwTransducerEnabled:
    """读取 FSW B 通道启用状态对象。"""
    return self.get_FootSwBTransducerEnabled()

  def set_fsw_b_is_enabled(self, fsw_transducer_enabled: CometaFootSwTransducerEnabled) -> None:
    """设置 FSW B 通道启用状态。"""
    self.set_FootSwBTransducerEnabled(fsw_transducer_enabled)

  def get_fsw_b_threshold(self) -> CometaFootSwTransducerThreshold:
    """读取 FSW B 通道阈值对象。"""
    return self.get_FootSwBTransducerThreshold()
  
  def set_fsw_b_threshold(self, fsw_transducer_threshold: CometaFootSwTransducerThreshold) -> None:
    """设置 FSW B 通道阈值。"""
    self.set_FootSwBTransducerThreshold(fsw_transducer_threshold)

  def get_fsw_protocol(self) -> FootSwProtocolEnum:
    """读取 FSW 协议。"""
    return self.get_FootSwProtocol()

  def set_fsw_protocol(self, protocol: FootSwProtocolEnum) -> None:
    """设置 FSW 协议。"""
    self.set_FootSwProtocol(protocol)

  def get_imq_acq_type(self) -> ImuAcqTypeEnum:
    """读取 IMU 采样模式。"""
    return self.get_IMU_AcqType()

  def set_imu_acq_type(self, acq_type: ImuAcqTypeEnum) -> None:
    """设置 IMU 采样模式。"""
    self.set_IMU_AcqType(acq_type)
