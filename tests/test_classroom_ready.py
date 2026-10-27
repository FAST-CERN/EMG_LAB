import json
from pathlib import Path
import numpy as np
import pytest
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.storage import read_recording,usable_record,write_json
from emg_lab.training import prepare_dataset
from emg_lab.tasks import ROBOT,HAND
from emg_lab.collection import load_notes,save_notes,signal_check
from emg_lab.practice import BasicAssessment,report_html

def test_rejected_trial_preserves_raw_and_survives_export_import(tmp_path,profile):
    from emg_lab.transfer import export_recording,import_recording
    notes=dict(operator='P01',wearing='第1次',channels='1 左侧',actions='前进：握拳')
    capture=CaptureRun(tmp_path/'source','G01','采集',profile,SignalConfig(),trial_count=3,action_s=1.2,collection_notes=notes)
    raw=np.random.default_rng(21).normal(size=(capture.session_length,4)).astype('f4')
    capture.feed(raw[:capture.trial_length+20])
    capture.reject_trial(2,'动作做错')
    capture.feed(raw[capture.trial_length+20:])
    meta,actual,labels=read_recording(capture.run_path)
    np.testing.assert_array_equal(actual,raw)
    assert meta['completed_trials']==3 and meta['usable_trials']==2 and usable_record(meta)
    assert meta['collection_notes']==notes and len(labels)==12
    _,split=prepare_dataset([capture.run_path])
    assert {unit[2]['trial'] for units in split.values() for unit in units}=={1,3}
    destination=tmp_path/'export';destination.mkdir()
    exported=export_recording(capture.run_path,destination,ROBOT)
    imported=import_recording(exported,tmp_path/'other',ROBOT)
    assert read_recording(imported.path)[0]['rejected_trials']==[dict(trial=2,reason='动作做错')]

def test_all_rejected_not_trainable_and_notes_are_scoped(tmp_path,profile):
    capture=CaptureRun(tmp_path,'G01','无效',profile,SignalConfig(),trial_count=1,action_s=1.2)
    capture.reject_trial(1,'传感器问题');capture.feed(np.zeros((capture.session_length,4),dtype='f4'))
    assert not usable_record(read_recording(capture.run_path)[0])
    with pytest.raises(ValueError,match='补采'):prepare_dataset([capture.run_path])
    with pytest.raises(ValueError,match='结束'):capture.reject_trial(1,'again')
    save_notes(tmp_path,'A',ROBOT,dict(operator='P01'))
    assert load_notes(tmp_path,'A',ROBOT)['operator']=='P01'
    assert load_notes(tmp_path,'B',ROBOT)=={} and load_notes(tmp_path,'A',HAND)=={}

def test_health_distinguishes_constant_channel_small_noise_and_disconnection():
    raw=np.random.default_rng(5).normal(scale=1e-10,size=(200,4))
    assert not signal_check(raw,100,[1,2,3,4],.1)[1]
    raw[:,2]=.02
    text,warning=signal_check(raw,100,[1,2,3,4],.1)
    assert warning and '3' in text
    assert '中断' in signal_check(raw,100,[1,2,3,4],2)[0]
    assert not signal_check(raw[:20],100,[1,2,3,4],.1)[1]

def test_assessment_behavior_and_stop_metrics_use_predictions_only():
    labels=[dict(trial=1,class_id=0,start_sample=0,end_sample=200),dict(trial=1,class_id=3,start_sample=200,end_sample=400)]
    assessment=BasicAssessment(ROBOT,100,10,labels=labels,source='replay')
    sequence=[(30,1),(40,1),(50,0),(60,2),(70,0),(230,0),(240,3),(250,3),(260,3),(270,0),(280,3)]
    assessment.feed([dict(sample_end=t,raw_class=3,filtered_class=c) for t,c in sequence],400)
    report=assessment.report()
    assert report['stop']['false_motion_events']==2
    assert report['stop']['false_motion_fraction']==pytest.approx(3/5)
    movement=report['segments'][1]
    assert movement['first_correct_seconds']==.4 and movement['switches']==3
    assert movement['longest_correct_seconds']==pytest.approx(.2)
    assert '不是机器人/机械手的到位时间' in report_html(report)
    assert report['command']['total']==11

def test_saved_reports_can_be_found_and_exported_with_evidence(tmp_path):
    from emg_lab.reports import find_reports,export_reports
    report=BasicAssessment(ROBOT,100,10).report(False)
    report.update(group='G01',model_id='model-A')
    source=tmp_path/'data/G01/evaluations/report.json';write_json(source,report)
    source.with_suffix('.html').write_text(report_html(report),encoding='utf-8')
    rows=find_reports(tmp_path/'data','G01')
    assert len(rows)==1 and rows[0]['model']=='model-A'
    assert find_reports(tmp_path/'data','G02')==[]
    exported=export_reports(rows,tmp_path)
    assert json.loads((exported/'01/report.json').read_text(encoding='utf-8'))==report

def test_small_window_keeps_capture_controls_accessible(tmp_path):
    from PySide6 import QtWidgets as W
    from emg_lab.app import MainWindow,configure_app
    app=W.QApplication.instance() or W.QApplication([]);configure_app(app)
    window=MainWindow(tmp_path);window.timer.stop();window.resize(900,600)
    window.stack.setCurrentIndex(1);window.tabs.setCurrentIndex(1);window.show();app.processEvents()
    assert window.collection_notes_button.text()=='采集记录…'
    assert not window.reject_trial_button.isEnabled()
    assert window.capture_start.isVisible() and window.capture_stop.isVisible()
    window.close()
