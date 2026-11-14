"""Capture-only data contracts, raw preservation and robot-page workflow; no hardware."""

import csv
import zipfile
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from emg_lab.backend.data import catalog, transfer
from emg_lab.backend.data.capture import CaptureRun
from emg_lab.backend.data.storage import read_recording
from emg_lab.backend.learning.dataset import prepare_dataset
from emg_lab.contracts.acquisition import capture_task, validate_plan
from emg_lab.contracts.tasks import ROBOT, task_from_metadata
from emg_lab.signal import SignalConfig


def plan_for(profile, count=20):
    return dict(
        version=1,
        operator="P01",
        wearing="右臂，第 2 次佩戴",
        notes="自定义采集测试",
        channels=[
            dict(channel_id=c, muscle=f"肌肉 {c}", notes="位置记录") for c in profile["channel_ids"]
        ],
        conditions=[
            dict(
                id=f"stable_{i}",
                name=f"动作 {i}",
                body_part="右手",
                effort="轻力" if i % 2 else "重力",
                save_name=f"自定义名称_{i}",
                notes="保持姿势",
            )
            for i in range(count)
        ],
        selected_ids=[f"stable_{i}" for i in range(count)],
    )


def index_rows(path):
    with path.with_suffix(".index.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def capture_record(tmp_path, profile, plan, trials=1):
    run = CaptureRun(
        tmp_path,
        "GROUP",
        "动作研究",
        profile,
        SignalConfig(),
        trial_count=trials,
        action_s=1.2,
        capture_plan=plan,
    )
    raw = (
        np.random.default_rng(7)
        .normal(size=(run.session_length, len(profile["channel_ids"])))
        .astype(np.float32)
    )
    for block in np.array_split(raw, 37):
        run.feed(block)
    return run, raw


def test_twenty_conditions_preserve_raw_and_sample_labels(tmp_path, profile):
    plan = plan_for(profile)
    run, expected = capture_record(tmp_path, profile, plan, trials=2)
    plan["conditions"][0]["name"] = "后续改名不影响已采记录"
    meta, raw, labels = read_recording(run.run_path)
    np.testing.assert_array_equal(raw, expected)
    assert meta["capture_only"] and len(labels) == 40
    assert task_from_metadata(meta).names[0] == "动作 0"
    assert meta["capture_plan"]["channels"][0]["muscle"] == "肌肉 1"
    assert meta["completed_trials"] == meta["usable_trials"] == 2
    with zipfile.ZipFile(run.run_path) as archive:
        assert set(archive.namelist()) == {"emg.bin", "labels.csv", "meta.json"}
    rows = index_rows(run.run_path)
    assert len(rows) == 40 and len({r["segment_name"] for r in rows}) == 40
    for label, row in zip(labels, rows):
        assert label["start_sample"] == int(row["start_sample"])
        assert label["end_sample"] == int(row["end_sample"])
        assert label["class_name"] == row["condition_id"]
        assert row["complete_segment"] == "True"
        assert row["operator"] == "P01"
    assert rows[0]["save_name"] == "自定义名称_0" and rows[0]["effort"] == "重力"
    assert rows[0]["start_sample"] == "3000" and rows[0]["end_sample"] == "4200"
    entries = catalog.catalogue(tmp_path)
    assert len(entries) == 1 and "待离线分析" in catalog.describe(entries[0])
    with pytest.raises(ValueError, match="尚未配置"):
        prepare_dataset([run.run_path])


def test_subset_and_single_action_keep_stable_identity(tmp_path, profile):
    plan = plan_for(profile, 5)
    plan["selected_ids"] = ["stable_4"]
    run, _ = capture_record(tmp_path, profile, plan, trials=3)
    meta, _, labels = read_recording(run.run_path)
    assert len(meta["capture_plan"]["conditions"]) == 5
    assert meta["classes"] == ["stable_4"]
    assert [row["class_id"] for row in labels] == [0, 0, 0]
    assert {row["condition_id"] for row in index_rows(run.run_path)} == {"stable_4"}


def test_early_stop_indexes_partial_action_and_rejected_trial(tmp_path, profile):
    run = CaptureRun(
        tmp_path,
        "GROUP",
        "中断",
        profile,
        SignalConfig(),
        trial_count=3,
        action_s=1.2,
        capture_plan=plan_for(profile, 2),
    )
    n = run.trial_length + run.prepare + 200
    expected = np.ones((n, len(profile["channel_ids"])), np.float32)
    run.feed(expected)
    run.reject_trial(2, "动作做错")
    run.stop()
    meta, raw, labels = read_recording(run.run_path)
    np.testing.assert_array_equal(raw, expected)
    assert not meta["complete"] and meta["completed_trials"] == 1 and len(labels) == 2
    rows = index_rows(run.run_path)
    assert len(rows) == 3 and rows[-1]["end_sample"] == str(n)
    assert rows[-1]["complete_segment"] == rows[-1]["complete_trial"] == "False"
    assert rows[-1]["valid"] == "False" and rows[-1]["rejection_reason"] == "动作做错"


def test_custom_transfer_and_bundle_rebuild_derived_index(tmp_path, profile):
    plan = plan_for(profile, 2)
    run, _ = capture_record(tmp_path / "original", profile, plan)
    destination = tmp_path / "exports"
    destination.mkdir()
    task = capture_task(plan)
    exported = transfer.export_recording(run.run_path, destination, task)
    assert index_rows(exported)[0]["recording"] == exported.name
    result = transfer.import_recording(exported, tmp_path / "new", task)
    assert index_rows(result.path)[0]["record_id"] == index_rows(run.run_path)[0]["record_id"]
    result.path.with_suffix(".index.csv").unlink()
    assert transfer.import_recording(exported, tmp_path / "new", task).reused
    assert result.path.with_suffix(".index.csv").is_file()
    entries = catalog.catalogue(tmp_path / "original")
    bundle, _ = catalog.export_bundle(entries, entries, destination)
    paths, _ = catalog.bundle_files(bundle)
    restored = catalog.import_file(paths[0], tmp_path / "restored")
    assert len(index_rows(restored.path)) == 2


@pytest.mark.parametrize("change", ["empty", "duplicate", "channels", "name"])
def test_invalid_plan_creates_no_recording(tmp_path, profile, change):
    plan = plan_for(profile, 2)
    if change == "empty":
        plan["selected_ids"] = []
    elif change == "duplicate":
        plan["conditions"][1]["id"] = plan["conditions"][0]["id"]
    elif change == "channels":
        plan["channels"].reverse()
    else:
        plan["conditions"][0]["name"] = ""
    with pytest.raises(ValueError):
        CaptureRun(tmp_path, "GROUP", "无效", profile, SignalConfig(), capture_plan=plan)
    assert not list(tmp_path.rglob("*.emg")) and not list(tmp_path.rglob("emg.bin"))


def test_task_validation_does_not_reinterpret_custom_as_robot(profile):
    plan = validate_plan(plan_for(profile, 2))
    task = capture_task(plan)
    meta = dict(task.metadata, capture_plan=plan, capture_only=True)
    assert task_from_metadata(meta) != ROBOT
    bad = deepcopy(meta)
    bad["classes"].reverse()
    with pytest.raises(ValueError):
        task_from_metadata(bad)


def test_random_order_index_matches_saved_labels(tmp_path, profile):
    run = CaptureRun(
        tmp_path,
        "GROUP",
        "随机",
        profile,
        SignalConfig(),
        trial_count=2,
        action_s=1.2,
        capture_plan=plan_for(profile, 20),
        random_order=True,
    )
    run.feed(np.zeros((run.session_length, len(profile["channel_ids"])), np.float32))
    meta, _, labels = read_recording(run.run_path)
    assert meta["random_order"] and meta["order_seed"] is not None
    assert [r["class_id"] for r in labels] == meta["actual_order"]
    assert [r["condition_id"] for r in index_rows(run.run_path)] == [
        r["class_name"] for r in labels
    ]


def test_custom_metadata_order_cannot_disagree_with_sample_labels(tmp_path, profile):
    run, _ = capture_record(tmp_path, profile, plan_for(profile, 2))
    import json

    with zipfile.ZipFile(run.run_path) as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    meta = json.loads(payload["meta.json"])
    meta["actual_order"].reverse()
    payload["meta.json"] = json.dumps(meta).encode()
    with zipfile.ZipFile(run.run_path, "w") as archive:
        for name, content in payload.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="时序不一致"):
        read_recording(run.run_path)


