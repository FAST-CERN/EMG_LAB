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
传感器配置包装（SensorConfiguration）。

用于设置单个传感器的类型、加速度计/陀螺仪量程等。
"""

import clr
import os
dir_path = os.path.dirname(__file__)

clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSys')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSysInterface')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'CyUSB')) # type: ignore

from .constants import AccelerometerFullScaleEnum, GyroscopeFullScaleEnum, SensorTypeEnum

from Waveplus.DaqSys import * # type: ignore
from Waveplus.DaqSysInterface import * # type: ignore
from Waveplus.DaqSys.Definitions import * # type: ignore
from Waveplus.DaqSys.Exceptions import * # type: ignore
from CyUSB import * # type: ignore


class CometaSensorConfiguration(SensorConfiguration):  # type: ignore
  """单传感器配置的 Python 包装。"""
  def get_sensor_type(self) -> SensorTypeEnum:
    """读取传感器类型（EMG/IMU/FSW/模拟）。"""
    return self.get_SensorType()

  def set_sensor_type(self, sensor_type: SensorTypeEnum) -> None:
    """设置传感器类型。"""
    self.set_SensorType(sensor_type)

  def get_accelerometer_full_scale(self) -> AccelerometerFullScaleEnum:
    """读取加速度计量程。"""
    return self.get_AccelerometerFullScale()

  def set_accelerometer_full_scale(self, full_scale: AccelerometerFullScaleEnum) -> None:
    """设置加速度计量程。"""
    self.set_AccelerometerFullScale(full_scale)

  def get_gyroscope_full_scale(self) -> GyroscopeFullScaleEnum:
    """读取陀螺仪量程。"""
    return self.get_GyroscopeFullScale()

  def set_gyroscope_full_scale(self, full_scale: GyroscopeFullScaleEnum) -> None:
    """设置陀螺仪量程。"""
    self.set_GyroscopeFullScale(full_scale)
