"""InferencePage: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    CLASS_NAMES,
    ROOT,
    TASKS,
    HandView,
    QtCore,
    QtGui,
    W,
    button,
    card,
    details,
    field,
    fields,
    label,
    row,
    speed_summary,
    text_label,
)


class InferencePage:
    def make_inference_page(self):
        page_layout = self.page(
            "04  使用模型",
            "用肌电控制机器人",
            "选择模型和数据来源，再开始推理。当前配置始终保留在页面中。",
        )
        self.infer_setup, layout = card("模型与数据来源")
        layout.setSpacing(8)
        self.inference_task_choice = W.QComboBox()
        self.inference_task_choice.currentIndexChanged.connect(
            lambda: self.guard(lambda: self.choose_task(self.inference_task_choice))
        )
        layout.addLayout(fields(("任务方案", self.inference_task_choice)))
        self.infer_task_classes = text_label("")
        layout.addWidget(self.infer_task_classes)
        self.sync_capture_choices(self.task)
        page_layout.addWidget(self.infer_setup)
        self.infer_context = text_label("", "status")
        self.infer_context.hide()
        page_layout.addWidget(self.infer_context)
        self.models = W.QComboBox()
        self.models.setMinimumWidth(200)
        self.models.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.models.setMinimumContentsLength(16)
        self.models.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Fixed)
        self.models.currentIndexChanged.connect(self.model_details)
        self.manage_models = button("模型管理 / 导入导出…", lambda: self.open_library("model"))
        self.model_refresh = button("刷新", self.refresh_data)
        model_row = row(self.models, self.manage_models, self.model_refresh)
        layout.addLayout(model_row)
        self.model_summary = text_label("尚无模型，请先训练或导入。")
        layout.addWidget(self.model_summary)
        self.source = W.QComboBox()
        self.source.addItem("使用设备的实时信号", "live")
        self.source.addItem("回放已采集的数据", "replay")
        self.source.currentIndexChanged.connect(self.update_controls)
        self.replay_records = W.QComboBox()
        self.replay_records.setMinimumWidth(200)
        self.replay_records.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.replay_records.setMinimumContentsLength(16)
        self.replay_records.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Fixed)
        self.replay_field = field("回放数据", self.replay_records)
        source_fields = fields(("数据来源", self.source))
        source_fields.addWidget(self.replay_field, 1)
        layout.addLayout(source_fields)
        self.replay_manage = button(
            "选择回放数据 / 导入导出…", lambda: self.open_library("recording")
        )
        self.live_source_info = text_label("请先连接设备。")
        layout.addWidget(self.live_source_info)
        self.source_explanation = text_label("")
        layout.addWidget(self.source_explanation)
        self.practice_mode = W.QComboBox()
        self.practice_mode.addItem("自由练习", "free")
        self.practice_mode.addItem("基础评估 · 实时提示 / 回放标签对照", "assessment")
        self.practice_mode.addItem("金币任务 · 练习 / 正式比赛", "coins")
        self.practice_mode.currentIndexChanged.connect(self.update_controls)
        layout.addLayout(fields(("练习方式", self.practice_mode)))
        self.practice_hint = text_label(
            "自由练习：前进 → 停止 → 左转 → 前进 → 停止，观察转向后前进方向。"
        )
        layout.addWidget(self.practice_hint)
        self.competition_panel, race_body = card("金币任务")
        self.race_group = W.QLineEdit("G01")
        self.race_group.setMaxLength(40)
        self.race_seed = W.QSpinBox()
        self.race_seed.setRange(0, 2147483647)
        self.race_seed.setValue(20261025)
        self.race_count = W.QSpinBox()
        self.race_count.setRange(1, 20)
        self.race_count.setValue(6)
        self.race_seconds = W.QSpinBox()
        self.race_seconds.setRange(20, 600)
        self.race_seconds.setValue(120)
        self.race_seconds.setSuffix(" 秒")
        race_body.addLayout(fields(("参赛组别", self.race_group), ("随机种子", self.race_seed)))
        race_body.addLayout(fields(("金币数", self.race_count), ("整局限时", self.race_seconds)))
        self.race_official = W.QCheckBox("正式比赛：真实肌电、教师规定种子、程序校验")
        self.race_official.toggled.connect(lambda: self.guard(self.configure_competition))
        race_body.addWidget(self.race_official)
        self.race_rules_hint = text_label(
            "固定分类："
            + speed_summary()
            + "。所有模型统一榜单；连续/混合控制通过教师验收后可使用更高速度档，计时规则相同。"
        )
        race_body.addWidget(self.race_rules_hint)
        self.race_result = text_label(
            "每局自动保存成绩、路线、模型校验值与逐步控制记录；提前退出也留档。"
        )
        race_body.addWidget(self.race_result)
        self.race_report = button("打开最近一局报告", self.open_competition_report)
        self.race_report.setEnabled(False)
        race_body.addLayout(
            row(
                self.race_report,
                button(
                    "比赛规则与教师操作",
                    lambda: QtGui.QDesktopServices.openUrl(
                        QtCore.QUrl.fromLocalFile(str(ROOT / "docs/机器人金币任务说明.html"))
                    ),
                ),
                1,
            )
        )
        page_layout.addWidget(self.competition_panel)
        self.replay_actions = W.QWidget()
        self.replay_actions.setLayout(row(self.replay_manage, 1))
        self.replay_actions.layout().setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.replay_actions)
        self.infer_scene = W.QCheckBox("显示机器人练习场")
        self.infer_scene.setChecked(True)
        self.infer_scene.toggled.connect(self.update_hand_views)
        self.model_info = label("尚无模型，请先完成训练。")
        model_section, model_body = details("模型信息与评估详情")
        model_body.addWidget(self.model_info)
        layout.addLayout(row(self.infer_scene, 1, model_section.toggle))
        layout.addWidget(model_section)
        model_section.hide()
        model_section.toggle.toggled.connect(model_section.setVisible)
        panel, body = card("实时识别")
        self.prediction = label("选择模型后，点击“开始推理”")
        self.prediction.setObjectName("prediction")
        self.prediction.setAlignment(QtCore.Qt.AlignCenter)
        self.prediction.setMinimumHeight(60)
        feedback_row = W.QHBoxLayout()
        result_panel = W.QWidget()
        result_layout = W.QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(10)
        result_layout.addWidget(self.prediction)
        feedback_row.addWidget(result_panel, 1)
        self.probabilities = []
        probability_grid = self.probability_grid = W.QGridLayout()
        probability_grid.setSpacing(10)
        for i in range(max(len(task.classes) for task in TASKS.values())):
            name = self.task.names[i] if i < len(self.task.names) else ""
            bar = W.QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat(name + "  %p%")
            bar.setVisible(i < 4)
            probability_grid.addWidget(bar, i // 2, i % 2)
            self.probabilities.append(bar)
        result_layout.addLayout(probability_grid)
        self.infer_hand_view = HandView()
        self.infer_hand_view.setMinimumWidth(280)
        self.infer_hand_view.hide()
        feedback_row.addWidget(self.infer_hand_view, 1)
        body.addLayout(feedback_row)
        self.infer_hand_feedback = text_label("")
        self.infer_hand_feedback.hide()
        body.addWidget(self.infer_hand_feedback)
        page_layout.addWidget(panel)
        self.assessment_panel, assessment_body = card("基础评估")
        self.assessment_cue = text_label(
            "实时：按随机提示做动作；回放：与原始标签对照。", "cueBanner"
        )
        self.assessment_stats = text_label("仅评估模型预测，提示不会直接控制场景。")
        self.assessment_report = button("打开完整评估报告", self.open_assessment_report)
        self.assessment_report.setEnabled(False)
        assessment_body.addWidget(self.assessment_cue)
        assessment_body.addWidget(self.assessment_stats)
        assessment_body.addWidget(self.assessment_report, 0, QtCore.Qt.AlignLeft)
        page_layout.insertWidget(page_layout.indexOf(panel), self.assessment_panel)
        self.mock_panel = W.QGroupBox("模拟设备体验")
        body = W.QVBoxLayout(self.mock_panel)
        body.addLayout(row("模拟输入的动作", self.mock_action_combo(), 1))
        body.addWidget(text_label("推理开始后，切换动作来生成模拟信号，观察上方的识别结果。"))
        page_layout.addWidget(self.mock_panel)
        panel, body = card("真实设备输出")
        self.hardware_output_panel = panel
        body.addWidget(text_label("使用硬件实验时开启，由助教确认设备已就绪。"))
        self.hand_check = W.QCheckBox("使用真实灵巧手（达妙 USB）")
        self.hand_check.toggled.connect(self.update_controls)
        self.hand_connect = button("连接灵巧手", lambda: self.guard(self.connect_hand))
        self.hand_disconnect = button("断开", self.disconnect_hand)
        self.hand_panel = W.QWidget()
        self.hand_panel.setLayout(row(self.hand_check, 1, self.hand_connect, self.hand_disconnect))
        self.hand_panel.layout().setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.hand_panel)
        self.hand_status = text_label("灵巧手未连接。连接后待机，开始推理才启用动作输出。")
        body.addWidget(self.hand_status)
        self.hand_feedback = label("连接后显示四指位置回读。")
        self.hand_details, hand_body = details("灵巧手状态详情")
        hand_body.addWidget(self.hand_feedback)
        body.addWidget(self.hand_details)
        self.dds_check = W.QCheckBox("使用真实机器人（DDS）")
        self.dds_check.toggled.connect(self.update_controls)
        self.domain = W.QSpinBox()
        self.domain.setRange(0, 232)
        self.interface = W.QLineEdit()
        self.interface.setPlaceholderText("留空自动选择")
        self.dds_connect = button("连接机器人", lambda: self.guard(self.connect_dds))
        self.dds_disconnect = button("断开", self.disconnect_dds)
        self.dds_panel = W.QWidget()
        self.dds_panel.setLayout(row(self.dds_check, 1, self.dds_connect, self.dds_disconnect))
        self.dds_panel.layout().setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.dds_panel)
        self.dds_status = text_label("机器人未连接。可在推理前连接，开始推理才发送指令。")
        body.addWidget(self.dds_status)
        self.dds_settings, extra = details("机器人连接设置（由助教设置）")
        extra.addLayout(fields(("DDS Domain", self.domain), ("网卡名称", self.interface)))
        body.addWidget(self.dds_settings)
        page_layout.addWidget(panel)
        self.infer_start = button("开始推理", lambda: self.guard(self.start_inference), True)
        self.infer_stop = button("停止推理", self.stop_inference)
        self.infer_run_status = text_label("等待开始", "status")
        self.page_actions["04  使用模型"].addLayout(
            row(self.infer_start, self.infer_stop, 1, self.infer_run_status)
        )
        page_layout.addStretch()

    def mock_action_combo(self):
        self.mock_action = W.QComboBox()
        self.mock_action.addItems(CLASS_NAMES)
        self.mock_action.currentIndexChanged.connect(
            lambda cue: (
                self.guard(lambda: self.backend.cue(cue))
                if self.backend.device_present and not self.backend.capture
                else None
            )
        )
        return self.mock_action