def test_simulated_device_subprocess_custom_capture_autosaves(tmp_path):
    import time

    from emg_lab.backend.application import ApplicationService
    from emg_lab.contracts.events import DeviceConfig

    service = ApplicationService(tmp_path, local_root=tmp_path / "logs")
    events = []
    service.events.connect(events.append)
    try:
        service.connect_device(DeviceConfig("模拟练习", (1, 2)))
        deadline = time.monotonic() + 15
        while not service.device_ready or not len(service.snapshot()["raw"]):
            assert time.monotonic() < deadline, events
            time.sleep(0.02)
        plan = plan_for(service.profile, 2)
        path = service.start_capture("GROUP", "模拟子进程采集", 1, 1.2, capture_plan=plan)
        deadline = time.monotonic() + 15
        while service.capture:
            assert time.monotonic() < deadline, events
            time.sleep(0.02)
        meta, raw, labels = read_recording(path)
        assert meta["complete"] and raw.shape == (8400, 2) and len(labels) == 2
        assert len(index_rows(path)) == 2
    finally:
        service.close()


@pytest.fixture
def window(tmp_path, profile):
    from PySide6 import QtWidgets as W

    from emg_lab.backend.application import ApplicationService
    from emg_lab.frontend.window import MainWindow, configure_app

    app = W.QApplication.instance() or W.QApplication([])
    configure_app(app)
    service = ApplicationService(tmp_path, local_root=tmp_path / "logs", background=False)
    service.set_profile(profile)
    service._device_ready = True  # Deliberate fixture; never create a physical device.
    service.feed(np.ones((1000, len(profile["channel_ids"])), np.float32))
    w = MainWindow(tmp_path, backend=service)
    w.timer.stop()
    w.select_task("robot")
    w.tabs.setCurrentIndex(1)
    w.capture_mode.setCurrentIndex(w.capture_mode.findData("custom"))
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def test_robot_page_twenty_conditions_capture_without_scene(window, profile, monkeypatch):
    from PySide6 import QtWidgets as W

    editor = window.custom_capture
    editor.set_plan(plan_for(profile))
    editor.sync_channels()
    monkeypatch.setattr(window.scene, "start", lambda *a: pytest.fail("Custom capture opened 3D"))
    window.trial_count.setValue(1)
    window.action_seconds.setValue(1.2)
    window.backend.save_notes(window.group.text(), dict(actions="旧机器人命令映射"))
    window.start_capture()
    assert not editor.isEnabled() and not window.capture_mode.isEnabled()
    assert window.backend.task == ROBOT
    state = window.backend.capture
    assert state.metadata["capture_only"]
    assert state.metadata["collection_notes"] == {}
    window.backend.feed(np.ones((3200, len(profile["channel_ids"])), np.float32))
    window.tick()
    assert "动作 0" in window.cue.text() and "重力" in window.capture_status.text()
    window.backend.feed(np.ones((84000 - 3200, len(profile["channel_ids"])), np.float32))
    window.backend.poll()
    W.QApplication.processEvents()
    assert window.backend.capture is None and editor.isEnabled()
    assert Path(state.identity).is_file() and len(index_rows(Path(state.identity))) == 20
    assert "自定义采集" in window.notice.text()
    window.library.refresh()
    assert any(e.meta.get("capture_only") for e in window.library.entries)
    with pytest.raises(ValueError, match="尚未配置"):
        window.backend.validate_use("train", window.library.entries)


