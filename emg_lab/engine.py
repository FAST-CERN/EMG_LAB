"""Thread-safe session state. Device callbacks never touch Qt widgets."""
from __future__ import annotations
import csv
from datetime import datetime
from pathlib import Path
import threading
import time
import uuid
import numpy as np
from .capture import CaptureRun, ACTION_SECONDS
from .inference import InferencePipeline
from .signal import SignalConfig, SignalFilter
from .storage import DATA_ROOT, read_recording, safe_name, write_json, read_json, excluded_trials
from .tasks import ROBOT, require_task
from .practice import BasicAssessment, report_html


class Session:
    def __init__(self, root=DATA_ROOT, task=ROBOT):
        self.task = task
        self.root = Path(root)
        self.lock = threading.RLock()
        self.profile = None
        self.config = SignalConfig()
        self.capture = None
        self.inference = None
        self.last_frame = 0.
        self.result = None
        self.raw = self.filtered = np.empty((0,0),dtype=np.float32)
        self.replay_stop = threading.Event()
        self.replay_thread = None
        self.replay_done = False
        self.source = 'live'
        self.prediction_file = None
        self.dds = None
        self.error = ''
        self.assessment = None
        self.last_assessment_path = None

    def set_profile(self, profile):
        with self.lock:
            self.profile = dict(profile)
            self.set_filter(self.config)
            self.last_frame = time.monotonic()

    def set_filter(self, config):
        with self.lock:
            if self.inference or self.capture:
                raise ValueError('请先停止当前任务，再修改滤波设置。')
            self.config = config
            if self.profile:
                self.preview_filter = SignalFilter(self.profile['sampling_rate'],len(self.profile['channel_ids']),config)
                self.raw = self.filtered = np.empty((0,len(self.profile['channel_ids'])),dtype=np.float32)

    def feed(self, samples):
        with self.lock:
            self.last_frame = time.monotonic()
            filtered = self.preview_filter.process(samples)
            keep = round(self.profile['sampling_rate']*10)
            self.raw = np.concatenate((self.raw,samples))[-keep:]
            self.filtered = np.concatenate((self.filtered,filtered))[-keep:]
            if self.capture:
                self.capture.feed(samples)
            if self.inference:
                results=self.inference.feed(samples)
                if self.assessment:
                    self.assessment.feed(results,len(samples))
                for result in results:
                    self.result = result
                    if self.prediction_file:
                        self.prediction_writer.writerow([result['sample_end']/self.profile['sampling_rate'],
                            result['raw_class'],result['filtered_class'],*result['probabilities']])
                    if self.dds:
                        self.dds.update(result)

    def start_capture(self, group, name, trial_count=5, action_s=ACTION_SECONDS, random_order=False, collection_notes=None):
        with self.lock:
            if not self.profile or self.inference or self.capture:
                raise ValueError('请先连接设备，并停止当前任务。')
            if time.monotonic()-self.last_frame > 1. or not len(self.raw):
                raise ValueError('尚未收到设备数据，请检查设备。')
            self.capture = CaptureRun(self.root,group,name,self.profile,self.config,trial_count=trial_count,action_s=action_s,task=self.task,random_order=random_order,collection_notes=collection_notes)
            return self.capture.run_path

    def reject_capture_trial(self,capture,trial,reason):
        with self.lock:
            if capture is not self.capture:raise ValueError('采集已结束或已切换，请检查本次记录。')
            capture.reject_trial(trial,reason)

    def stop_capture(self):
        with self.lock:
            if self.capture:
                self.capture.stop()
                self.capture = None

    def start_inference(self, model, source, recording=None, assessment=False):
        if self.inference or self.capture:
            raise ValueError('请先停止当前任务。')
        self.replay_done = False
        self.error = ''
        require_task(read_json(Path(model)/'metadata.json'),self.task)
        raw = None
        labels = None
        if source == 'replay':
            profile,raw,labels = read_recording(recording)
            labels=[r for r in labels if r['trial'] not in excluded_trials(profile)]
            if assessment and not labels:raise ValueError('这份数据没有可评估的有效动作组，请补采。')
            require_task(profile,self.task)
        else:
            profile = self.profile
            if not profile or time.monotonic()-self.last_frame > 1. or not len(self.raw):
                raise ValueError('请先连接设备，确认有实时波形。')
        pipeline = InferencePipeline(model,profile)
        from .collection import load_notes
        notes=profile.get('collection_notes',{}) if source=='replay' else load_notes(self.root,pipeline.meta['group'],self.task)
        if raw is not None:
            self.set_profile(profile)
        with self.lock:
            self.source = source
            self.result = None
            folder = self.root/safe_name(pipeline.meta['group'])/'predictions'
            folder.mkdir(parents=True,exist_ok=True)
            base = folder/f'{datetime.now():%Y%m%d_%H%M%S}_{source}_{uuid.uuid4().hex[:8]}'
            write_json(base.with_suffix('.json'),dict(model=str(Path(model).resolve()),model_id=pipeline.meta['model_id'],
                source=source,recording=str(recording) if source=='replay' and recording else None,
                profile=profile,decision=pipeline.stable.settings,architecture=pipeline.meta.get('architecture'),**self.task.metadata))
            self.prediction_file = base.with_suffix('.csv').open('w',encoding='utf-8',newline='')
            self.prediction_writer = csv.writer(self.prediction_file)
            self.prediction_writer.writerow(['seconds','raw_class','stable_class',*[f'p_{c}' for c in self.task.classes]])
            self.inference = pipeline
            self.assessment = BasicAssessment(self.task,profile['sampling_rate'],pipeline.window,
                                              labels=labels,source=source) if assessment else None
            self.last_assessment_path = None
            self.assessment_context = dict(model_id=pipeline.meta['model_id'],record_id=profile.get('record_id'),
                                           created_at=datetime.now().astimezone().isoformat(),
                                           collection_notes=notes,
                                           sampling_rate=profile['sampling_rate'],channel_ids=profile['channel_ids'],device=profile.get('device'),
                                           group=pipeline.meta['group'],model=str(Path(model).resolve()),
                                           recording=str(recording) if recording else None)
            used={r.get('record_id') for rows in pipeline.meta.get('split',{}).values() for r in rows}
            self.assessment_context['interpretation'] = (
                '所选记录参与了模型训练/验证/测试流程；本次为回放自检，不是新的独立测试。'
                if source=='replay' and profile.get('record_id') in used else
                '新记录回放：请确认未用于训练或调参，再将结果作为独立测试。' if source=='replay' else
                '模拟信号评估只用于软件自检，不能证明真实肌电效果。' if profile.get('device')=='模拟练习' else
                '实时提示评估；结果反映本次操作者、佩戴和模型条件。')
        if raw is not None:
            self.replay_stop.clear()
            self.replay_thread = threading.Thread(target=self._replay,args=(raw,),daemon=True)
            self.replay_thread.start()

    def _replay(self, raw):
        step = max(1,round(self.profile['sampling_rate']*.02))
        deadline = time.monotonic()
        try:
            for offset in range(0,len(raw),step):
                if self.replay_stop.is_set():
                    return
                self.feed(raw[offset:offset+step])
                deadline += step/self.profile['sampling_rate']
                if self.replay_stop.wait(max(0,deadline-time.monotonic())):
                    return
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.replay_done = True

    def stop_inference(self):
        self.replay_stop.set()
        if self.replay_thread and threading.current_thread() is not self.replay_thread:
            self.replay_thread.join(timeout=3)
        self.replay_thread = None
        with self.lock:
            if self.assessment:
                report=dict(self.assessment.report(),**self.assessment_context)
                folder=self.root/safe_name(report['group'])/'evaluations'
                base=folder/f'{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}'
                write_json(base.with_suffix('.json'),report)
                base.with_suffix('.html').write_text(report_html(report),encoding='utf-8')
                self.last_assessment_path=base.with_suffix('.html')
                self.assessment=None
            self.inference = None
            self.result = None
            dds, self.dds = self.dds, None
            if self.prediction_file:
                self.prediction_file.close()
                self.prediction_file = None
        if dds:
            dds.close()

    def snapshot(self):
        with self.lock:
            return dict(profile=self.profile,raw=self.raw.copy(),filtered=self.filtered.copy(),result=self.result,
                capture=self.capture.status() if self.capture else None,source=self.source,
                assessment=self.assessment.status() if self.assessment else None,
                last_frame=self.last_frame,inferencing=self.inference is not None,replay_done=self.replay_done)

    def close(self):
        self.stop_capture()
        self.stop_inference()
