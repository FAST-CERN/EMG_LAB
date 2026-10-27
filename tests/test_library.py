"""Unified file management, portable bundles and source-independent scenes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import date
import json
from pathlib import Path
import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from emg_lab import catalog
from emg_lab.app import MainWindow,configure_app
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.tasks import HAND
from emg_lab.storage import read_recording
from conftest import synthesize


@pytest.fixture
def window(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    w = MainWindow(tmp_path/'local')
    w.timer.stop()
    w.show()
    yield w
    w.close()
    app.processEvents()


def test_filters_date_boundaries_and_missing_dates():
    def item(name,day,group='G01',kind='recording'):
        return catalog.Entry(kind,Path(name),dict(name=name,created_at=day,group=group,device='Cometa'))
    entries = [item('a','2026-10-01T23:59:00'),item('b','2026-10-02'),item('c','2026-10-03','G02','model'),item('d','')]
    assert [e.path.name for e in catalog.filter_entries(entries,start=date(2026,10,1),end=date(2026,10,2))]==['a','b']
    assert [e.path.name for e in catalog.filter_entries(entries,group='G02',kind='model',device='Cometa',query='C')]==['c']
    assert catalog.filter_entries(entries,start=date(2026,10,3),end=date(2026,10,1))==[]


def test_mixed_import_filters_selection_and_training_jump(window,tmp_path,profile,monkeypatch):
    robot = synthesize(tmp_path/'external',profile,trial_count=1)[0]
    run = CaptureRun(tmp_path/'external','HAND_GROUP','手部数据',profile,SignalConfig(),trial_count=1,action_s=1.,task=HAND)
    run.feed(np.zeros((run.session_length,4),dtype=np.float32))
    monkeypatch.setattr(window,'show_transfer_result',lambda *a,**k:None)
    library = window.library
    library.import_paths([robot,run.run_path])
    assert len(library.entries)==2 and len(library.selected())==2
    assert {e.task.key for e in library.entries}=={'robot','hand'}
    library.target.setCurrentIndex(library.target.findData('robot'))
    assert len(library.visible_entries)==1 and len(library.selected())==1
    selected = library.selected()
    window.use_library('train',selected)
    assert window.tabs.currentIndex()==2 and window.task.key=='robot'
    assert window.records.item(0).checkState()==C.Qt.Checked
    library.reset_filters()
    library.check_visible()
    with pytest.raises(ValueError,match='同一个实验目标'):
        window.use_library('train',library.selected())
    library.target.setCurrentIndex(library.target.findData('hand'))
    window.use_library('replay',library.selected())
    assert window.task==HAND and window.source.currentData()=='replay'
    assert Path(window.replay_records.currentData()).is_relative_to(window.session.root)
    window.training = object()
    try:
        window.update_controls()
        assert not library.import_button.isEnabled() and not library.replay_button.isEnabled()
        with pytest.raises(ValueError,match='结束'):
            library.import_paths([robot])
    finally:
        window.training = None


def test_bundle_includes_linked_records_roundtrips_and_checks_tampering(tmp_path,profile):
    from emg_lab.training import train
    source = tmp_path/'source'
    record = synthesize(source,profile,trial_count=1)[0]
    model = train(dict(recordings=[record],data_root=source,name='课堂模型',epochs=1))
    entries = catalog.catalogue(source)
    selected = [e for e in entries if e.kind=='model']
    folder,manifest = catalog.export_bundle(selected,entries,tmp_path)
    assert len(manifest['files'])==2 and not manifest['missing_training_record_ids']
    assert len(manifest['source']['fingerprint'])==64
    paths,_ = catalog.bundle_files(folder)
    another = tmp_path/'another-computer'
    for path in paths:
        catalog.import_file(path,another)
    restored = catalog.catalogue(another)
    assert {e.kind for e in restored}=={'recording','model'}
    restored_record = next(e for e in restored if e.kind=='recording')
    np.testing.assert_array_equal(read_recording(restored_record.path)[1],read_recording(record)[1])
    assert catalog.import_file(paths[0],another).reused
    assert manifest['files'][0]['path'].startswith('models/')
    target = paths[-1]
    target.write_bytes(target.read_bytes()+b'corrupt')
    with pytest.raises(ValueError,match='校验失败'):
        catalog.bundle_files(folder)


def test_bundle_rejects_escape_and_reports_missing_training_data(tmp_path):
    meta = dict(name='模型',group='G01',device='Cometa',split={'train':[dict(record_id='missing')]})
    model = catalog.Entry('model',tmp_path/'model',meta)
    entries,missing = catalog.with_training_data([model],[])
    assert entries==[model] and missing==['missing']
    (tmp_path/'manifest.json').write_text(json.dumps(dict(format='emg-classroom-bundle',version=1,complete=True,
        files=[dict(path='../outside.emg',kind='recording',sha256='bad',identity='id',target='robot')])),'utf-8')
    with pytest.raises(ValueError,match='不合法'):
        catalog.bundle_files(tmp_path)


def test_library_footer_and_table_fit_small_window(window):
    window.open_library()
    for size in ((900,600),(1160,820)):
        window.resize(*size)
        W.QApplication.processEvents()
        scroll = window.page_scrolls['数据与模型']
        assert scroll.horizontalScrollBar().maximum()==0
        for button in (window.library.import_button,window.library.bundle_button,window.library.model_button):
            assert button.visibleRegion().boundingRect()==button.rect()
    window.library.period.setCurrentIndex(window.library.period.findData('custom'))
    W.QApplication.processEvents()
    assert window.library.date_range.isVisible()
    window.open_help(2)
    page = window.help_dialog.tabs.widget(2)
    page.search.setText('Cometa')
    assert page.contents.count()>0
    page.show_chapter(page.contents.currentItem())
    assert page.browser.document().firstBlock().blockFormat().lineHeight()==140
    window.help_dialog.close()


def test_live_and_replay_scene_use_same_worker_and_settings(window):
    from emg_lab.physics.scene import SceneWindow
    live = SceneWindow('open',source='live')
    replay = SceneWindow('open',source='replay')
    try:
        assert live.scene_id==replay.scene_id=='g1_outdoor_15m_v1'
        assert type(live.worker) is type(replay.worker)
        assert live.settings==replay.settings
        assert '实时推理' in live.windowTitle() and '离线回放' in replay.windowTitle()
        assert '标签不直接控制' in replay.hint.text()
    finally:
        live.close()
        replay.close()
