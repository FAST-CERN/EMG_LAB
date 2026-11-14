"""TrainingPage: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    QtCore,
    W,
    button,
    card,
    details,
    field,
    fields,
    row,
    text_label,
)


class TrainingPage:
    def make_training_page(self):
        layout = self.page(
            "03  训练模型",
            "让模型学习你的动作",
            "勾选训练数据并填写模型名称。一份数据、一个完整动作组也能训练。",
        )
        self.training_task_choice = W.QComboBox()
        self.training_task_choice.currentIndexChanged.connect(
            lambda: self.guard(lambda: self.choose_task(self.training_task_choice))
        )
        layout.addLayout(fields(("任务方案", self.training_task_choice)))
        self.train_task_classes = text_label("")
        layout.addWidget(self.train_task_classes)
        self.sync_capture_choices(self.task)
        setup = W.QHBoxLayout()
        setup.setSpacing(16)
        panel, body = card("训练数据")
        self.records = W.QListWidget()
        self.records.setMinimumHeight(130)
        self.records.setMaximumHeight(165)
        self.records.setWordWrap(True)
        self.records.setSpacing(2)
        body.addWidget(self.records, 1)
        self.manage_data = button("数据管理 / 导入导出…", lambda: self.open_library("recording"))
        self.record_refresh = button("刷新列表", self.refresh_data)
        self.record_latest = button("选择最近一次采集", self.select_latest)
        body.addLayout(row(self.manage_data, 1))
        body.addLayout(row(self.record_refresh, self.record_latest, 1))
        self.record_summary = text_label("")
        body.addWidget(self.record_summary)
        self.records.itemChanged.connect(self.update_record_summary)
        setup.addWidget(panel, 3)
        panel, body = card("模型设置")
        self.model_name = W.QLineEdit("方向分类模型")
        self.epochs = W.QSpinBox()
        self.epochs.setRange(1, 200)
        self.epochs.setValue(30)
        self.epochs.setSuffix(" 遍")
        body.addWidget(field("模型名称", self.model_name))
        body.addWidget(field("学习遍数（Epochs）", self.epochs))
        body.addWidget(
            text_label("建议先使用默认 30 遍。训练结束后，模型会自动保存并出现在“使用模型”页。")
        )
        body.addStretch()
        setup.addWidget(panel, 2)
        layout.addLayout(setup)
        panel, body = card("训练进度与结果")
        self.train_progress = W.QProgressBar()
        self.train_progress.setRange(0, 1000)
        self.train_progress.setValue(0)
        body.addWidget(self.train_progress)
        self.train_status = text_label("等待开始。软件会自动安排训练和效果评估。")
        body.addWidget(self.train_status)
        self.training_result = W.QPlainTextEdit()
        self.training_result.setReadOnly(True)
        self.training_result.setMinimumHeight(150)
        self.training_result.setMaximumHeight(220)
        self.training_result.setPlaceholderText(
            "训练完成后，查看模型保存位置、评估结果与下一步操作。"
        )
        body.addWidget(self.training_result)
        explanation, extra = details("这些分数怎么计算？")
        extra.addWidget(
            text_label(
                "窗口分类：取每个信号窗口中概率最大的类别，与动作标签比较。最终指令：连续回放数据，经过与实时推理相同的置信度和连续判定，再与标签比较。"
            )
        )
        extra.addWidget(
            text_label(
                "默认使用 0.5 秒窗口，每 0.1 秒推理一次；运动指令要求概率至少 65%，连续 3 次一致。只统计留出动作段内的完整窗口，并跳过每段开头 0.2 秒。窗口互相重叠，不是独立动作次数。"
            )
        )
        body.addWidget(explanation)
        layout.addWidget(panel)
        self.train_start = button("开始训练", lambda: self.guard(self.start_training), True)
        self.train_stop = button("停止训练", self.stop_training)
        self.page_actions["03  训练模型"].addLayout(
            row(
                self.train_start,
                self.train_stop,
                1,
                button(
                    "下一步：使用模型 →",
                    lambda: (self.refresh_data(), self.tabs.setCurrentIndex(3)),
                ),
            )
        )

    def update_record_summary(self):
        total = self.records.count()
        checked = sum(self.records.item(i).checkState() == QtCore.Qt.Checked for i in range(total))
        self.record_summary.setText(
            f"共 {total} 份数据 · 已勾选 {checked} 份。导入导出统一在“数据与模型”页管理。"
            if total
            else "还没有数据。请先采集，或进入“数据与模型”导入已有文件。"
        )
