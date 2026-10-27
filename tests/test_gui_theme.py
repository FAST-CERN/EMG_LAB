"""Visibility regressions for the classroom's essential configuration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import numpy as np
from PySide6 import QtCore as C, QtGui, QtWidgets as W
from emg_lab.app import MainWindow, configure_app


def test_capture_names_remain_visible_and_locked_during_capture(tmp_path, profile):
    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    w = MainWindow(tmp_path)
    w.timer.stop()
    w.show()
    try:
        w.select_task('robot')
        w.tabs.setCurrentIndex(1)
        w.scene_check.setChecked(False)
        w.session.set_profile(profile)
        w.session.feed(np.zeros((1000, 4), dtype=np.float32))
        w.device_ready = True
        app.processEvents()
        for control in (w.group, w.experiment, w.trial_count, w.action_seconds):
            assert control.isVisibleTo(w.page_scrolls['02  采集数据'].widget())
        w.start_capture()
        app.processEvents()
        assert w.session.capture is not None
        for control in (w.group, w.experiment, w.trial_count, w.action_seconds):
            assert control.isVisibleTo(w.page_scrolls['02  采集数据'].widget())
            assert not control.isEnabled()
    finally:
        w.close()


def test_essential_fields_do_not_depend_on_advanced_toggles(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    w = MainWindow(tmp_path)
    w.timer.stop()
    w.show()
    try:
        for task in ('robot', 'hand'):
            w.select_task(task)
            for index, controls in (
                (0, (w.device_combo, w.channels, w.bandpass, w.notch, w.waveform.display)),
                (1, (w.group, w.experiment, w.trial_count, w.action_seconds)),
                (2, (w.model_name, w.epochs)),
                (3, (w.models, w.source, w.infer_scene))):
                w.tabs.setCurrentIndex(index)
                page = w.page_scrolls[w.tabs.tabText(index)].widget()
                for toggle in page.findChildren(W.QToolButton):
                    if toggle.isCheckable():
                        toggle.setChecked(False)
                app.processEvents()
                assert all(control.isVisibleTo(page) for control in controls)
            w.source.setCurrentIndex(1)
            assert w.replay_field.isVisibleTo(w.infer_setup)
            w.source.setCurrentIndex(0)
            assert not w.replay_field.isVisibleTo(w.infer_setup)
        w.tabs.setCurrentIndex(2)
        item = W.QListWidgetItem('课堂样本')
        item.setFlags(item.flags() | C.Qt.ItemIsUserCheckable)
        item.setCheckState(C.Qt.Unchecked)
        w.records.addItem(item)
        item.setCheckState(C.Qt.Checked)
        assert '已勾选 1 份' in w.record_summary.text()
        w.open_help(1)
        assert not any('用 AI 改进' in title for title, _ in w.help_dialog.tabs.widget(1).chapters)
        w.help_dialog.close()
    finally:
        w.close()


def test_app_font_family_follows_platform(monkeypatch):
    from emg_lab.theme import apply_theme
    app = W.QApplication.instance() or W.QApplication([])
    app.setFont(QtGui.QFont('Helvetica', 10))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    apply_theme(app)
    assert app.font().family() == 'Helvetica', '非 win32 不得指定 Windows 字族'
    monkeypatch.setattr(sys, 'platform', 'win32')
    apply_theme(app)
    assert app.font().family() == 'Microsoft YaHei UI'
