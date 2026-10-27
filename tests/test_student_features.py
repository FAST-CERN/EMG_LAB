"""Student-facing import/export choices, restart persistence and offline help."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import pytest
from PySide6 import QtCore as C, QtWidgets as W

from emg_lab.app import MainWindow, configure_app
from emg_lab.storage import read_recording
from conftest import synthesize


@pytest.fixture
def window(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    window = MainWindow(tmp_path / 'library')
    window.timer.stop()
    window.stack.setCurrentIndex(1)
    window.show()
    app.processEvents()
    yield window
    window.close()
    app.processEvents()


def test_batch_import_export_and_restart(window, tmp_path, profile, monkeypatch):
    source = synthesize(tmp_path / 'external', profile, trial_count=1)[0]
    bad = tmp_path / 'broken.emg'
    bad.write_bytes(b'broken')
    messages = []
    monkeypatch.setattr(window, 'show_transfer_result', lambda *args, **kw: messages.append((args, kw)))
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileNames', lambda *a, **k: ([str(source), str(bad)], ''))
    window.import_record()
    assert window.records.count() == 1 and window.replay_records.count() == 1
    item = window.records.item(0)
    assert item.checkState() == C.Qt.Checked
    imported = Path(item.data(C.Qt.UserRole))
    assert imported.is_relative_to(window.session.root)
    assert len(messages[-1][0][2]) == 1
    source.unlink()
    destination = tmp_path / '作业'
    destination.mkdir()
    monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *a, **k: str(destination))
    window.export_records()
    exported = list(destination.glob('*.emg'))
    assert len(exported) == 1
    assert read_recording(exported[0])[0] == read_recording(imported)[0]
    reopened = MainWindow(window.session.root)
    reopened.timer.stop()
    try:
        assert reopened.records.count() == 1
        assert Path(reopened.records.item(0).data(C.Qt.UserRole)) == imported
    finally:
        reopened.close()


def test_cancel_is_noop_and_active_tasks_block_transfers(window, tmp_path, monkeypatch):
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileNames', lambda *a, **k: ([], ''))
    window.import_record()
    assert not window.session.root.exists()
    window.training = object()
    try:
        window.update_controls()
        for item in (window.library.import_button, window.library.export_button, window.library.bundle_button):
            assert not item.isEnabled()
        with pytest.raises(ValueError, match='结束'):
            window.import_record()
        with pytest.raises(ValueError, match='结束'):
            window.export_model()
    finally:
        window.training = None


def test_replay_import_is_persistent_and_export_available(window, tmp_path, profile, monkeypatch):
    source = synthesize(tmp_path / 'external', profile, trial_count=1)[0]
    monkeypatch.setattr(window, 'choose_data', lambda: str(source))
    window.import_replay()
    assert window.source.currentData() == 'replay'
    assert Path(window.replay_records.currentData()).is_relative_to(window.session.root)
    window.tabs.setCurrentIndex(3)
    W.QApplication.processEvents()
    assert not window.replay_actions.isHidden()
    assert window.replay_manage.isEnabled()


def test_help_search_and_developer_document(window):
    window.open_help()
    dialog = window.help_dialog
    assert dialog.isVisible()
    page = dialog.tabs.widget(0)
    page.search.setText('导出')
    assert page.contents.count() > 0
    assert '导出' in page.browser.toPlainText()
    page.search.setText('不存在的搜索词xyz')
    assert '没有找到' in page.browser.toPlainText()
    page.search.clear()
    window.open_help(1)
    assert dialog is window.help_dialog and dialog.tabs.currentIndex() == 1
    tech = dialog.tabs.widget(1)
    tech.search.setText('LiteCNN1D')
    assert tech.contents.count() > 0
    assert 'LiteCNN1D' in tech.browser.toPlainText()
    dialog.close()


def test_model_dialog_export_import_and_restart(window, tmp_path, profile, monkeypatch):
    from emg_lab.training import train
    records = synthesize(tmp_path / 'external', profile, trial_count=1)
    model = train(dict(recordings=records, data_root=tmp_path / 'external', name='同学模型', epochs=1))
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(model / 'model.onnx'), ''))
    window.import_model()
    imported = window.models.currentData()
    assert window.models.count() == 1 and Path(imported).is_relative_to(window.session.root)
    destination = tmp_path / '交作业'
    destination.mkdir()
    monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *a, **k: str(destination))
    monkeypatch.setattr(window, 'show_transfer_result', lambda *a, **k: None)
    window.export_model()
    package, = destination.glob('*.emgmodel')
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(package), ''))
    window.import_model()
    assert window.models.count() == 1 and window.models.currentData() == imported
    reopened = MainWindow(window.session.root)
    reopened.timer.stop()
    try:
        assert reopened.models.count() == 1
        assert reopened.models.currentData() == imported
    finally:
        reopened.close()