def test_editor_single_action_copy_and_plan_roundtrip(window, profile, tmp_path):
    editor = window.custom_capture
    changed = []
    editor.changed.connect(lambda: changed.append(True))
    editor.operator.setText("P02")
    assert changed
    editor.set_plan(plan_for(profile, 20))
    identity = editor.table.item(7, 1).data(256)
    editor.mode.setCurrentIndex(1)
    editor.table.setCurrentCell(7, 1)
    assert editor.plan()["selected_ids"] == [identity]
    editor.duplicate_condition()
    assert editor.table.rowCount() == 21
    assert editor.table.item(20, 1).data(256) != identity
    path = tmp_path / "方案.json"
    window.backend.save_capture_plan(path, editor.plan())
    restored = window.backend.load_capture_plan(path)
    editor.set_plan(restored)
    assert len(editor.selected_ids()) == 1
    assert editor.plan()["channels"] == restored["channels"]
    window.backend.save_capture_plan(path, editor.plan())
    assert window.backend.load_capture_plan(path) == editor.plan()
    window.trial_count.setValue(7)
    window.action_seconds.setValue(2.5)
    window.random_order.setChecked(True)
    configured = editor.plan()
    window.trial_count.setValue(1)
    editor.set_plan(configured)
    assert window.trial_count.value() == 7 and window.action_seconds.value() == 2.5
    assert window.random_order.isChecked()
