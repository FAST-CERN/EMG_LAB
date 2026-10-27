import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from emg_lab.waveform import WaveformPreview
from emg_lab.engine import Session


@pytest.fixture
def preview():
    app = W.QApplication.instance() or W.QApplication([])
    widget = WaveformPreview()
    widget.set_profile(dict(channel_ids=[2, 5], sampling_rate=1000., unit='a.u.'))
    yield widget
    widget.close()
    app.processEvents()


def test_channel_grid_preserves_amplitude_and_shared_scale(preview):
    preview.scale.setCurrentIndex(preview.scale.findData('shared'))
    raw = np.column_stack((np.linspace(-5, 5, 3000), np.linspace(-.1, .1, 3000)))
    filtered = raw*.5
    preview.update_data(raw, filtered, 1000.)
    assert [p.getPlotItem().titleLabel.text for p in preview.plots] == ['CH 2', 'CH 5']
    assert preview.grid.itemAtPosition(0, 1).widget() is preview.plots[1]
    np.testing.assert_array_equal(preview.filtered_curves[0].yData, filtered[:, 0])
    np.testing.assert_array_equal(preview.filtered_curves[1].yData, filtered[:, 1])
    assert preview.plots[0].viewRange()[1] == preview.plots[1].viewRange()[1]
    assert preview.plots[0].viewRange()[1] == [-2.75, 2.75]
    preview.display.setCurrentIndex(preview.display.findData('both'))
    assert preview.raw_curves[0].isVisible() and preview.filtered_curves[0].isVisible()
    assert preview.plots[0].viewRange()[1] == [-5.5, 5.5]
    preview.scale.setCurrentIndex(preview.scale.findData('individual'))
    assert preview.plots[0].viewRange()[1][1] > 40*preview.plots[1].viewRange()[1][1]
    preview.scale.setCurrentIndex(preview.scale.findData('fixed'))
    preview.fixed_limit.setValue(2.)
    assert all(p.viewRange()[1] == [-2., 2.] for p in preview.plots)


def test_default_axis_stays_fixed_across_amplitude_changes(preview):
    assert preview.scale.currentData() == 'fixed'
    for gain in (.01, 4., .2):
        raw=np.full((1000,2),gain)
        preview.update_data(raw,raw,1000.)
        assert all(p.viewRange()[1] == [-1.,1.] for p in preview.plots)
    preview.fixed_limit.setValue(.5)
    preview.set_profile(dict(channel_ids=[1,3],sampling_rate=1000.,unit='a.u.'))
    assert all(p.viewRange()[1] == [-.5,.5] for p in preview.plots)


def test_time_window_and_pause_preserve_samples(preview):
    raw = np.arange(20000).reshape(10000, 2).astype(float)
    preview.update_data(raw, raw*.5, 1000.)
    preview.time_window.setCurrentIndex(preview.time_window.findData(1))
    np.testing.assert_array_equal(preview.raw_curves[0].yData, raw[-1000:, 0])
    np.testing.assert_allclose(preview.raw_curves[0].xData[[0, -1]], [-.999, 0.])
    preview.pause.setChecked(True)
    preview.update_data(raw+100, raw*.5+50, 1000.)
    np.testing.assert_array_equal(preview.raw_curves[0].yData, raw[-1000:, 0])
    preview.pause.setChecked(False)
    preview.update_data(raw+100, raw*.5+50, 1000.)
    np.testing.assert_array_equal(preview.raw_curves[0].yData, raw[-1000:, 0]+100)
    preview.time_window.setCurrentIndex(preview.time_window.findData(10))
    assert len(preview.raw_curves[0].yData) == 10000
    assert preview.plots[0].viewRange()[0] == [-10., 0.]


def test_preview_history_does_not_limit_recording(tmp_path, profile):
    session = Session(tmp_path)
    session.set_profile(profile)
    block = np.zeros((1000, 4), dtype=np.float32)
    session.feed(block)
    session.start_capture('TEST', '波形窗口', trial_count=2, action_s=1.)
    capture = session.capture
    try:
        for i in range(12):
            session.feed(block+i)
        assert session.raw.shape == (10000, 4)
        assert session.filtered.shape == (10000, 4)
        assert capture.writer.count == 12000
    finally:
        session.close()
