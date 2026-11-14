"""CapturePage: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    ACTION_SECONDS,
    PREPARE_SECONDS,
    REST_SECONDS,
    QtCore,
    W,
    WaveformPreview,
    button,
    card,
    details,
    fields,
    label,
    row,
    safe_name,
    text_label,
)


class CapturePage:
    def make_capture_page(self):
        layout = self.page(
            "02  采集数据",
            "跟随提示，采集动作数据",
            "填写本次数据的名称与组别，再按屏幕提示完成动作。结束后自动保存。",
        )
        self.capture_settings, settings = card("采集设置")
        layout.addWidget(self.capture_settings)
        self.task_choice = W.QComboBox()
        self.sync_capture_choices(self.task)
        self.task_choice.currentIndexChanged.connect(
            lambda: self.guard(lambda: self.choose_task(self.task_choice))
        )
        self.capture_mode = W.QComboBox()
        self.capture_mode.addItem("课程预设采集（四类 / 七类）", "standard")
        self.capture_mode.addItem("自定义动作采集（不关联机器人）", "custom")
        self.capture_mode.currentIndexChanged.connect(self.update_capture_mode)
        settings.addLayout(fields(("采集方式", self.capture_mode)))
        self.preset_task_field = fields(("任务方案", self.task_choice))
        settings.addLayout(self.preset_task_field)
        self.preset_hint = text_label(
            "课程预设保留原有训练与控制流程；自定义采集可自由添加动作、力道与备注，稍后再研究映射。"
        )
        settings.addWidget(self.preset_hint)
        self.group = W.QLineEdit("G01")
        self.group.setMaxLength(40)
        self.experiment = W.QLineEdit("方向控制练习")
        self.experiment.setMaxLength(60)
        settings.addLayout(fields(("组别 / 学号", self.group), ("数据名称", self.experiment)))
        self.group.textChanged.connect(self.name_preview)
        self.experiment.textChanged.connect(self.name_preview)
        self.trial_count = W.QSpinBox()
        self.trial_count.setRange(1, 9999)
        self.trial_count.setValue(5)
        self.trial_count.setSuffix(" 组")
        self.action_seconds = W.QDoubleSpinBox()
        self.action_seconds.setRange(1, 10)
        self.action_seconds.setValue(ACTION_SECONDS)
        self.action_seconds.setSuffix(" 秒")
        self.scene_check = W.QCheckBox("独立窗口显示机器人示范")
        self.scene_check.setChecked(True)
        self.scene_check.toggled.connect(self.update_hand_views)
        controls = fields(("动作组数", self.trial_count), ("每个动作持续", self.action_seconds))
        controls.addWidget(self.scene_check, 1, QtCore.Qt.AlignBottom)
        settings.addLayout(controls)
        self.random_order = W.QCheckBox("随机动作顺序")
        self.random_order.setToolTip("每组仍包含全部类别。先按固定顺序熟悉动作，再勾选随机采集。")
        settings.addWidget(self.random_order)
        self.collection_notes_button = button(
            "采集记录…", lambda: self.guard(self.edit_collection_notes)
        )
        self.legacy_notes_panel = W.QWidget()
        legacy_notes_layout = row(
            self.collection_notes_button,
            text_label("选填操作者、通道位置与动作约定；同一佩戴可沿用，随数据一起带走。"),
            1,
        )
        self.legacy_notes_panel.setLayout(legacy_notes_layout)
        settings.addWidget(self.legacy_notes_panel)
        from emg_lab.frontend.custom_capture import CustomCaptureEditor

        self.custom_capture = CustomCaptureEditor(self)
        self.custom_capture.changed.connect(self.update_capture_plan)
        settings.addWidget(self.custom_capture)
        self.custom_capture.setVisible(False)
        self.capture_plan = text_label("")
        settings.addWidget(self.capture_plan)
        self.trial_count.valueChanged.connect(self.update_capture_plan)
        self.action_seconds.valueChanged.connect(self.update_capture_plan)
        self.group.textChanged.connect(self.update_capture_plan)
        self.path_preview = text_label("")
        self.path_preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        storage_info, storage_body = details("保存位置与命名规则")
        storage_body.addWidget(self.path_preview)
        storage_body.addWidget(
            button("打开数据目录", lambda: self.open_folder(self.backend.root)),
            0,
            QtCore.Qt.AlignLeft,
        )
        settings.addWidget(storage_info)
        self.cue = label("准备就绪后，开始采集")
        self.cue.setObjectName("cueBanner")
        self.cue.setAlignment(QtCore.Qt.AlignCenter)
        self.cue.setMinimumHeight(44)
        layout.addWidget(self.cue)
        self.capture_progress = W.QProgressBar()
        self.capture_progress.setRange(0, 1000)
        self.capture_progress.setValue(0)
        self.capture_progress.setFixedWidth(170)
        self.capture_status = text_label("准备时放松；动作提示出现后，完成助教约定的肌肉动作。")
        self.reject_trial_button = button(
            "标记本组无效", lambda: self.guard(self.reject_current_trial)
        )
        self.reject_trial_button.setToolTip(
            "保留原始信号；训练和基础评估跳过这一组。结束后另采一组补足。"
        )
        layout.addLayout(row(self.capture_status, self.capture_progress, self.reject_trial_button))
        panel, body = card("采集波形")
        self.capture_waveform = WaveformPreview(compact=True)
        body.addWidget(self.capture_waveform)
        self.capture_health = text_label("连接后先观察波形，再开始采集。")
        body.addWidget(self.capture_health)
        layout.addWidget(panel, 1)
        self.capture_start = button("开始采集并保存", lambda: self.guard(self.start_capture), True)
        self.capture_stop = button("提前结束并保存", self.stop_capture)
        self.capture_next = button("下一步：训练模型 →", self.capture_next_step)
        self.page_actions["02  采集数据"].addLayout(
            row(
                self.capture_start,
                self.capture_stop,
                1,
                self.capture_next,
            )
        )
        self.name_preview()
        self.update_capture_plan()

    def capture_next_step(self):
        if self.custom_capture_active():
            self.open_library("recording")
        else:
            self.refresh_data()
            self.tabs.setCurrentIndex(2)

    def custom_capture_active(self):
        return self.task.key == "robot" and self.capture_mode.currentData() == "custom"

    def update_capture_mode(self):
        if not hasattr(self, "custom_capture"):
            return
        custom = self.custom_capture_active()
        self.capture_mode.setVisible(self.task.key == "robot")
        self.custom_capture.setVisible(custom)
        self.page_titles["02  采集数据"].setText("自定义动作采集" if custom else "跟随提示，采集动作数据")
        self.capture_next.setText("查看采集数据 →" if custom else "下一步：训练模型 →")
        self.scene_check.setVisible(not custom)
        self.legacy_notes_panel.setVisible(not custom)
        self.task_choice.setEnabled(not custom)
        self.task_choice.setVisible(not custom)
        for index in range(self.preset_task_field.count()):
            widget = self.preset_task_field.itemAt(index).widget()
            if widget:
                widget.setVisible(not custom)
        if custom and self.backend.profile:
            self.custom_capture.sync_channels()
        self.name_preview()
        self.update_capture_plan()
        self.update_controls()

    def update_capture_plan(self):
        count = self.trial_count.value()
        if not hasattr(self, "capture_plan"):
            return
        actions = (
            len(self.custom_capture.selected_ids())
            if self.custom_capture_active()
            else len(self.task.classes)
        )
        seconds = round(
            count * actions * (self.action_seconds.value() + PREPARE_SECONDS + REST_SECONDS)
        )
        duration = f"{seconds // 60} 分 {seconds % 60} 秒" if seconds >= 60 else f"{seconds} 秒"
        self.capture_plan.setText(
            f"本次共 {count} 组、{count * actions} 个动作，预计 {duration}。每个动作前准备 {PREPARE_SECONDS:g} 秒，完成后直接进入下一个动作的准备。"
        )

    def name_preview(self):
        try:
            group, title = safe_name(self.group.text()), safe_name(self.experiment.text())
            self.path_preview.setText(
                f"将保存为一份“{title}”数据，归入 {group}。时间和文件编号自动添加。"
                + (
                    " 自定义采集同时生成同名 .index.csv；动作名称与备注保存在原始文件内。"
                    if self.custom_capture_active()
                    else ""
                )
            )
        except ValueError as exc:
            self.path_preview.setText(str(exc))
