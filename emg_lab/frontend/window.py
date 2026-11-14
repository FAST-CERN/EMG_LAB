"""Desktop composition: window shell, pages and presenters."""

from __future__ import annotations

from emg_lab.frontend.components import (
    DATA_ROOT,
    ROBOT,
    TASKS,
    VERSION,
    Bridge,
    HandScene,
    Path,
    QtCore,
    QtGui,
    RobotScene,
    W,
    apply_theme,
    label,
    sys,
    text_label,
)
from emg_lab.frontend.components import available_devices as available_devices
from emg_lab.frontend.pages.capture import CapturePage
from emg_lab.frontend.pages.device import DevicePage
from emg_lab.frontend.pages.inference import InferencePage
from emg_lab.frontend.pages.training import TrainingPage
from emg_lab.frontend.pages.workspace import WorkspacePages
from emg_lab.frontend.presenters.artifacts import ArtifactPresenter
from emg_lab.frontend.presenters.capture import CapturePresenter
from emg_lab.frontend.presenters.device import DevicePresenter
from emg_lab.frontend.presenters.inference import InferencePresenter
from emg_lab.frontend.presenters.status import StatusPresenter
from emg_lab.frontend.presenters.training import TrainingPresenter


class MainWindow(
    W.QMainWindow,
    WorkspacePages,
    DevicePage,
    CapturePage,
    TrainingPage,
    InferencePage,
    DevicePresenter,
    CapturePresenter,
    TrainingPresenter,
    ArtifactPresenter,
    InferencePresenter,
    StatusPresenter,
):
    def __init__(self, data_root=DATA_ROOT, backend=None):
        super().__init__()
        self.setWindowTitle("EMG Lab · 课堂实验 · " + VERSION)
        self.resize(1160, 820)
        self.setMinimumSize(900, 600)
        from emg_lab.bootstrap import build_service

        self.backend = backend if backend is not None else build_service(data_root)
        self.task = ROBOT
        self.hand_output = None
        self.dds_output = None
        self.page_actions, self.page_scrolls = {}, {}
        self.page_titles, self.page_hints = {}, {}
        self.scene_pending = None
        self.scene = RobotScene(self)
        self.scene.ready.connect(self.finish_scene_start)
        self.scene.failed.connect(self.on_scene_error)
        self.scene.closed.connect(self.on_scene_closed)
        self.scene.competition_finished.connect(self.on_competition_finished)
        self.last_competition_path = None
        self.competition_token = None
        self._last_result_end = None
        self._capture_identity = self._inference_identity = None
        self._last_cue = None
        self._dds_interface = None
        self.imported_records = {}
        self.imported_models = {}
        self.help_dialog = None
        self.last_transfer_folder = str(self.backend.root)
        self._health_checked = 0.0
        self.bridge = Bridge()
        self.bridge.application_event.connect(self.on_application_event)
        self.backend.events.connect(self.bridge.application_event.emit)
        self.bridge.device_event.connect(self.on_device)
        self.bridge.train_event.connect(self.on_train)
        self.stack = W.QStackedWidget()
        self.setCentralWidget(self.stack)
        self.make_choice()
        self.make_workspace()
        self.help_action = QtGui.QAction("帮助 / 操作教程", self)
        self.help_action.setShortcut(QtGui.QKeySequence("F1"))
        self.help_action.triggered.connect(lambda: self.guard(self.open_help))
        self.addAction(self.help_action)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.refresh_data()
        self.update_controls()

    @property
    def session(self):
        return self.backend

    def on_application_event(self, event):
        if event.kind == "device":
            self.on_device(event.payload)
        elif event.kind == "training":
            self.on_train(event.payload)
        elif event.kind == "capture_finished":
            summary = event.payload["summary"]
            if summary and summary.identity == self._capture_identity:
                self.show_capture_finished(summary)
        elif event.kind == "inference_finished":
            if event.payload["identity"] != self._inference_identity:
                return
            self.stop_inference(event.payload["reason"])
            self.scene.stop()
            self.prediction.setText("推理已停止")
            error = event.payload["error"]
            self.message(error or "推理已完成，预测结果与评估报告已保存。", bool(error))
        elif event.kind == "error":
            self.stop_capture()
            self.stop_inference()
            self.message(event.payload["message"], True)

    def guard(self, action):
        try:
            return action()
        except Exception as exc:
            self.message(str(exc), error=True)
            return None

    def message(self, text, error=False):
        self.notice.setText(("提示：" if error else "") + str(text))
        self.notice.setProperty("tone", "error" if error else "info")
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)

    def page(self, name, title, hint):
        widget = W.QWidget()
        widget.setObjectName("pageContent")
        layout = W.QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        self.page_titles[name] = label(title, True)
        self.page_hints[name] = text_label(hint)
        layout.addWidget(self.page_titles[name])
        layout.addWidget(self.page_hints[name])
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.NoFrame)
        scroll.setWidget(widget)
        page = W.QWidget()
        outer = W.QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        actions = W.QFrame()
        actions.setObjectName("actionBar")
        footer = W.QHBoxLayout(actions)
        footer.setContentsMargins(24, 12, 24, 12)
        outer.addWidget(actions)
        self.page_actions[name] = footer
        self.page_scrolls[name] = scroll
        self.tabs.addTab(page, name)
        return layout

    def reveal_activity(self, name, widget):
        """Focus the live feedback without collapsing or discarding its setup."""
        scroll = self.page_scrolls[name]

        def reveal():
            position = widget.mapTo(scroll.widget(), QtCore.QPoint(0, 0)).y()
            scroll.verticalScrollBar().setValue(max(0, position - 18))

        QtCore.QTimer.singleShot(0, reveal)

    def update_workspace_heading(self):
        self.workspace_header.setText(
            "EMG Lab  /  " + ("数据与模型" if self.tabs.currentIndex() == 4 else self.task.title)
        )

    def choose_task(self, choice):
        key = choice.currentData()
        if key is None:
            return
        try:
            self.select_task(key)
        finally:
            # If switching is refused during a run, the visible choices stay truthful.
            self.sync_capture_choices(self.task)

    def sync_capture_choices(self, task):
        captions = {
            "robot": "基础四类",
            "robot7": "扩展七类",
            "hand": "基础开合三类",
            "hand5": "预设姿态五类",
        }
        for attr in ("task_choice", "training_task_choice", "inference_task_choice"):
            choice = getattr(self, attr, None)
            if choice is None:
                continue
            choice.blockSignals(True)
            choice.clear()
            for key, candidate in TASKS.items():
                if candidate.key == task.key:
                    choice.addItem(
                        captions.get(key, f"{candidate.title}（{len(candidate.classes)} 类）"), key
                    )
            choice.setCurrentIndex(choice.findData(task.selector))
            choice.blockSignals(False)
        for attr in ("train_task_classes", "infer_task_classes"):
            if hasattr(self, attr):
                getattr(self, attr).setText(
                    "类别："
                    + "、".join(task.names)
                    + "。三页方案同步，列表只显示匹配的数据与模型。"
                )

    def select_task(self, key):
        if (
            self.backend.capture
            or self.backend.inference
            or self.backend.training
            or self.scene_pending
        ):
            raise ValueError("请先结束当前实验，再切换目标。")
        task = TASKS[key]
        self.sync_capture_choices(task)
        if task != self.task:
            self.disconnect_hand()
            self.disconnect_dds()
            self.hand_check.setChecked(False)
            self.dds_check.setChecked(False)
            self.scene.stop()
            self.scene.deleteLater()
            self.backend.select_task(key)
            self.task = task
            self.scene = (
                HandScene(self, (self.infer_hand_view,), task=task)
                if task.key == "hand"
                else RobotScene(self)
            )
            self.scene.ready.connect(self.finish_scene_start)
            self.scene.failed.connect(self.on_scene_error)
            self.scene.closed.connect(self.on_scene_closed)
            if task.key == "robot":
                self.scene.competition_finished.connect(self.on_competition_finished)
            if task.key == "hand":
                self.scene.changed.connect(self.hand_scene_status)
            self._last_result_end = None
            self.assessment_report.setEnabled(False)
            self.assessment_cue.setText("实时：按随机提示做动作；回放：与原始标签对照。")
            self.assessment_stats.setText("仅评估模型预测，提示不会直接控制场景。")
            self.update_workspace_heading()
            self.page_hints["02  采集数据"].setText(
                "每次采集保存为一个数据文件。每组依次完成："
                + " → ".join(task.names[i] for i in task.order)
                + "。停止用放松／静息打标。"
            )
            self.page_titles["04  使用模型"].setText(
                "用肌电控制" + ("灵巧手" if task.key == "hand" else "机器人")
            )
            self.page_hints["04  使用模型"].setText(
                "选择模型和数据来源，再开始推理。使用采集时相同的肌肉动作，观察模型输出与动作反馈。"
            )
            self.experiment.setText("灵巧手控制练习" if task.key == "hand" else "方向控制练习")
            self.model_name.setText(task.title + "模型")
            self.scene_check.setText(
                "独立窗口显示灵巧手示范" if task.key == "hand" else "独立窗口显示机器人示范"
            )
            self.infer_scene.setText(
                "显示灵巧手 3D 模拟" if task.key == "hand" else "显示机器人练习场"
            )
            self.cue.setText("准备就绪后，开始采集")
            self.cue.setMinimumHeight(44)
            self.capture_status.setText(
                "准备时放松；动作阶段按当前姿态提示完成约定的肌肉动作。3D 手为标签示范，不控制真机。"
                if task.key == "hand"
                else "准备时放松；动作提示出现后，完成助教约定的肌肉动作。"
            )
            self.prediction.setText("选择模型后，点击“开始推理”")
            while len(self.probabilities) < len(task.classes):
                i = len(self.probabilities)
                bar = W.QProgressBar()
                bar.setRange(0, 100)
                self.probability_grid.addWidget(bar, i // 2, i % 2)
                self.probabilities.append(bar)
            for i, bar in enumerate(self.probabilities):
                bar.setVisible(i < len(task.classes))
                bar.setValue(0)
                if i < len(task.classes):
                    bar.setFormat(task.names[i] + "  %p%")
            self.mock_action.blockSignals(True)
            self.mock_action.clear()
            self.mock_action.addItems(task.names)
            self.mock_action.blockSignals(False)
            if self.backend.device_present:
                self.guard(lambda: self.backend.cue(0))
            self.training_result.clear()
            self.train_status.setText("请选择当前实验目标的数据进行训练。")
            self.refresh_data()
        self.update_capture_mode()
        self.update_capture_plan()
        self.update_hand_views()
        self.update_controls()
        self.stack.setCurrentIndex(1)

    def back_home(self):
        if (
            self.backend.capture
            or self.backend.inference
            or self.backend.training
            or self.scene_pending
        ):
            raise ValueError("请先结束当前实验，再切换目标。")
        self.stack.setCurrentIndex(0)

    def open_help(self, tab=0):
        if self.help_dialog is None:
            from emg_lab.frontend.help import HelpDialog

            self.help_dialog = HelpDialog(self)
        self.help_dialog.tabs.setCurrentIndex(tab)
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def open_folder(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event):
        self.timer.stop()
        self.scene_pending = None
        try:
            self.scene.stop()
            self.backend.close()
        except Exception as error:
            self.message(str(error), True)
        event.accept()


def configure_app(app):
    apply_theme(app)


def main():
    app = W.QApplication(sys.argv)
    configure_app(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
