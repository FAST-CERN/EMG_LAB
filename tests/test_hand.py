"""Three-class workflow and USB lifecycle contracts. No hardware is opened."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import queue
import threading
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from emg_lab.tasks import HAND, ROBOT, HAND_RATE, task_from_metadata
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.storage import read_recording, read_json
from emg_lab.training import prepare_dataset, train
from emg_lab.inference import InferencePipeline
from emg_lab.engine import Session
from emg_lab.evaluation import evaluation_details
from emg_lab.hand.model import HandMotion, HandModel, ACTIVE
from emg_lab.hand.output import HandOutput


def synth_hand(root,profile,trial_count=3):
    capture=CaptureRun(root,'HAND_TEST','手部开合',profile,SignalConfig(),trial_count=trial_count,action_s=1.2,task=HAND)
    rng=np.random.default_rng(142)
    while not capture.completed:
        cue=capture.status()['command']
        gains=np.full(len(profile['channel_ids']),.03)
        if cue: gains[cue-1]=1.
        capture.feed((rng.normal(size=(20,len(gains)))*gains).astype(np.float32))
    return capture.run_path


def test_hand_labels_trial_count_and_partial_capture(tmp_path,profile):
    path=synth_hand(tmp_path,profile,2)
    meta,raw,labels=read_recording(path)
    assert meta['classes']==['rest','open','close'] and meta['task_type']==HAND.task_type
    assert meta['completed_trials']==2 and [r['class_id'] for r in labels]==[1,2,0,1,2,0]
    assert len(raw)==2*3*4200
    partial=CaptureRun(tmp_path,'HAND_TEST','部分',profile,SignalConfig(),trial_count=2,action_s=1.2,task=HAND)
    partial.feed(np.zeros((3*4200+4500,4),np.float32)); partial.stop()
    m,_,_=read_recording(partial.run_path)
    assert m['completed_trials']==1 and not m['complete']
    _,split=prepare_dataset([partial.run_path])
    assert len(split['train'])==1


def test_robot_hand_cannot_mix_and_old_robot_metadata_stays_valid(tmp_path,profile,records):
    hand=synth_hand(tmp_path,profile,1)
    with pytest.raises(ValueError,match='实验目标'):
        prepare_dataset([records[0],hand])
    assert task_from_metadata({})==ROBOT
    with pytest.raises(ValueError): task_from_metadata(dict(task_type=HAND.task_type,classes=['rest','left','right']))


def test_three_class_training_evaluation_and_streaming(tmp_path,profile):
    path=synth_hand(tmp_path,profile)
    model=train(dict(recordings=[path],data_root=tmp_path,name='手部三分类',epochs=15))
    meta=read_json(model/'metadata.json')
    assert meta['classes']==list(HAND.classes)
    report=meta['online_evaluation']
    assert np.asarray(report['command']['confusion_matrix']).shape==(3,3)
    assert [c['name'] for c in report['command']['per_class']]==list(HAND.classes)
    assert '左转' not in evaluation_details(meta)
    raw=read_recording(path)[1]
    full=InferencePipeline(model,profile).feed(raw)
    stream=InferencePipeline(model,profile); chunked=[]
    for block in np.array_split(raw,97): chunked.extend(stream.feed(block))
    np.testing.assert_allclose([r['probabilities'] for r in full],[r['probabilities'] for r in chunked],atol=1e-6)
    assert len(full[0]['probabilities'])==3
    robot=Session(tmp_path)
    with pytest.raises(ValueError,match='实验目标'): robot.start_inference(model,'replay',path)
    with pytest.raises(ValueError,match='实验目标'):
        InferencePipeline(model,dict(profile,**ROBOT.metadata))
    session=Session(tmp_path,task=HAND)
    session.set_profile(profile); session.feed(np.zeros((1000,4),np.float32))
    session.start_inference(model,'live'); session.feed(raw[:1500]); session.stop_inference()
    log=next(tmp_path.glob('HAND_TEST/predictions/*.csv'))
    assert log.read_text(encoding='utf-8').splitlines()[0]=='seconds,raw_class,stable_class,p_rest,p_open,p_close'
    assert read_json(log.with_suffix('.json'))['task_type']==HAND.task_type


def test_motion_75_rate_reverse_and_stop_preserve_position():
    motion=HandMotion(); motion.set_command(2)
    assert motion.advance(.4)==pytest.approx(.3)
    motion.set_command(0); assert motion.advance(3)==pytest.approx(.3)
    motion.set_command(1); assert motion.advance(.2)==pytest.approx(.15)
    motion.set_command(2); motion.advance(10)
    assert motion.progress==1 and motion.positions[:2]==[400,337]
    motion.set_command(1); motion.advance(10); assert motion.progress==0


def test_official_model_mimic_and_fixed_default_thumb():
    hand=HandModel()
    thumb=[]
    for p in (0,.5,1):
        hand.set_progress(p)
        thumb.append([hand.data.qpos[hand.model.joint(n).qposadr[0]] for n in ACTIVE[:2]])
        for name,source,mult,offset in hand.mimics:
            assert hand.data.qpos[hand.model.joint(name).qposadr[0]]==pytest.approx(hand.data.qpos[hand.model.joint(source).qposadr[0]]*mult+offset)
    np.testing.assert_allclose(thumb,np.tile(np.deg2rad([24,30]),(3,1)))
    assert hand.model.nq==11 and hand.model.ngeom>=20


class FakeLease:
    def __init__(self): self.closed=False
    def close(self): self.closed=True


class FakeController:
    def __init__(self):
        self.events=queue.Queue(); self.calls=[]
        self.connect_event=threading.Event(); self.quit_event=threading.Event()
        self.stopping=False
    def set_speed(self,value): self.speed=value
    def start(self): pass
    def is_alive(self): return False
    def heartbeat_tick(self): pass
    def request_intent(self,value): self.calls.append(value)
    def request_stop(self): self.calls.append('stop'); self.stopping=True
    def interrupted(self): return self.stopping


def test_real_output_is_explicit_live_only_initializes_then_three_commands():
    app=W.QApplication.instance() or W.QApplication([])
    output=HandOutput(controller_factory=FakeController,lease_factory=FakeLease)
    for source,device in [('live','模拟练习'),('replay','Cometa')]:
        with pytest.raises(ValueError): output.enable(source,device)
        assert output.controller is None
    output.connect_hand(); ctrl=output.controller; lease=output.lease
    assert ctrl.speed==HAND_RATE==75
    ctrl.events.put(dict(kind='connected')); output.poll()
    assert ctrl.calls==[] and output.connected and not output.enabled
    output.enable('live','Cometa')
    assert ctrl.calls==['open']
    output.update(dict(filtered_class=2)); assert ctrl.calls==['open']
    ctrl.events.put(dict(kind='sample',view=dict(initialized=True),sample=dict(positions=[400,337,0,0,0,0])))
    output.poll(); output.update(dict(filtered_class=2)); output.update(dict(filtered_class=2))
    assert ctrl.calls==['open','fist']
    output.update(dict(filtered_class=0)); output.update(dict(filtered_class=1))
    assert ctrl.calls[-1]=='stop'  # A pending stop must not swallow the next repeated open.
    ctrl.stopping=False; output.update(dict(filtered_class=1)); assert ctrl.calls[-1]=='open'
    output.updated=0.; output.poll(); assert ctrl.calls[-1]=='stop'
    output.close(); assert ctrl.quit_event.is_set() and lease.closed


def test_ui_target_changes_three_classes_data_lists_and_preview(tmp_path,profile):
    from emg_lab.app import MainWindow,configure_app
    app=W.QApplication.instance() or W.QApplication([]); configure_app(app)
    w=MainWindow(tmp_path); w.timer.stop()
    try:
        hand=synth_hand(tmp_path,profile,1)
        w.select_task('hand')
        assert w.task==HAND and w.session.task==HAND and w.records.count()==1
        assert w.mock_action.count()==3 and w.probabilities[3].isHidden()
        assert not w.capture_waveform.isHidden() and not w.infer_hand_view.isHidden()
        assert w.dds_panel.isHidden() and w.hand_check.isEnabled()
        assert '15 个动作' in w.capture_plan.text()
        w.select_task('robot')
        assert w.records.count()==0 and w.mock_action.count()==4
        assert not w.capture_waveform.isHidden() and w.hand_panel.isHidden()
    finally: w.close(); app.processEvents()
