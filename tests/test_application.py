"""Headless use cases, fake acquisition and lifecycle regression scenarios."""

from types import SimpleNamespace

import numpy as np
import pytest

from emg_lab.backend.application import ApplicationService
from emg_lab.backend.data.storage import read_recording
from emg_lab.contracts.events import DeviceConfig, TrainingRequest


class FakeDevice:
    def __init__(self, config, callback, **kwargs):
        self.config, self.callback = config, callback
        self.process = SimpleNamespace(pid=id(self))
        self.closed = False
        self.commands = []

    def emit(self, kind, **payload):
        self.callback(dict(type=kind, process_id=self.process.pid, **payload))

    def send(self, action, **kwargs):
        self.commands.append((action, kwargs))

    def close(self):
        self.closed = True


@pytest.fixture
def service(tmp_path):
    devices = []

    def factory(*args, **kwargs):
        device = FakeDevice(*args, **kwargs)
        devices.append(device)
        return device

    app = ApplicationService(
        tmp_path / "data", local_root=tmp_path / "logs", device_factory=factory, background=False
    )
    app.test_devices = devices
    yield app
    app.close()


def connected(service):
    service.connect_device(DeviceConfig("模拟练习", (1, 2, 3, 4)))
    device = service.test_devices[-1]
    device.emit(
        "connected",
        profile=dict(
            device="模拟练习", sampling_rate=1000.0, channel_ids=[1, 2, 3, 4], unit="a.u."
        ),
    )
    device.emit("frame", samples=np.zeros((20, 4), dtype="f4"))
    return device


@pytest.mark.parametrize("selector", ["robot", "robot7", "hand", "hand5"])
def test_all_task_schemes_collect_without_a_frontend(service, selector):
    events = []
    service.events.connect(events.append)
    service.select_task(selector)
    connected(service)
    path = service.start_capture("TEST", "headless", trial_count=1, action_s=1.0)
    for _ in range(4 * len(service.task.classes)):
        service.feed(np.zeros((1000, 4), dtype="f4"))
        service.poll()
    assert service.capture is None
    summary = next(event.payload["summary"] for event in events if event.kind == "capture_finished")
    assert summary.completed and summary.metadata["completed_trials"] == 1
    meta, raw, labels = read_recording(path)
    assert len(labels) == len(service.task.classes)
    assert meta["classes"] == list(service.task.classes)
    assert raw.shape[1] == 4


def test_stale_events_after_disconnect_or_reconnect_are_ignored(service):
    old = connected(service)
    service.disconnect_device()
    assert old.closed and not service.device_present
    old.emit("connected", profile=dict(device="bad", channel_ids=[9]))
    assert service.profile is None
    new = connected(service)
    old.emit("error", message="stale error")
    old.emit("frame", samples=np.ones((10, 4), dtype="f4"))
    assert service.device_ready and service.profile["device"] == "模拟练习"
    assert not new.closed


def test_snapshots_cannot_mutate_backend_state(service):
    connected(service)
    profile = service.profile
    profile["channel_ids"].reverse()
    snapshot = service.snapshot()
    snapshot["profile"]["channel_ids"].clear()
    with pytest.raises(ValueError):
        snapshot["raw"][0, 0] = 1
    assert service.profile["channel_ids"] == [1, 2, 3, 4]


def test_pending_capture_cancel_creates_no_recording(service):
    connected(service)
    service.set_pending("sample")
    with pytest.raises(ValueError):
        service.select_task("hand")
    service.cancel_pending()
    assert not list(service.root.rglob("*.emg"))
    service.select_task("hand")


def test_invalid_trial_and_partial_stop_keep_raw_data(service):
    connected(service)
    path = service.start_capture("TEST", "partial", trial_count=2, action_s=1.0)
    state = service.capture
    service.reject_capture_trial(state, 1, "incorrect action")
    service.feed(np.ones((17000, 4), dtype="f4"))
    summary = service.stop_capture()
    meta, raw, labels = read_recording(path)
    assert not summary.completed and meta["rejected_trials"][0]["trial"] == 1
    assert len(raw) > 0 and labels


def test_stopping_training_closes_worker_and_filters_late_events(tmp_path):
    workers = []

    def factory(module, argument, callback, **kwargs):
        worker = FakeDevice({}, callback)
        workers.append(worker)
        return worker

    app = ApplicationService(
        tmp_path, local_root=tmp_path / "logs", background=False, training_factory=factory
    )
    events = []
    app.events.connect(events.append)
    try:
        app.start_training(TrainingRequest(("unused.emg",), "test", 1))
        worker = workers[-1]
        app.stop_training()
        worker.emit("complete", path="late")
        assert worker.closed and not app.training and not events
    finally:
        app.close()


def test_hardware_gate_rejects_mock_replay_and_extended_tasks(service):
    connected(service)
    for source in ("live", "replay"):
        with pytest.raises(ValueError):
            service.check_output(source, True)
    service.select_task("robot7")
    with pytest.raises(ValueError):
        service.check_output("live", True)


def test_cached_prediction_does_not_renew_robot_watchdog(service):
    connected(service)
    sent = []
    scene = SimpleNamespace(
        settings=None,
        update_command=lambda command, settings: sent.append(command),
        close=lambda: None,
    )
    service._scene = scene
    service._session.inference = object()
    service._session.result = dict(sample_end=500, filtered_class=3)
    service.poll()
    service.poll()
    assert sent == [3]
    service._session.result = dict(sample_end=600, filtered_class=0)
    service.poll()
    assert sent == [3, 0]


def test_output_stop_failure_does_not_skip_session_or_other_output_cleanup(service):
    connected(service)
    service._session.inference = object()
    stopped = []

    def fail():
        raise TimeoutError("stop acknowledgement lost")

    service._hand = SimpleNamespace(disable=fail)
    service._dds = SimpleNamespace(disable=lambda: stopped.append("dds"))
    try:
        with pytest.raises(RuntimeError, match="acknowledgement"):
            service.stop_inference()
        assert not service.inference and stopped == ["dds"]
    finally:
        service._hand = service._dds = None


def test_artifact_mutations_reject_pending_work_at_service_boundary(service):
    service.set_pending("sample")
    with pytest.raises(ValueError, match="结束"):
        service.catalog.import_file("unused", service.root)
    with pytest.raises(ValueError, match="结束"):
        service.transfer.import_model("unused", service.root, service.task)


def test_worker_exiting_during_construction_does_not_leave_training_busy(tmp_path):
    def factory(module, argument, callback, **kwargs):
        worker = FakeDevice({}, callback)
        worker.emit("exited", returncode=1)
        return worker

    app = ApplicationService(
        tmp_path, local_root=tmp_path / "logs", background=False, training_factory=factory
    )
    try:
        app.start_training(TrainingRequest(("unused.emg",), "test", 1))
        assert not app.training
    finally:
        app.close()


def test_assessment_write_failure_still_clears_inference(service):
    from emg_lab.backend.learning.practice import BasicAssessment

    connected(service)
    session = service._session
    session.inference = object()
    session.assessment = BasicAssessment(service.task, 1000, 500)
    session.assessment_context = {}  # Missing group deliberately fails report publication.
    with pytest.raises(RuntimeError, match="group"):
        service.stop_inference()
    assert not service.inference and session.assessment is None
