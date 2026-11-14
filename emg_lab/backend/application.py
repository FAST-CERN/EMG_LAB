"""Application use cases and ownership. No GUI toolkit is imported here."""

import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from emg_lab.contracts.events import (
    ApplicationEvent,
    CaptureState,
    DeviceConfig,
    EventHook,
    PeriodicTask,
    TrainingRequest,
)
from emg_lab.contracts.tasks import HAND, HAND5, ROBOT, ROBOT7, TASKS
from emg_lab.paths import DATA, LOCAL

from .competition import RaceConfig, check_entry, file_hash, load_rules
from .data import catalog, collection, reports, storage, transfer
from .learning.signal import compatible_profile
from .runtime.engine import Session
from .runtime.processes import DeviceProcess, JsonProcess


class ArtifactPort:
    """Keep mutation guards at the application boundary, including headless callers."""

    def __init__(self, service, module, mutations):
        self.service, self.module, self.mutations = service, module, mutations

    def __getattr__(self, name):
        function = getattr(self.module, name)
        if name not in self.mutations:
            return function

        def guarded(*args, **kwargs):
            self.service.require_idle()
            return function(*args, **kwargs)

        return guarded


class ApplicationService:
    """Single experiment owner; a frontend may subscribe but is never needed to run it."""

    def __init__(
        self,
        data_root=DATA,
        *,
        local_root=LOCAL,
        background=True,
        device_factory=DeviceProcess,
        training_factory=JsonProcess,
    ):
        self._session = Session(data_root)
        self.local_root = Path(local_root)
        self.events = EventHook()
        self._device_factory = device_factory
        self._training_factory = training_factory
        self._device = self._training = None
        self._device_generation = self._training_generation = None
        self._device_ready = self._connecting = False
        self._hand = self._dds = None
        self._dds_identity = None
        self._workers = []
        self._scene = None
        self._hand_scene = None
        self._scene_mode = None
        self._pending = None
        self._last_result = None
        self.inference_identity = None
        self._last_cue = None
        self._closed = False
        self._pump_lock = threading.RLock()
        self._timer = PeriodicTask(self._tick, 0.02)
        if background:
            self._timer.start()
        self.catalog = ArtifactPort(self, catalog, {"import_file", "export_entry", "export_bundle"})
        self.transfer = ArtifactPort(
            self, transfer, {"import_recording", "export_recording", "import_model", "export_model"}
        )

    def emit(self, kind, **payload):
        self.events.emit(ApplicationEvent(kind, payload))

    @property
    def root(self):
        return self._session.root

    @property
    def task(self):
        return self._session.task

    @property
    def profile(self):
        return deepcopy(self._session.profile) if self._session.profile else None

    @property
    def inference(self):
        return self._session.inference is not None

    @property
    def device_present(self):
        return self._device is not None

    @property
    def training(self):
        return self._training is not None

    @property
    def device_ready(self):
        return self._device_ready

    @property
    def connecting(self):
        return self._connecting

    @property
    def pending(self):
        return self._pending

    @property
    def last_assessment_path(self):
        return self._session.last_assessment_path

    @property
    def error(self):
        return self._session.error

    @property
    def capture(self):
        with self._session.lock:
            value = self._session.capture
            return (
                CaptureState(
                    str(value.run_path),
                    value.completed,
                    value.status(),
                    deepcopy(value.writer.meta),
                )
                if value
                else None
            )

    def snapshot(self):
        value = self._session.snapshot()
        for key in ("profile", "result", "capture", "assessment"):
            value[key] = deepcopy(value[key])
        for key in ("raw", "filtered"):
            value[key].setflags(write=False)
        value.update(training=self.training, pending=self.pending, device_ready=self.device_ready)
        return value

    @property
    def result(self):
        return self.snapshot()["result"]

    def require_idle(self):
        if self.capture or self.inference or self.training or self.pending:
            raise ValueError("请先结束采集、训练或推理。")

    def select_task(self, selector):
        self.require_idle()
        task = TASKS[selector]
        if task != self.task:
            self.disconnect_hand()
            self.disconnect_dds()
            self.stop_scene()
            self._session.task = task
            self._session.result = None
            self._session.last_assessment_path = None
            self._last_result = None

    def set_pending(self, mode):
        self.require_idle()
        self._pending = mode

    def cancel_pending(self):
        self._pending = None

    def set_profile(self, profile):
        self._session.set_profile(profile)

    def set_filter(self, config):
        self._session.set_filter(config)

    def feed(self, samples):
        self._session.feed(samples)

    def read_metadata(self, path):
        return storage.read_json(path)

    def recordings(self):
        return storage.list_recordings(self.root)

    def models(self):
        return storage.list_models(self.root)

    def notes(self, group):
        return collection.load_notes(self.root, group, self.task)

    def save_notes(self, group, notes):
        collection.save_notes(self.root, group, self.task, notes)

    def save_capture_plan(self, path, plan):
        from emg_lab.contracts.acquisition import validate_plan

        self.require_idle()
        storage.write_json(path, validate_plan(plan))

    def load_capture_plan(self, path):
        from emg_lab.contracts.acquisition import validate_plan

        self.require_idle()
        if Path(path).stat().st_size > 1024 * 1024:
            raise ValueError("方案文件过大。")
        return validate_plan(storage.read_json(path))

    def signal_check(self, *args):
        return collection.signal_check(*args)

    def rules(self):
        return load_rules()

    def find_reports(self, group=""):
        return reports.find_reports(self.root, group)

    def export_reports(self, rows, destination):
        return reports.export_reports(rows, destination)

    def validate_use(self, action, entries):
        self.require_idle()
        if not entries or len({entry.task.task_type for entry in entries}) != 1:
            raise ValueError("一次操作请选择同一个实验目标的文件。")
        if any(e.meta.get("capture_only") for e in entries):
            raise ValueError(
                "自定义采集仅用于保存和分析，尚未配置训练与机器人映射；请导出原始数据。"
            )
        if action == "train":
            if any(e.kind != "recording" or not storage.usable_record(e.meta) for e in entries):
                raise ValueError("训练只能选择至少包含一组完整动作的数据。")
            first = entries[0].meta
            for entry in entries:
                compatible_profile(first, entry.meta)
                if (
                    first["group"] != entry.meta["group"]
                    or first["preprocessing"] != entry.meta["preprocessing"]
                ):
                    raise ValueError("一次训练请选择同一组别、相同滤波设置的数据。")
        elif (
            action not in ("replay", "model")
            or len(entries) != 1
            or entries[0].kind != ("recording" if action == "replay" else "model")
        ):
            raise ValueError("请选择一份匹配用途的数据或模型。")

    def connect_device(self, config: DeviceConfig):
        self.require_idle()
        if self._device:
            raise ValueError("请先断开当前设备。")
        channels = list(config.channel_ids)
        if (
            not channels
            or len(channels) != len(set(channels))
            or any(type(c) is not int or not 1 <= c <= 16 for c in channels)
        ):
            raise ValueError("传感器编号应为不重复的 1–16。")
        if config.action != "connect" and config.device != "Delsys":
            raise ValueError("请先将设备切换为 Delsys。")
        self._connecting = True
        try:
            token = self._device_generation = object()
            device = self._device_factory(
                asdict(config),
                lambda event: self._device_event(event, token),
                log_dir=self.local_root,
            )
            if self._device_generation is token:
                self._device = device
            else:
                device.close()
        except Exception:
            self._connecting = False
            raise

    def accept_device_event(self, event):
        self._device_event(event)

    def _device_event(self, event, token=None):
        if self._closed or (token is not None and token is not self._device_generation):
            return
        # Process construction can start delivering events before assignment completes.
        device = self._device
        if device is not None and event.get("process_id") != device.process.pid:
            return
        try:
            kind = event["type"]
            if kind == "connected":
                self._session.set_profile(event["profile"])
                self._device_ready, self._connecting = True, False
            elif kind == "frame":
                self._session.feed(event["samples"])
                return
            elif kind in ("error", "exited"):
                self._device_ready = self._connecting = False
                if kind == "exited":
                    self._device = None
                    self._device_generation = None
            if kind in ("error", "exited"):
                self.stop_capture()
                self.stop_inference()
            self.emit("device", **event)
        except Exception as error:
            self.emit(
                "device", type="error", message=str(error), process_id=event.get("process_id")
            )

    def cue(self, class_id):
        if self._device:
            self._device.send("cue", cue=class_id)

    def disconnect_device(self):
        self.stop_capture()
        self.stop_inference()
        self._device_generation = None
        device, self._device = self._device, None
        if device:
            device.close()
        self._device_ready = self._connecting = False
        self._session.profile = None

    def start_capture(self, group, name, trial_count=5, action_s=5, **kwargs):
        if self.training or self.inference:
            raise ValueError("请先结束当前任务。")
        if not self.device_ready:
            raise ValueError("请先连接设备。")
        if kwargs.get("capture_plan") is not None:
            if self.task.key != "robot":
                raise ValueError("自定义采集目前仅在机器人实验中提供。")
            self.stop_scene()
        self._pending = None
        self._last_cue = None
        return self._session.start_capture(group, name, trial_count, action_s, **kwargs)

    def reject_capture_trial(self, state, trial, reason):
        capture = self._session.capture
        if not capture or str(capture.run_path) != state.identity:
            raise ValueError("采集已切换。")
        self._session.reject_capture_trial(capture, trial, reason)

    def stop_capture(self):
        self._pending = None
        state = self.capture
        if state:
            original = self._session.capture
            self._session.stop_capture()
            state = CaptureState(
                state.identity, state.completed, state.status_value, dict(original.writer.meta)
            )
            self.cue(0)
        return state

    def start_training(self, request: TrainingRequest):
        self.require_idle()
        if not request.recordings:
            raise ValueError("请选择训练数据。")
        storage.safe_name(request.name)
        path = self.local_root / f"train-{uuid.uuid4().hex}.json"
        storage.write_json(
            path,
            dict(
                recordings=list(request.recordings),
                name=request.name,
                epochs=request.epochs,
                architecture=request.architecture,
                model_config=deepcopy(request.model_config),
                data_root=str(self.root),
            ),
        )
        token = self._training_generation = object()
        worker = self._training_factory(
            "emg_lab.train_worker",
            str(path),
            lambda event: self._train_event(event, token),
            log_dir=self.local_root,
        )
        if self._training_generation is token:
            self._training = worker

    def _train_event(self, event, token=None):
        if self._closed or (token is not None and token is not self._training_generation):
            return
        worker = self._training
        if worker is not None and event.get("process_id") != worker.process.pid:
            return
        if event["type"] == "exited":
            self._training = None
            self._training_generation = None
        self.emit("training", **event)

    def stop_training(self):
        self._training_generation = None
        worker, self._training = self._training, None
        if worker:
            worker.close()

    def prepare_competition(self, config: RaceConfig, model, source, recording):
        baseline = check_entry(config, source, self.profile)
        meta = storage.read_json(Path(model) / "metadata.json")
        return dict(
            config=config,
            data_root=self.root,
            context=dict(
                run_token=uuid.uuid4().hex,
                model=str(Path(model).resolve()),
                model_id=meta["model_id"],
                model_hashes={
                    n: file_hash(Path(model) / n) for n in ("model.onnx", "metadata.json")
                },
                baseline_sha256=baseline,
                source=source,
                profile=self.profile if source == "live" else storage.recording_metadata(recording),
                task_type=self.task.task_type,
                recording=str(recording) if source == "replay" else None,
            ),
        )

    def check_output(self, source, selected):
        if not selected:
            return
        if self.task in (ROBOT7, HAND5):
            raise ValueError("扩展任务本版只用于仿真。")
        if (
            source != "live"
            or not self.device_ready
            or self.profile["device"] not in ("Cometa", "Delsys")
        ):
            raise ValueError("真机输出需要真实肌电设备的实时信号。")
        output = self._hand if self.task == HAND else self._dds
        if not output or not output.connected:
            raise ValueError("请先连接输出设备。")

    def start_inference(self, model, source, recording=None, assessment=False, output=False):
        if self.training:
            raise ValueError("请先结束训练。")
        if source == "replay" and self.device_present:
            raise ValueError("回放前请断开采集设备。")
        self.check_output(source, output)
        self._pending = None
        self._session.start_inference(model, source, recording, assessment=assessment)
        self.inference_identity = uuid.uuid4().hex
        self._last_result = None
        if output:
            target = self._hand if self.task == HAND else self._dds
            try:
                target.enable(source, self.profile["device"])
                if self.task == ROBOT:
                    self._session.dds = target
            except Exception:
                self.stop_inference()
                raise

    def stop_inference(self):
        self._pending = None
        with self._session.lock:
            self._session.dds = None
        errors = []
        for action in (
            self._hand.disable if self._hand else None,
            self._dds.disable if self._dds else None,
            self._session.stop_inference,
        ):
            if action:
                try:
                    action()
                except Exception as error:
                    errors.append(str(error))
        if errors:
            raise RuntimeError("; ".join(errors))

    def create_hand_output(self, **kwargs):
        if self.task != HAND:
            raise ValueError("本版真机仅支持基础开合任务。")
        if self._hand is None:
            from .hand.output import HandOutput

            self._hand = HandOutput(**kwargs)
        return self._hand

    def connect_hand(self, **kwargs):
        output = self.create_hand_output(**kwargs)
        if not output.connected and output.controller is None:
            try:
                output.connect_hand()
            except Exception:
                self._hand = None
                output.close()
                raise
        return output

    def disconnect_hand(self):
        output, self._hand = self._hand, None
        if output:
            return output.close(notify=False)
        return ""

    def connect_dds(self, domain=0, interface=""):
        if self.task != ROBOT:
            raise ValueError("DDS 仅支持基础四类。")
        identity = (domain, interface)
        if self._dds_identity is not None and self._dds_identity != identity:
            raise ValueError("更改 DDS 参数后请重启应用。")
        if self._dds:
            return self._dds
        from .robot.dds import DdsBroadcast

        output = DdsBroadcast(domain, interface)
        try:
            output.connect()
        except Exception:
            output.close()
            raise
        self._dds, self._dds_identity = output, identity
        return output

    def disconnect_dds(self):
        with self._session.lock:
            self._session.dds = None
        output, self._dds = self._dds, None
        if output:
            output.close()

    def create_robot_worker(self, competition=None):
        from .robot.worker import SimulationWorker

        worker = SimulationWorker(competition)
        self._scene = worker
        self._scene_mode = "open"
        self._workers.append(worker)
        return worker

    def create_hand_scene(self, task):
        from .hand.preview import HandPreview

        if self._hand_scene:
            self._hand_scene.stop()
        self._hand_scene = HandPreview(task)
        return self._hand_scene

    def create_hand_worker(self):
        from .hand.render import HandRenderWorker

        worker = HandRenderWorker()
        self._workers.append(worker)
        return worker

    def stop_scene(self):
        scene, self._scene = self._scene, None
        if scene:
            scene.close()
        if self._hand_scene:
            self._hand_scene.stop()

    def poll(self):
        """Advance orchestration without Qt; useful to deterministic/headless clients."""
        self._tick()

    def _tick(self):
        if self._closed:
            return
        try:
            with self._pump_lock:
                snapshot = self._session.snapshot()
                capture = snapshot["capture"]
                if capture:
                    if self._scene and not capture.get("capture_only"):
                        self._scene.update_capture(capture, self._scene.settings)
                    if self._hand_scene and not capture.get("capture_only"):
                        self._hand_scene.sample(capture)
                    cue = capture.get("command", 0)
                    if cue != self._last_cue:
                        self.cue(cue)
                        self._last_cue = cue
                    if capture["done"]:
                        summary = self.stop_capture()
                        self.emit("capture_finished", summary=summary)
                        capture = None
                result = snapshot["result"]
                if snapshot["inferencing"] and result and result["sample_end"] != self._last_result:
                    if self._scene:
                        self._scene.update_command(result["filtered_class"], self._scene.settings)
                    if self._hand:
                        self._hand.update(result)
                    if self._hand_scene:
                        self._hand_scene.command(result["filtered_class"])
                    self._last_result = result["sample_end"]
                assessment = snapshot.get("assessment")
                if snapshot["inferencing"] and (
                    (assessment and assessment["done"])
                    or (snapshot["source"] == "replay" and snapshot["replay_done"])
                ):
                    reason = (
                        "assessment_finished"
                        if assessment and assessment["done"]
                        else "replay_finished"
                    )
                    identity = self.inference_identity
                    self.stop_inference()
                    self.emit(
                        "inference_finished", reason=reason, error=self.error, identity=identity
                    )
                    return
                if self._dds and self._dds.error:
                    self.emit("error", message=self._dds.error)
                    self.stop_inference()
                if (capture or snapshot["inferencing"]) and time.monotonic() - snapshot[
                    "last_frame"
                ] > 1:
                    self.stop_capture()
                    self.stop_inference()
                    self.emit("error", message="肌电信号已中断，实验已停止。")
        except Exception as error:
            errors = [str(error)]
            for action in (self.stop_capture, self.stop_inference):
                try:
                    action()
                except Exception as stop_error:
                    errors.append(str(stop_error))
            self.emit("error", message="; ".join(errors))

    def close(self):
        self._closed = True
        self._timer.stop()
        errors = []
        for action in (
            self.stop_training,
            self.disconnect_device,
            self.disconnect_hand,
            self.disconnect_dds,
            self.stop_scene,
            self._session.close,
        ):
            try:
                action()
            except Exception as error:
                errors.append(str(error))
        for worker in self._workers:
            if hasattr(worker, "stop_event"):
                worker.stop_event.set()
            if worker.ident is not None:
                worker.wait(5000)
        if errors:
            raise RuntimeError("; ".join(errors))
