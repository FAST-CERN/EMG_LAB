"""CPU Decoupled WBC, adapted from NVIDIA and FAST-CERN/Teleopit.

Observation layout, history, gains and action transform preserve upstream semantics.
See SOURCE_PROVENANCE.json and licenses/ for original revisions and licenses.
"""
from collections import deque
from pathlib import Path
import numpy as np
import onnxruntime as ort

DEFAULT = np.array([-.1, 0, 0, .3, -.2, 0, -.1, 0, 0, .3, -.2, 0, 0, 0, 0] + [0.]*14)
KP = np.array([150,150,150,200,40,40,150,150,150,200,40,40,250,250,250] + [100.]*14)
KD = np.array([2,2,2,4,2,2,2,2,2,4,2,2,5,5,5] + [.5]*14)


class DecoupledPolicy:
    def __init__(self, asset_root):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.add_session_config_entry('session.intra_op.allow_spinning', '0')
        self.sessions = {}
        for name in ('Balance', 'Walk'):
            path = Path(asset_root)/'policies'/f'GR00T-WholeBodyControl-{name}.onnx'
            if not path.is_file():
                raise FileNotFoundError('缺少机器人模型，请先运行 install.cmd。')
            session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
            if session.get_inputs()[0].shape[-1] != 516 or session.get_outputs()[0].shape[-1] != 15:
                raise ValueError('机器人模型与控制接口不匹配。')
            self.sessions[name] = session
        self.reset()

    def reset(self):
        self.history = deque([np.zeros(86, dtype=np.float32) for _ in range(6)], maxlen=6)
        self.action = np.zeros(15, dtype=np.float32)
        self.last_policy = 'Balance'

    def observation(self, qpos, qvel, gravity_body, command):
        frame = np.zeros(86, dtype=np.float32)
        frame[:3] = np.asarray(command)*[2.,2.,.5]
        frame[3] = .74
        frame[7:10] = qvel[3:6]*.5
        frame[10:13] = gravity_body
        frame[13:42] = qpos[7:36]-DEFAULT
        frame[42:71] = qvel[6:35]*.05
        frame[71:86] = self.action
        self.history.append(frame)
        return np.concatenate(self.history)[None]

    def target(self, qpos, qvel, gravity_body, command):
        self.last_policy = 'Balance' if np.linalg.norm(command) < .05 else 'Walk'
        observation = self.observation(qpos, qvel, gravity_body, command)
        session = self.sessions[self.last_policy]
        action = session.run(None, {session.get_inputs()[0].name: observation})[0].reshape(15)
        if not np.isfinite(action).all():
            raise RuntimeError('机器人模型输出异常，请重置场景。')
        self.action = action.copy()
        target = DEFAULT.copy()
        target[:15] += .25*action
        return target
