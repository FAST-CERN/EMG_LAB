from pathlib import Path
import numpy as np
import pytest
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig


@pytest.fixture
def profile():
    return dict(device='模拟练习',sampling_rate=1000.,channel_ids=[1,2,3,4],unit='a.u.')


def synthesize(root, profile, name='模拟数据', trial_count=3):
    capture = CaptureRun(Path(root),'TEST',name,profile,SignalConfig(),trial_count=trial_count,action_s=1.2)
    rng = np.random.default_rng(73)
    while not capture.completed:
        cue = capture.status()['command']
        gain = np.full(len(profile['channel_ids']),.03)
        if cue:
            gain[(cue-1)%len(gain)] = 1.
        capture.feed((rng.normal(size=(20,len(gain)))*gain).astype(np.float32))
    return [capture.run_path]


@pytest.fixture
def records(tmp_path,profile):
    return synthesize(tmp_path,profile)
