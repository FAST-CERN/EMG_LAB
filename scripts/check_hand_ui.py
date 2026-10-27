"""Offline Qt acceptance: simulated EMG -> labels -> ONNX -> hand preview -> replay.

The real USB output must stay absent throughout this script.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import tempfile
import time
from PySide6 import QtWidgets as W
from emg_lab.app import MainWindow,configure_app
from emg_lab.storage import ROOT,list_recordings,list_models,read_recording,read_json


def main():
    app=W.QApplication([]); configure_app(app)
    out=ROOT/'local'/'hand-validation'; out.mkdir(parents=True,exist_ok=True)
    report=dict(passed=False,real_usb_used=False,events=[],errors=[])
    with tempfile.TemporaryDirectory(prefix='emg_hand_ui_') as folder:
        w=MainWindow(Path(folder)); w.resize(1160,940); w.show(); w.select_task('hand')
        def until(predicate,seconds=15):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                app.processEvents()
                assert w.hand_output is None,'Offline check unexpectedly constructed real USB output'
                if predicate(): return
                time.sleep(.01)
            raise AssertionError(f'Timeout: {w.notice.text()} / {w.train_status.text()} / result={w.session.result} / progress={w.scene.motion.progress}')
        def mark(name):
            print(name,flush=True)
            report['events'].append(dict(name=name,command=w.session.result,progress=w.scene.motion.progress))
        try:
            w.device_combo.setCurrentIndex(w.device_combo.findData('模拟练习'))
            w.connect_button.click(); until(lambda:w.device_ready and len(w.session.raw)>500)
            w.tabs.setCurrentIndex(1); w.trial_count.setValue(5); w.action_seconds.setValue(3)
            w.capture_start.click(); until(lambda:w.session.capture is not None)
            until(lambda:w.session.capture.status()['phase']=='动作' and w.scene.motion.progress<.8)
            assert w.scene.window is not None and w.scene.window.view.picture is not None
            w.grab().save(str(out/'collection.png')); mark('collection_3d_ready')
            until(lambda:w.session.capture is None,110)
            records=list_recordings(Path(folder)); assert len(records)==1
            meta,raw,labels=read_recording(records[0][0])
            assert meta['classes']==['rest','open','close'] and meta['completed_trials']==5
            assert [x['class_id'] for x in labels]==[1,2,0]*5
            report['recording']=meta
            w.tabs.setCurrentIndex(2); w.epochs.setValue(30); w.train_start.click()
            until(lambda:w.training is None,75)
            models=list_models(Path(folder)); assert len(models)==1,w.notice.text()
            report['model']=models[0][1]
            assert report['model']['online_evaluation']['split']=='test'
            w.grab().save(str(out/'training.png')); mark('trained_three_class_model')
            w.tabs.setCurrentIndex(3); w.infer_start.click()
            until(lambda:w.session.inference is not None and w.session.result is not None)
            assert not w.hand_check.isEnabled()
            w.mock_action.setCurrentIndex(2)
            until(lambda:w.session.result['filtered_class']==2 and w.scene.motion.progress>.12,12)
            w.mock_action.setCurrentIndex(0)
            until(lambda:w.session.result['filtered_class']==0 and w.scene.motion.command==0,10)
            held=w.scene.motion.progress
            deadline=time.monotonic()+.4
            until(lambda:time.monotonic()>deadline,2)
            assert abs(w.scene.motion.progress-held)<1e-6
            mark('decoded_stop_holds_position')
            w.grab().save(str(out/'inference-stop.png'))
            w.mock_action.setCurrentIndex(2)
            until(lambda:w.session.result['filtered_class']==2 and w.scene.motion.progress>.99,10)
            mark('decoded_close')
            w.grab().save(str(out/'inference-close.png'))
            w.mock_action.setCurrentIndex(1)
            until(lambda:w.session.result['filtered_class']==1 and w.scene.motion.progress<.01,10)
            mark('decoded_open')
            w.grab().save(str(out/'inference-open.png'))
            w.infer_stop.click(); assert w.scene.worker is None
            w.disconnect_button.click(); w.source.setCurrentIndex(1); w.infer_start.click()
            until(lambda:w.session.inference is not None)
            until(lambda:w.session.result is not None)
            assert not w.hand_check.isEnabled()
            until(lambda:w.session.inference is None,110)
            mark('replay_complete')
            logs=list(Path(folder).glob('*/predictions/*.csv'))
            assert len(logs)==2
            for log in logs:
                assert log.read_text(encoding='utf-8').splitlines()[0]=='seconds,raw_class,stable_class,p_rest,p_open,p_close'
                assert read_json(log.with_suffix('.json'))['task_type']=='HAND_COMMAND_3CLASS'
            w.infer_start.click(); w.stop_inference(); app.processEvents()
            assert w.scene_pending is None and w.scene.worker is None
            w.select_task('robot'); assert w.models.count()==0 and w.records.count()==0
            report['passed']=True
        except Exception as exc:
            report['errors'].append(str(exc)); raise
        finally:
            w.close(); app.processEvents()
            (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: offline three-class GUI, 3D cues, training, all decoded commands, replay and shutdown',flush=True)


if __name__=='__main__': main()
