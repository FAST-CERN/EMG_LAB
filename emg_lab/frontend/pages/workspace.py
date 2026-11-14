"""WorkspacePages: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import LibraryWidget, W, button, card, label, row, text_label


class WorkspacePages:
    def make_choice(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(64, 40, 64, 40)
        layout.setSpacing(16)
        layout.addLayout(
            row(text_label("EMG LAB", "brand"), 1, text_label("肌电 · 课堂实验", "muted"))
        )
        layout.addStretch(1)
        layout.addWidget(text_label("从肌肉信号，到动作控制", "hero"))
        layout.addWidget(text_label("选择实验目标，按四个步骤完成采集、训练与实时控制。"))
        layout.addSpacing(12)
        choices = W.QHBoxLayout()
        choices.setSpacing(20)
        for key, number, title, description, tags in (
            (
                "robot",
                "EXPERIMENT 01",
                "机器人控制",
                "学习用肌电信号控制机器人方向，观察动作识别与运动反馈。",
                "前进 / 停止 / 左转 / 右转",
            ),
            (
                "hand",
                "EXPERIMENT 02",
                "灵巧手控制",
                "学习手部动作分类，在 3D 模拟中观察灵巧手的开合与停止。",
                "张开 / 握合 / 停止",
            ),
        ):
            panel, body = card()
            body.setContentsMargins(24, 24, 24, 24)
            body.setSpacing(18)
            body.addWidget(text_label(number, "eyebrow"))
            body.addWidget(label(title, True))
            body.addWidget(text_label(description))
            body.addSpacing(6)
            body.addWidget(text_label(tags, "fieldLabel"))
            body.addStretch()
            body.addWidget(
                button(
                    "进入" + title + "  →",
                    lambda checked=False, k=key: self.guard(lambda: self.select_task(k)),
                    True,
                )
            )
            choices.addWidget(panel, 1)
        layout.addLayout(choices)
        layout.addWidget(
            text_label("没有硬件也能开始：进入实验后选择“模拟设备”，即可体验完整流程。")
        )
        layout.addStretch(1)
        workflow = text_label("01 连接  →  02 采集  →  03 训练  →  04 使用")
        workflow.setWordWrap(False)
        layout.addLayout(
            row(
                button("操作教程  ·  F1", lambda: self.guard(self.open_help)),
                button("开发技术文档", lambda: self.guard(lambda: self.open_help(1))),
                button("数据与模型", lambda: self.guard(self.open_library)),
                1,
                workflow,
            )
        )
        self.stack.addWidget(page)

    def make_workspace(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header_panel = W.QFrame()
        header_panel.setObjectName("header")
        header_layout = W.QHBoxLayout(header_panel)
        header_layout.setContentsMargins(24, 14, 24, 14)
        self.workspace_header = text_label("EMG Lab  /  机器人控制", "brand")
        self.workspace_header.setWordWrap(False)
        header_layout.addLayout(
            row(
                self.workspace_header,
                1,
                button("帮助  ·  F1", lambda: self.guard(self.open_help)),
                button("切换实验", lambda: self.guard(self.back_home)),
            )
        )
        layout.addWidget(header_panel)
        self.tabs = W.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.setUsesScrollButtons(False)
        layout.addWidget(self.tabs, 1)
        self.notice = label("从“设备连接”开始，按页面顺序完成实验。")
        self.notice.setObjectName("notice")
        self.notice.setMinimumHeight(18)
        notice_layout = W.QVBoxLayout()
        notice_layout.setContentsMargins(16, 8, 16, 8)
        notice_layout.addWidget(self.notice)
        layout.addLayout(notice_layout)
        self.make_device_page()
        self.make_capture_page()
        self.make_training_page()
        self.make_inference_page()
        self.make_library_page()
        self.tabs.currentChanged.connect(self.update_workspace_heading)
        for name in ("time_window", "display", "scale"):
            first, second = getattr(self.waveform, name), getattr(self.capture_waveform, name)
            first.currentIndexChanged.connect(second.setCurrentIndex)
            second.currentIndexChanged.connect(first.setCurrentIndex)
        self.waveform.fixed_limit.valueChanged.connect(self.capture_waveform.fixed_limit.setValue)
        self.capture_waveform.fixed_limit.valueChanged.connect(self.waveform.fixed_limit.setValue)
        self.stack.addWidget(page)

    def make_library_page(self):
        layout = self.page(
            "数据与模型",
            "管理课堂数据与模型",
            "按组别、日期和实验目标查找文件，统一导入导出，再选择用于训练或离线回放。",
        )
        self.library = LibraryWidget(self, self.page_actions["数据与模型"])
        layout.addWidget(self.library, 1)
