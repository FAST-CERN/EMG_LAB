"""Shared causal preprocessing, ONNX sliding windows and stable four-state output."""
from __future__ import annotations
import numpy as np
import onnxruntime as ort
from .signal import SignalConfig, SignalFilter, compatible_profile, window_samples
from .storage import read_json, CLASSES
from .tasks import task_from_metadata, require_task


class StableCommand:
    def __init__(self, threshold=.65, hold=3):
        if not np.isfinite(threshold) or not 0 <= threshold <= 1 or int(hold) != hold or hold < 1:
            raise ValueError('模型的指令判定参数无效。')
        self.threshold, self.hold = threshold, hold
        self.candidate = self.command = self.count = 0

    @property
    def settings(self):
        return dict(threshold=float(self.threshold), hold=int(self.hold))

    def update(self, probabilities):
        p = np.asarray(probabilities)
        chosen = int(np.argmax(p)) if np.max(p) >= self.threshold else 0
        self.count = self.count+1 if chosen==self.candidate else 1
        self.candidate = chosen
        # Low confidence and REST stop immediately; movements require persistence.
        if chosen==0 or self.count >= self.hold:
            self.command = chosen
        elif chosen != self.command:
            self.command = 0
        return self.command


class InferencePipeline:
    def __init__(self, folder, profile, *, metadata=None):
        from pathlib import Path
        self.folder = Path(folder)
        # Training evaluates a ready ONNX file before publishing its manifest.
        self.meta = metadata if metadata is not None else read_json(self.folder/'metadata.json')
        self.task = task_from_metadata(self.meta)
        if not self.meta.get('complete') or self.meta.get('classes') != list(self.task.classes) or self.meta.get('signal_type') != 'emg':
            raise ValueError('无法使用这个模型。请选择本软件训练并保存的模型。')
        if 'record_id' in profile or 'task_type' in profile:
            require_task(profile,self.task)
        if not compatible_profile(profile,self.meta):
            raise ValueError('模型与数据不匹配：请核对设备、通道编号/顺序、采样率和单位。')
        self.config = SignalConfig(**self.meta['preprocessing'])
        self.filter = SignalFilter(profile['sampling_rate'],len(profile['channel_ids']),self.config)
        self.window, self.step = window_samples(profile['sampling_rate'],self.config)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(self.folder/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.buffer = np.empty((0,len(profile['channel_ids'])),dtype=np.float32)
        self.stable = StableCommand(**self.meta.get('decision', {}))
        self.window_end = self.window

    def feed(self, samples):
        filtered = self.filter.process(samples)
        self.buffer = np.concatenate((self.buffer,filtered))
        results = []
        while len(self.buffer) >= self.window:
            x = self.buffer[:self.window].T[np.newaxis].astype(np.float32)
            logits = self.session.run(None,{self.input_name:x})[0][0]
            if logits.shape != (len(self.task.classes),) or not np.isfinite(logits).all():
                raise ValueError('模型输出的类别数或数值无效。')
            p = np.exp(logits-logits.max())
            p /= p.sum()
            command = self.stable.update(p)
            results.append(dict(probabilities=p.tolist(), raw_class=int(p.argmax()),
                                filtered_class=command, sample_end=self.window_end))
            self.buffer = self.buffer[self.step:]
            self.window_end += self.step
        return results
