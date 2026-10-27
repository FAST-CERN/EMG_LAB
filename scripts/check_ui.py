"""Exercise the actual Qt workflow and child processes using the mock device."""
import os
import sys
import json
PHYSICS = '--physics' in sys.argv
if not PHYSICS:
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import time
from PySide6 import QtWidgets as W
from shiboken6 import isValid
from emg_lab.app import MainWindow,configure_app
from emg_lab.storage import ROOT,list_models,list_recordings


def main():
    app=W.QApplication([])
    configure_app(app)
    (ROOT/'local').mkdir(exist_ok=True)
    physics_statuses = []
    with tempfile.TemporaryDirectory(prefix='emg_ui_') as folder:
        w=MainWindow(Path(folder))
        w.show()
        w.stack.setCurrentIndex(1)
        def until(condition,timeout):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                app.processEvents()
                if condition():return
                time.sleep(.01)
            raise AssertionError(f'Timeout: {w.notice.text()} / {w.train_status.text()}')
        try:
            assert w.mock_panel.isHidden()
            w.device_combo.setCurrentIndex(w.device_combo.findData('模拟练习'))
            w.connect_button.click()
            until(lambda:w.device_ready and len(w.session.raw)>500,15)
            w.grab().save(str(ROOT/'local'/'ui-device.png'))
            w.tabs.setCurrentIndex(1)
            w.scene_check.setChecked(PHYSICS)
            w.trial_count.setValue(1)
            w.action_seconds.setValue(3. if PHYSICS else 1.)
            w.capture_start.click()
            if PHYSICS:
                assert w.session.capture is None
                w.scene.window.worker.telemetry.connect(lambda s:physics_statuses.append(dict(mode='sample',**s)))
                until(lambda:w.session.capture is not None,35)
            assert w.session.capture is not None,w.notice.text()
            if PHYSICS:
                until(lambda:w.session.capture.status()['remaining']<2.3,5)
                w.scene.window.grab().save(str(ROOT/'local'/'physics-prepare.png'))
                until(lambda:w.session.capture.status()['remaining']<.2,4)
                w.scene.window.grab().save(str(ROOT/'local'/'physics-countdown-zero.png'))
            until(lambda:w.capture_progress.value()>100,5)
            w.grab().save(str(ROOT/'local'/'ui-capture.png'))
            if PHYSICS:
                until(lambda:w.session.capture.status()['phase']=='动作' and w.session.capture.status()['remaining']<2.5,4)
                assert w.scene.window.view.picture is not None
                w.scene.window.grab().save(str(ROOT/'local'/'physics-capture.png'))
            until(lambda:w.session.capture is None,45)
            if PHYSICS:
                assert w.scene.window is None
                assert {s['command'] for s in physics_statuses} == {0,1,2,3}
                assert all(not s['fallen'] for s in physics_statuses)
            recordings=list_recordings(Path(folder))
            assert len(recordings)==1 and recordings[0][0].suffix=='.emg'
            assert recordings[0][1]['completed_trials']==1
            w.tabs.setCurrentIndex(2)
            w.epochs.setValue(30 if PHYSICS else 12)
            w.train_start.click()
            assert w.training is not None,w.notice.text()
            until(lambda:w.training is None,60)
            assert len(list_models(Path(folder)))==1,w.notice.text()
            assert list_models(Path(folder))[0][1]['test_accuracy'] is None
            assert '尚未评估' in w.training_result.toPlainText()
            assert '尚未评估' in w.model_info.text()
            w.grab().save(str(ROOT/'local'/'ui-training.png'))
            w.tabs.setCurrentIndex(3)
            assert not w.mock_panel.isHidden()
            w.infer_scene.setChecked(PHYSICS)
            w.infer_start.click()
            if PHYSICS:
                assert w.session.inference is None
                w.scene.window.worker.telemetry.connect(lambda s:physics_statuses.append(dict(mode='open',**s)))
                until(lambda:w.session.inference is not None,35)
            assert w.session.inference,w.notice.text()
            until(lambda:w.session.result is not None,5)
            assert not w.dds_check.isEnabled()
            w.mock_action.setCurrentIndex(3)
            until(lambda:w.session.result['sample_end']>2000,5)
            if PHYSICS:
                for command in (3,1,2,0):
                    w.mock_action.setCurrentIndex(command)
                    until(lambda:w.session.result['filtered_class']==command,10)
                    until(lambda:w.scene.window.latest_status.get('command')==command,5)
                    assert not w.scene.window.latest_status['fallen']
                    if command == 3:
                        w.scene.window.grab().save(str(ROOT/'local'/'physics-inference.png'))
            w.grab().save(str(ROOT/'local'/'ui-inference.png'))
            w.infer_stop.click()
            assert w.session.inference is None
            w.disconnect_button.click()
            w.source.setCurrentIndex(1)
            assert w.mock_panel.isHidden()
            w.infer_start.click()
            if PHYSICS:
                until(lambda:w.session.inference is not None,35)
            assert w.session.inference,w.notice.text()
            until(lambda:w.session.result is not None,5)
            assert not w.dds_check.isEnabled()
            until(lambda:w.session.inference is None,30)
            if PHYSICS:
                assert w.scene.window is None
                # Closing a real scene cancels a pending start without leaving a worker alive.
                w.infer_start.click()
                worker = w.scene.window.worker
                w.scene.window.close()
                until(lambda:w.scene_pending is None,8)
                assert w.session.inference is None and (not isValid(worker) or not worker.isRunning())
                (ROOT/'local'/'physics-validation.json').write_text(json.dumps(dict(passed=True,records=physics_statuses),indent=2),encoding='utf-8')
            files=list(Path(folder).glob('*/predictions/*.csv'))
            assert len(files)==2
            assert all(len(p.read_text().splitlines())>2 for p in files)
            for p in files:
                meta=json.loads(p.with_suffix('.json').read_text(encoding='utf-8'))
                assert meta['decision']==dict(threshold=.65,hold=3)
                assert bool(meta['recording']) == (meta['source']=='replay')
            print(f'PASS: Qt connect -> 1 trial / 1 session file -> train without holdout -> live inference -> file replay -> clean shutdown; physics={PHYSICS}',flush=True)
            print(w.training_result.toPlainText(),flush=True)
        finally:
            w.close()
            app.processEvents()


if __name__=='__main__':
    main()
