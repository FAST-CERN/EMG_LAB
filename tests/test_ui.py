"""Student-facing regressions; no real device or DDS participant is created."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
import numpy as np
from PySide6 import QtWidgets as W
from emg_lab.app import MainWindow,configure_app
from conftest import synthesize


@pytest.fixture
def window(tmp_path):
    app=W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    w=MainWindow(tmp_path)
    w.timer.stop()
    w.stack.setCurrentIndex(1)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def test_mock_input_is_only_shown_for_live_simulated_device(window,profile):
    window.tabs.setCurrentIndex(3)
    assert window.mock_panel.isHidden()


    window.device_ready=True
    window.session.set_profile(dict(profile,device='Cometa'))
    window.update_controls()
    assert window.mock_panel.isHidden()
    window.session.set_profile(dict(profile,device='Delsys'))
    window.update_controls()
    assert window.mock_panel.isHidden()
    window.session.set_profile(profile)
    window.update_controls()
    assert not window.mock_panel.isHidden()
    window.source.setCurrentIndex(1)
    assert window.mock_panel.isHidden()


def test_coin_settings_are_robot_only_and_formal_values_locked(window):
    window.practice_mode.setCurrentIndex(window.practice_mode.findData('coins'))
    assert not window.competition_panel.isHidden()
    assert window.infer_scene.isChecked() and not window.infer_scene.isEnabled()
    assert not window.dds_check.isEnabled()
    window.race_official.setChecked(True)
    assert window.race_count.value()==6 and window.race_seconds.value()==120
    assert not window.race_count.isEnabled() and not window.race_seconds.isEnabled()
    window.select_task('hand')
    assert window.practice_mode.currentData()=='free'
    assert window.competition_panel.isHidden()


def test_latest_selection_selects_one_file_not_all_siblings(window,tmp_path,profile):
    first=synthesize(tmp_path,profile,name='第一次',trial_count=1)[0]
    latest=synthesize(tmp_path,profile,name='第二次',trial_count=2)[0]
    window.refresh_data()
    window.select_latest()
    from PySide6.QtCore import Qt
    selected=[window.records.item(i).data(Qt.UserRole) for i in range(window.records.count()) if window.records.item(i).checkState()==Qt.Checked]
    assert selected==[str(latest)]
    assert first!=latest


def test_imported_data_survives_refresh_and_small_window_is_scrollable(window,tmp_path,profile):
    from emg_lab.storage import recording_metadata
    external=synthesize(tmp_path/'external',profile,trial_count=1)[0]
    window.imported_records[str(external)]=recording_metadata(external)
    window.refresh_data()
    window.refresh_data()
    assert window.records.count()==1
    assert window.replay_records.count()==1
    window.resize(950,650)
    window.tabs.setCurrentIndex(3)
    W.QApplication.processEvents()
    assert window.height()==650
    scroll=window.page_scrolls['04  使用模型']
    assert isinstance(scroll,W.QScrollArea)
    assert not scroll.isAncestorOf(window.infer_stop)
    assert window.infer_stop.visibleRegion().boundingRect()==window.infer_stop.rect()


def test_capture_waits_for_scene_and_cancel_never_records(window, profile, monkeypatch):
    monkeypatch.setattr(window.scene, 'start', lambda mode: None)
    window.session.set_profile(profile)
    window.session.feed(np.zeros((1000, 4), dtype=np.float32))
    window.device_ready = True
    window.start_capture()
    assert window.session.capture is None
    assert not window.capture_start.isEnabled() and window.capture_stop.isEnabled()
    window.stop_capture()
    window.scene.ready.emit()
    assert window.session.capture is None and window.scene_pending is None
    assert not list(window.session.root.glob('*/recordings/*'))


def test_scene_failure_finalizes_partial_capture(window, profile, monkeypatch):
    from emg_lab.storage import read_recording
    monkeypatch.setattr(window.scene, 'start', lambda mode: None)
    window.session.set_profile(profile)
    window.session.feed(np.zeros((1000, 4), dtype=np.float32))
    window.device_ready = True
    window.start_capture()
    window.scene.ready.emit()
    capture = window.session.capture
    assert capture is not None
    window.session.feed(np.zeros((200, 4), dtype=np.float32))
    window.scene.failed.emit('机器人已跌倒')
    assert window.session.capture is None
    meta, raw, _ = read_recording(capture.run_path)
    assert meta['finalized'] and not meta['complete']
    assert len(raw) == 200


def test_cached_prediction_does_not_refresh_robot_watchdog(window, profile, monkeypatch):
    sent = []
    monkeypatch.setattr(window.scene, 'command', sent.append)
    window.session.set_profile(profile)
    window.session.inference = object()
    window.session.result = dict(sample_end=500, filtered_class=3, probabilities=[0.,0.,0.,1.])
    window.tick()
    window.tick()
    assert sent == [3]
    window.session.result = dict(sample_end=600, filtered_class=0, probabilities=[1.,0.,0.,0.])
    window.tick()
    assert sent == [3, 0]
