"""Student-facing regressions; no real device or DDS participant is created."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import pytest
import numpy as np
from PySide6 import QtWidgets as W
from emg_lab.app import MainWindow, configure_app
from conftest import synthesize


@pytest.fixture
def window(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    w = MainWindow(tmp_path)
    w.timer.stop()
    w.backend._timer.stop()
    w.stack.setCurrentIndex(1)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def test_mock_input_is_only_shown_for_live_simulated_device(window, profile):
    window.tabs.setCurrentIndex(3)
    assert window.mock_panel.isHidden()

    window.backend._device_ready = True
    window.backend._session.set_profile(dict(profile, device="Cometa"))
    window.update_controls()
    assert window.mock_panel.isHidden()
    window.backend._session.set_profile(dict(profile, device="Delsys"))
    window.update_controls()
    assert window.mock_panel.isHidden()
    window.backend._session.set_profile(profile)
    window.update_controls()
    assert not window.mock_panel.isHidden()
    window.source.setCurrentIndex(1)
    assert window.mock_panel.isHidden()


def test_coin_settings_are_robot_only_and_formal_values_locked(window):
    window.practice_mode.setCurrentIndex(window.practice_mode.findData("coins"))
    assert not window.competition_panel.isHidden()
    assert window.infer_scene.isChecked() and not window.infer_scene.isEnabled()
    assert not window.dds_check.isEnabled()
    window.race_official.setChecked(True)
    assert window.race_count.value() == 6 and window.race_seconds.value() == 120
    assert not window.race_count.isEnabled() and not window.race_seconds.isEnabled()
    window.select_task("hand")
    assert window.practice_mode.currentData() == "free"
    assert window.competition_panel.isHidden()


def test_latest_selection_selects_one_file_not_all_siblings(window, tmp_path, profile):
    first = synthesize(tmp_path, profile, name="第一次", trial_count=1)[0]
    latest = synthesize(tmp_path, profile, name="第二次", trial_count=2)[0]
    window.refresh_data()
    window.select_latest()
    from PySide6.QtCore import Qt

    selected = [
        window.records.item(i).data(Qt.UserRole)
        for i in range(window.records.count())
        if window.records.item(i).checkState() == Qt.Checked
    ]
    assert selected == [str(latest)]
    assert first != latest


def test_imported_data_survives_refresh_and_small_window_is_scrollable(window, tmp_path, profile):
    from emg_lab.storage import recording_metadata

    external = synthesize(tmp_path / "external", profile, trial_count=1)[0]
    window.imported_records[str(external)] = recording_metadata(external)
    window.refresh_data()
    window.refresh_data()
    assert window.records.count() == 1
    assert window.replay_records.count() == 1
    window.resize(950, 650)
    window.tabs.setCurrentIndex(3)
    W.QApplication.processEvents()
    assert window.height() == 650
    scroll = window.page_scrolls["04  使用模型"]
    assert isinstance(scroll, W.QScrollArea)
    assert not scroll.isAncestorOf(window.infer_stop)
    assert window.infer_stop.visibleRegion().boundingRect() == window.infer_stop.rect()


def test_capture_waits_for_scene_and_cancel_never_records(window, profile, monkeypatch):
    monkeypatch.setattr(window.scene, "start", lambda mode: None)
    window.backend._session.set_profile(profile)
    window.backend._session.feed(np.zeros((1000, 4), dtype=np.float32))
    window.backend._device_ready = True
    window.start_capture()
    assert window.backend._session.capture is None
    assert not window.capture_start.isEnabled() and window.capture_stop.isEnabled()
    window.stop_capture()
    window.scene.ready.emit()
    assert window.backend._session.capture is None and window.scene_pending is None
    assert not list(window.backend._session.root.glob("*/recordings/*"))


def test_scene_failure_finalizes_partial_capture(window, profile, monkeypatch):
    from emg_lab.storage import read_recording

    monkeypatch.setattr(window.scene, "start", lambda mode: None)
    window.backend._session.set_profile(profile)
    window.backend._session.feed(np.zeros((1000, 4), dtype=np.float32))
    window.backend._device_ready = True
    window.start_capture()
    window.scene.ready.emit()
    capture = window.backend._session.capture
    assert capture is not None
    window.backend._session.feed(np.zeros((200, 4), dtype=np.float32))
    window.scene.failed.emit("机器人已跌倒")
    assert window.backend._session.capture is None
    meta, raw, _ = read_recording(capture.run_path)
    assert meta["finalized"] and not meta["complete"]
    assert len(raw) == 200


FULL_DEVICES = [("Cometa", "Cometa"), ("Delsys", "Delsys"), ("模拟设备（无需硬件）", "模拟练习")]


def test_available_devices_by_platform():
    from emg_lab.app import available_devices

    assert available_devices("win32") == FULL_DEVICES
    assert available_devices("darwin") == [FULL_DEVICES[-1]]


@pytest.fixture
def platform_window(tmp_path, monkeypatch):
    built = []

    def build(platform_name):
        monkeypatch.setattr(sys, "platform", platform_name)
        app = W.QApplication.instance() or W.QApplication([])
        configure_app(app)
        window = MainWindow(tmp_path)
        window.timer.stop()
        window.backend._timer.stop()
        built.append(window)
        return window

    yield build
    app = W.QApplication.instance()
    for window in built:
        window.close()
    if app is not None:
        app.processEvents()


def test_device_dropdown_keeps_full_list_on_win32(platform_window):
    window = platform_window("win32")
    items = [
        (window.device_combo.itemText(i), window.device_combo.itemData(i))
        for i in range(window.device_combo.count())
    ]
    assert items == FULL_DEVICES


def test_device_dropdown_darwin_shows_mock_only(platform_window):
    window = platform_window("darwin")
    assert window.device_combo.count() == 1
    assert window.device_combo.itemData(0) == "模拟练习"
    assert window.delsys_panel.isHidden()


def test_connect_dds_without_real_machine_stack_shows_error(platform_window, monkeypatch):
    monkeypatch.setitem(sys.modules, "bsi_robot_base", None)
    window = platform_window("win32")
    window.select_task("robot")
    window.guard(window.connect_dds)
    assert window.notice.property("tone") == "error"
    assert "bsi_robot_base" in window.notice.text()


def test_queued_completion_from_previous_run_cannot_cancel_new_scene(window):
    from emg_lab.contracts.events import ApplicationEvent, CaptureState

    window.backend.set_pending("open")
    window.scene_pending = ("open", lambda: None)
    window._inference_identity = None  # The next run is still preparing its scene.
    window.on_application_event(
        ApplicationEvent(
            "inference_finished",
            dict(identity="previous-run", reason="assessment_finished", error=""),
        )
    )
    assert window.scene_pending and window.backend.pending == "open"
    window._capture_identity = "current-capture"
    previous = CaptureState("previous-capture", True, {}, {})
    window.on_application_event(ApplicationEvent("capture_finished", dict(summary=previous)))
    assert window.scene_pending and window.backend.pending == "open"
    window.scene_pending = None
    window.backend.cancel_pending()


def test_capture_completion_belongs_to_service_then_updates_view(window, profile):
    window.backend.set_profile(profile)
    window.backend.feed(np.zeros((20, 4), dtype=np.float32))
    window.backend._device_ready = True
    window.scene_check.setChecked(False)
    window.trial_count.setValue(1)
    window.action_seconds.setValue(1)
    window.begin_capture()
    capture = window.backend._session.capture
    window.backend.feed(np.zeros((capture.session_length, 4), dtype=np.float32))
    window.tick()
    assert window.backend.capture is not None  # UI ticks render; only service completes tasks.
    window.backend.poll()
    W.QApplication.processEvents()
    assert window.backend.capture is None and window._capture_identity is None
    assert window.records.count() == 1 and window.train_start.isEnabled()
