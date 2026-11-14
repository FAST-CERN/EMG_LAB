from dataclasses import asdict, dataclass


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
