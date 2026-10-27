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
设备依赖功能可用性查询。

某些功能仅在特定设备/固件或工作状态下可用，本模块对可用性查询
接口进行薄封装。
"""

import clr
import os
dir_path = os.path.dirname(__file__)

clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSys')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'Waveplus.DaqSysInterface')) # type: ignore
clr.AddReference(os.path.join(dir_path, 'lib', 'CyUSB')) # type: ignore

from Waveplus.DaqSys import * # type: ignore
from Waveplus.DaqSysInterface import * # type: ignore
from Waveplus.DaqSys.Definitions import * # type: ignore
from Waveplus.DaqSys.Exceptions import * # type: ignore
from CyUSB import * # type: ignore


# NOTE: properties accessible when DAQ is in 'Idle', 'Capturing' or 'ReadingSensorMemory' states. 
class CometaDeviceDependentFunctionalities(DeviceDependentFunctionalities):  # type: ignore
  """设备依赖功能集合包装。"""
  def is_rf_freq_setting_supported(self) -> bool:
    """是否支持设置 RF 频率/信道。"""
    return self.get_RfFrequencySettingSupported()

  def is_selective_mem_reading_supported(self) -> bool:
    """是否支持选择性读取传感器内存（按试次）。"""
    return self.get_SelectiveMemoryReadingSupported()
