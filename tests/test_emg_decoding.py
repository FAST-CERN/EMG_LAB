"""Two independent muscles must remain distinguishable through final commands."""
import numpy as np
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.training import train
from emg_lab.inference import InferencePipeline
from emg_lab.storage import read_json, read_recording


def test_two_leg_emg_distinguishes_single_and_both_muscles(tmp_path):
    profile = dict(device='模拟练习', sampling_rate=2000., channel_ids=[1,2], unit='a.u.')
    capture = CaptureRun(tmp_path,'TEST','双腿四动作',profile,SignalConfig(),trial_count=6)
    rng = np.random.default_rng(37)
    amplitudes = np.array([[15.,3.], [15.,53.], [65.,3.], [65.,53.]])
    while not capture.completed:
        cls = capture.status()['command']
        # The same noisy muscle is active for left and forward. Only the other
        # channel says whether this is one leg or both; vary effort over time.
        gain = amplitudes[cls]*rng.uniform(.7,1.3,2)
        capture.feed((rng.normal(size=(200,2))*gain).astype(np.float32))
    folder = train(dict(recordings=[capture.run_path],data_root=tmp_path,name='双腿回归',epochs=30))
    meta = read_json(folder/'metadata.json')
    profile,raw,labels = read_recording(capture.run_path)
    trials = {r['trial'] for r in meta['split']['test']}
    cm = np.zeros((4,4),int)
    for result in InferencePipeline(folder,profile).feed(raw):
        end = result['sample_end']
        for label in labels:
            if label['trial'] in trials and label['start_sample']+400 <= end-1000 and end<=label['end_sample']:
                cm[label['class_id'],result['filtered_class']] += 1
    recall = cm.diagonal()/cm.sum(1)
    assert min(recall[1],recall[3]) >= .85, f'Left/forward final-command recall: {recall.tolist()}; confusion: {cm.tolist()}'
