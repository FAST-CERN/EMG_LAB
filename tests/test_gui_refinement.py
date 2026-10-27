"""Classroom layout and output lifecycle regressions, without real USB/DDS."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from emg_lab.app import MainWindow, configure_app
from emg_lab.hand.scene import HandScene, RELAXED_PROGRESS
from emg_lab.hand.output import HandOutput
from emg_lab.hand.driver.revo2_path_control import PathController, PathSimHand
from emg_lab.robot import DdsBroadcast


@pytest.fixture
def window(tmp_path):
    app=W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    w=MainWindow(tmp_path); w.timer.stop(); w.show()
    yield w
    w.close(); app.processEvents()


def test_primary_controls_stay_visible_when_details_scroll(window):
    buttons=(window.connect_button,window.capture_stop,window.train_stop,window.infer_stop)
    for task in ('robot','hand'):
        window.select_task(task)
        for size in ((900,600),(1160,820)):
            window.resize(*size)
            for i,button in enumerate(buttons):
                window.tabs.setCurrentIndex(i)
                for toggle in window.tabs.widget(i).findChildren(W.QToolButton):
                    if toggle.isCheckable(): toggle.setChecked(True)
                W.QApplication.processEvents()
                scroll=window.page_scrolls[window.tabs.tabText(i)]
                for y in (0,scroll.verticalScrollBar().maximum()):
                    scroll.verticalScrollBar().setValue(y)
                    W.QApplication.processEvents()
                    assert not scroll.isAncestorOf(button)
                    assert button.visibleRegion().boundingRect()==button.rect()
                assert scroll.horizontalScrollBar().maximum()==0


def test_capture_page_shows_live_signal_for_both_tasks(window,profile):
    for task in ('robot','hand'):
        window.select_task(task)
        window.device_ready=True
        window.session.set_profile(profile)
        window.capture_waveform.set_profile(profile)
        window.tabs.setCurrentIndex(1)
        raw=np.random.default_rng(5).normal(size=(1000,4)).astype(np.float32)
        window.session.feed(raw)
        window.tick()
        np.testing.assert_array_equal(window.capture_waveform.raw_curves[0].yData,raw[:,0])
        assert window.capture_waveform.scale.currentData()=='fixed'


def test_collection_neutral_pose_does_not_change_inference_stop():
    app=W.QApplication.instance() or W.QApplication([])
    scene=HandScene(); scene.mode='sample'
    def cue(phase,cls):
        return dict(phase=phase,cue=cls,command=cls if phase=='动作' else 0,
                    trial=1,action_index=1,trial_count=1,remaining=1.,done=False)
    for cls in (1,2,0):
        scene.motion.progress=.9
        scene.sample(cue('准备',cls))
        assert scene.motion.progress==RELAXED_PROGRESS and scene.motion.command==0
        scene.sample(cue('动作',cls))
        scene.motion.advance(.2)
        expected={1:.35,2:.65,0:.5}[cls]
        assert scene.motion.progress==pytest.approx(expected)
        scene.sample(cue('准备',2))
        assert scene.motion.progress==RELAXED_PROGRESS
    scene.mode='open'; scene.motion.progress=.27
    scene.command(0); scene.motion.advance(2.)
    assert scene.motion.progress==.27
    scene.stop()


class Lease:
    def __init__(self): self.closed=False
    def close(self): self.closed=True


def spin(output,condition,timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        output.poll()
        if condition(): return
        time.sleep(.01)
    raise AssertionError(output.error or 'Simulated output timed out')


def test_hand_read_only_connect_enable_stop_and_reuse():
    app=W.QApplication.instance() or W.QApplication([])
    hardware=PathSimHand('left')
    output=HandOutput(controller_factory=lambda:PathController(lambda side:hardware),lease_factory=Lease)
    try:
        output.connect_hand(); output.timer.stop()
        spin(output,lambda:output.connected)
        assert hardware.writes==[] and not output.enabled
        for source,device in [('replay','Cometa'),('live','模拟练习')]:
            with pytest.raises(ValueError): output.enable(source,device)
        output.update(dict(filtered_class=2))
        assert hardware.writes==[]
        output.enable('live','Cometa')
        spin(output,lambda:output.initialized)
        output.update(dict(filtered_class=2))
        spin(output,lambda:hardware.status()['positions'][2]>100)
        output.disable()
        spin(output,lambda:not output.controller.interrupted())
        held=hardware.status()['positions'][2:]
        output.update(dict(filtered_class=1)); time.sleep(.08)
        assert hardware.status()['positions'][2:]==held and output.connected
        output.enable('live','Cometa'); output.update(dict(filtered_class=1))
        spin(output,lambda:hardware.status()['positions'][2]<held[0])
    finally:
        output.close()
    assert hardware.closed


def test_stop_failure_is_reported_during_disconnect():
    app=W.QApplication.instance() or W.QApplication([])
    class BrokenStop(PathSimHand):
        def stop_all(self): raise TimeoutError('test stop acknowledgement missing')
    hardware=BrokenStop('left')
    output=HandOutput(controller_factory=lambda:PathController(lambda side:hardware),lease_factory=Lease)
    errors=[]; output.failed.connect(errors.append)
    output.connect_hand(); output.timer.stop()
    spin(output,lambda:output.connected)
    # Simulate an output that had moved, then a lost STOP acknowledgement.
    output.controller.touched=True
    result=output.close()
    assert '停止未获确认' in result and errors and hardware.closed


def test_gui_connects_before_inference_and_keeps_connection_on_stop(window,profile,monkeypatch):
    import emg_lab.hand.output as module
    hardware=PathSimHand('left')
    factory=lambda parent:HandOutput(parent,controller_factory=lambda:PathController(lambda side:hardware),lease_factory=Lease)
    monkeypatch.setattr(module,'HandOutput',factory)
    window.select_task('hand'); window.hand_check.setChecked(True)
    assert window.session.inference is None and window.hand_connect.isEnabled()
    window.connect_hand(); output=window.hand_output; output.timer.stop()
    spin(output,lambda:output.connected)
    assert hardware.writes==[]
    window.device_ready=True; window.session.set_profile(dict(profile,device='Cometa'))
    monkeypatch.setattr(window.session,'start_inference',lambda *args:setattr(window.session,'inference',object()))
    window.begin_inference('fake-model','live',None)
    assert output.enabled and window.session.inference
    window.stop_inference()
    assert window.hand_output is output and output.connected and not output.enabled
    assert not hardware.closed
    window.disconnect_hand()
    assert hardware.closed and window.hand_output is None


def test_dds_connect_is_idle_and_stop_preserves_transport():
    class Adapter:
        last_error=''
        def __init__(self): self.sent=[]; self.closed=False
        def connect(self): return True
        def send_direction(self,event): self.sent.append(dict(event)); return True
        def disconnect(self): self.closed=True
    adapter=Adapter(); dds=DdsBroadcast(adapter=adapter)
    dds.connect(); assert dds.connected and not adapter.sent
    with pytest.raises(ValueError): dds.enable('replay','Cometa')
    try:
        dds.enable('live','Cometa')
        dds.update(dict(filtered_class=3,probabilities=[0.,0.,0.,1.]))
        time.sleep(.15)
        assert any(x['filtered_class']==3 for x in adapter.sent)
        dds.disable()
        count=len(adapter.sent); time.sleep(.12)
        assert len(adapter.sent)==count and adapter.sent[-1]['filtered_class']==0
        assert dds.connected and not adapter.closed
    finally: dds.close()
    assert adapter.closed
