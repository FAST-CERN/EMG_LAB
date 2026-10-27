"""One session file, with N trials containing each of the four actions once."""
from __future__ import annotations
import math
import numpy as np
from .storage import RecordingWriter, new_run, CLASSES
from .tasks import ROBOT

PREPARE_SECONDS = 3.
ACTION_SECONDS = 5.
REST_SECONDS = 0.


def preparation_countdown(status):
    """Match the host: show zero in the last 0.3 s, without extending preparation."""
    if status.get('done') or status.get('phase') != '准备':
        return None
    remaining = status['remaining']
    return 0 if remaining <= .3 else math.ceil(remaining)


class CaptureRun:
    ACTION_ORDER = (3, 0, 1, 2)  # forward, stop, left, right; wire IDs stay unchanged.

    def __init__(self, root, group, name, profile, config, trial_count=5,
                 action_s=ACTION_SECONDS, prepare_s=PREPARE_SECONDS, rest_s=REST_SECONDS, task=ROBOT,
                 random_order=False, collection_notes=None):
        if int(trial_count) != trial_count or trial_count < 1:
            raise ValueError('请设置至少 1 组动作。')
        if action_s < config.window_s + .2 or prepare_s < 0 or rest_s < 0:
            raise ValueError('每个动作至少持续 1 秒，准备和休息时间不能为负数。')
        self.task = task
        self.rejected_trials = {}
        self.action_order = task.order
        self.action_count = len(task.classes)
        self.rate = float(profile['sampling_rate'])
        self.trial_count = int(trial_count)
        self.completed = self.stopped = False
        self.received = 0
        self.prepare = round(self.rate*prepare_s)
        self.action = round(self.rate*action_s)
        self.rest = round(self.rate*rest_s)
        self.segment_length = self.prepare+self.action+self.rest
        self.trial_length = self.action_count*self.segment_length
        self.session_length = self.trial_count*self.trial_length
        self.order = np.tile(self.action_order,self.trial_count)
        seed = int(np.random.SeedSequence().entropy) if random_order else None
        if random_order:
            rng=np.random.default_rng(seed)
            self.order=np.concatenate([rng.permutation(self.action_order) for _ in range(self.trial_count)])
        metadata = dict(profile, group=group.strip(), name=name.strip(), preprocessing=config.to_dict(),
            schema_version=2,trial_count=self.trial_count,action_order=list(self.action_order),
            action_seconds=action_s,prepare_seconds=prepare_s,rest_seconds=rest_s,
            random_order=bool(random_order),order_seed=seed,actual_order=self.order.tolist(),
            collection_notes=dict(collection_notes or {}),rejected_trials=[], **task.metadata)
        folder = new_run(root,group,name,metadata)
        labels = []
        for segment,cls in enumerate(self.order):
            start = segment*self.segment_length+self.prepare
            labels.append(dict(trial=segment//self.action_count+1,start_sample=start,end_sample=start+self.action,
                               class_id=int(cls),class_name=task.classes[int(cls)]))
        self.writer = RecordingWriter(folder,metadata,labels,bundle=True)
        self.run_path = self.writer.output_path

    def status(self):
        if self.completed or self.stopped:
            return dict(done=True,command=0,phase='完成' if self.completed else '已结束',
                        progress=self.received/self.session_length,trial_count=self.trial_count)
        count = self.writer.count
        segment = count//self.segment_length
        within = count%self.segment_length
        phase = '准备' if within < self.prepare else '动作' if within < self.prepare+self.action else '休息'
        command = int(self.order[segment]) if phase=='动作' else 0
        remaining = (self.prepare-within if phase=='准备' else self.prepare+self.action-within if phase=='动作' else self.segment_length-within)/self.rate
        return dict(done=False,command=command,cue=int(self.order[segment]),phase=phase,
                    rejected=(segment//self.action_count+1) in self.rejected_trials,
                    trial=segment//self.action_count+1,trial_count=self.trial_count,action_index=segment%self.action_count+1,
                    action_count=self.action_count,
                    remaining=remaining,progress=self.received/self.session_length)

    def feed(self, samples):
        if not self.completed and not self.stopped:
            n = min(len(samples),self.session_length-self.writer.count)
            self.writer.append(samples[:n])
            self.received += n
            if self.received == self.session_length:
                self.writer.close(complete=True)
                self.completed = True
        return self.status()

    def stop(self):
        if not self.completed and not self.stopped:
            self.writer.close(complete=False)
            self.stopped = True

    def reject_trial(self,trial,reason):
        if self.completed or self.stopped or self.writer.handle.closed:
            raise ValueError('本次采集已经结束，不能再标记当前组。')
        if type(trial) is not int or not 1<=trial<=self.status()['trial']:
            raise ValueError('只能标记本次已经开始的动作组。')
        self.rejected_trials[trial]=str(reason).strip()[:200] or '人工标记'
        self.writer.meta['rejected_trials']=[dict(trial=t,reason=r) for t,r in sorted(self.rejected_trials.items())]
