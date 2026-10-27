"""One causal filter implementation for preview, training and online inference."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np
from scipy.signal import butter, iirnotch, tf2sos, sosfilt


@dataclass(frozen=True)
class SignalConfig:
    bandpass: bool = True
    notch: bool = True
    low_hz: float = 20.0
    high_hz: float = 450.0
    notch_hz: float = 50.0
    window_s: float = 0.5
    step_s: float = 0.1

    def to_dict(self):
        return asdict(self)


class SignalFilter:
    def __init__(self, rate: float, channels: int, config: SignalConfig):
        if not np.isfinite(rate) or rate < 100 or channels < 1:
            raise ValueError('无效采样率或通道数。')
        self.channels = channels
        filters = []
        if config.bandpass:
            high = min(config.high_hz, rate * .45)
            if not 0 < config.low_hz < high:
                raise ValueError('滤波频带超出采样率允许范围。')
            filters.append(butter(4, [config.low_hz, high], btype='bandpass', fs=rate, output='sos'))
        if config.notch:
            if not 0 < config.notch_hz < rate/2:
                raise ValueError('陷波频率必须低于 Nyquist 频率。')
            filters.append(tf2sos(*iirnotch(config.notch_hz, 30, fs=rate)))
        self.sos = np.vstack(filters) if filters else None
        self.zi = np.zeros((len(self.sos), 2, channels)) if self.sos is not None else None

    def process(self, samples):
        x = np.asarray(samples, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != self.channels or not np.isfinite(x).all():
            raise ValueError('信号通道不一致或出现 NaN/Inf。')
        if not len(x):
            return x.astype(np.float32)
        if self.sos is None:
            return x.astype(np.float32)
        y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y.astype(np.float32)


def window_samples(rate, config):
    window, step = round(rate * config.window_s), round(rate * config.step_s)
    if not 4 <= window or not 1 <= step <= window:
        raise ValueError('滑窗长度或步长无效。')
    return window, step


def compatible_profile(a, b):
    for key in ('channel_ids', 'unit', 'device'):
        if a.get(key) != b.get(key):
            names = {'channel_ids':'传感器编号或顺序','unit':'信号单位','device':'设备类型'}
            raise ValueError(f'所选模型与数据的{names[key]}不同。请使用训练时的设备和传感器，或重新选择模型。')
    if not np.isclose(a['sampling_rate'], b['sampling_rate'], rtol=1e-6, atol=1e-6):
        raise ValueError('模型与数据采样率不匹配，请重新选择数据或训练模型。')
    return True
