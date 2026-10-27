"""Actual Qt/device-process/training/live/replay exercise. No physical hardware."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import time
import json
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6 import QtWidgets as W
from emg_lab.app import MainWindow, configure_app
from emg_lab.storage import ROOT, list_models, list_recordings


def main():
    key=sys.argv[1]
    out=ROOT/'local'/('lesson1-'+key)
    out.mkdir(parents=True,exist_ok=True)
    app=W.QApplication([])
    configure_app(app)
    with tempfile.TemporaryDirectory(prefix=key+'-',dir=out) as folder:
        w=MainWindow(Path(folder))
        w.show()
        w.select_task(key)
        def until(condition,timeout):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                app.processEvents()
                if condition(): return
                time.sleep(.01)
            raise AssertionError(f'Timeout: {w.notice.text()} / {w.train_status.text()}')
        try:
            w.device_combo.setCurrentIndex(w.device_combo.findData('模拟练习'))
            w.connect_button.click()
            until(lambda:w.device_ready and len(w.session.raw)>500,15)
            w.tabs.setCurrentIndex(1)
            w.trial_count.setValue(1)
            w.action_seconds.setValue(3)
            w.scene_check.setChecked(True)
            w.capture_start.click()
            until(lambda:w.session.capture is not None,40)
            until(lambda:w.capture_progress.value()>80,10)
            w.grab().save(str(out/'capture.png'))
            until(lambda:w.session.capture is None,90)
            assert len(list_recordings(folder))==1,w.notice.text()
            w.tabs.setCurrentIndex(2)
            w.epochs.setValue(50)
            w.train_start.click()
            until(lambda:w.training is None,90)
            models=list_models(folder)
            assert len(models)==1,w.notice.text()
            assert len(models[0][1]['classes'])==len(w.task.classes)
            w.tabs.setCurrentIndex(3)
            w.infer_scene.setChecked(True)
            w.infer_start.click()
            until(lambda:w.session.inference is not None,40)
            seen=[]
            for command in range(len(w.task.classes)):
                w.mock_action.setCurrentIndex(command)
                until(lambda:w.session.result and w.session.result['filtered_class']==command,15)
                until(lambda:w.scene.motion.command==command if key=='hand5' else w.scene.window.latest_status.get('command')==command,5)
                seen.append(command)
            w.grab().save(str(out/'live.png'))
            w.stop_inference()
            # Exercise live prompt timing/auto completion as a separate path.
            # Only this test harness follows prompts with simulated input.
            w.practice_mode.setCurrentIndex(w.practice_mode.findData('assessment'))
            w.infer_start.click()
            until(lambda:w.session.assessment is not None,40)
            deadline=time.monotonic()+100
            while w.session.inference is not None:
                app.processEvents()
                assessment=w.session.assessment
                if assessment:
                    state=assessment.status()
                    if state['target'] is not None:
                        w.mock_action.setCurrentIndex(state['target'] if state['phase']=='动作' else 0)
                assert time.monotonic()<deadline,'Live assessment did not finish'
                time.sleep(.01)
            live_report_path=w.session.last_assessment_path
            live_report=json.loads(live_report_path.with_suffix('.json').read_text(encoding='utf-8'))
            assert live_report['complete'] and live_report['source']=='live'
            assert live_report['command']['total']>0
            assert '模拟信号' in live_report['interpretation']
            (out/'live-assessment.json').write_text(json.dumps(live_report,ensure_ascii=False,indent=2),encoding='utf-8')
            w.disconnect_device()
            w.source.setCurrentIndex(w.source.findData('replay'))
            w.practice_mode.setCurrentIndex(w.practice_mode.findData('assessment'))
            w.infer_start.click()
            until(lambda:w.session.inference is not None,40)
            until(lambda:w.session.assessment is not None and w.session.assessment.seen>6000,12)
            w.grab().save(str(out/'assessment.png'))
            until(lambda:w.session.inference is None,90)
            report_path=w.session.last_assessment_path
            assert report_path and report_path.exists()
            report=json.loads(report_path.with_suffix('.json').read_text(encoding='utf-8'))
            assert report['complete']
            assert report['command']['total']>0
            assert len(report['command']['confusion_matrix'])==len(w.task.classes)
            assert '自检' in report['interpretation']
            (out/'assessment.html').write_text(report_path.read_text(encoding='utf-8'),encoding='utf-8')
            (out/'report.json').write_text(json.dumps(dict(passed=True,task=key,live_commands=seen,
                assessment=report),ensure_ascii=False,indent=2),encoding='utf-8')
            print('PASS',key,'Qt mock capture -> train -> every class live -> 3D -> live assessment -> full replay assessment -> reports',flush=True)
        finally:
            w.close()
            app.processEvents()

if __name__=='__main__':
    main()
