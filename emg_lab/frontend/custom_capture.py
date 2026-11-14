"""Editable capture conditions; device channels remain owned by device configuration."""

import uuid

from PySide6 import QtCore as C
from PySide6 import QtWidgets as W

from emg_lab.contracts.acquisition import CONDITION_FIELDS, MAX_CONDITIONS, validate_plan


class CustomCaptureEditor(W.QWidget):
    changed = C.Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = W.QLabel("自定义动作与采集条件")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        tip = W.QLabel(
            "每行是一个动作与力道条件，最多 64 行。只保存肌电和标签，不驱动机器人，也不启动 3D。力道是实验提示，并非实测力值。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.tabs = W.QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { padding:7px 14px; }")
        action_page, metadata_page = W.QWidget(), W.QWidget()
        action_body, metadata_body = W.QVBoxLayout(action_page), W.QVBoxLayout(metadata_page)
        action_body.setContentsMargins(0, 8, 0, 0)
        metadata_body.setContentsMargins(0, 8, 0, 0)
        self.tabs.addTab(action_page, "动作条件")
        self.tabs.addTab(metadata_page, "佩戴与通道记录")
        info = W.QFormLayout()
        self.operator = W.QLineEdit()
        self.operator.setPlaceholderText("例如 P01，不需要真实姓名")
        self.wearing = W.QLineEdit()
        self.wearing.setPlaceholderText("例如 第 1 次佩戴 · 坐姿 · 右前臂")
        self.notes = W.QLineEdit()
        self.notes.setPlaceholderText("本轮整体说明，例如重新贴电极、疲劳情况")
        for name, widget in (
            ("操作者代号", self.operator),
            ("佩戴批次 / 姿态", self.wearing),
            ("本轮备注", self.notes),
        ):
            widget.setMaxLength(2000)
            widget.textChanged.connect(self._changed)
            info.addRow(name, widget)
        metadata_body.addLayout(info)
        self.channel_info = W.QLabel("连接设备后，按实际通道填写肌肉位置。")
        self.channel_info.setWordWrap(True)
        metadata_body.addWidget(self.channel_info)
        self.channels = W.QTableWidget(0, 3)
        self.channels.setHorizontalHeaderLabels(["实际通道", "肌肉 / 电极位置", "通道备注"])
        self.channels.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.channels.setMinimumHeight(110)
        self.channels.setMaximumHeight(185)
        metadata_body.addWidget(self.channels)
        toolbar = W.QHBoxLayout()
        for text, callback in (
            ("刷新实际通道", self.sync_channels),
            ("保存方案…", self.save_plan),
            ("加载方案…", self.load_plan),
        ):
            control = W.QPushButton(text)
            control.clicked.connect(lambda checked=False, fn=callback: host.guard(fn))
            toolbar.addWidget(control)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.table = W.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["采集", "动作名称", "执行部位", "力道 / 目标", "保存名称", "动作备注"]
        )
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, W.QHeaderView.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(250)
        self.table.setMaximumHeight(380)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setAlternatingRowColors(True)
        action_body.addWidget(self.table)
        actions = W.QHBoxLayout()
        for text, callback in (
            ("新增动作", self.add_condition),
            ("复制当前", self.duplicate_condition),
            ("删除当前", self.remove_condition),
            ("全选", lambda: self.check_all(True)),
            ("全不选", lambda: self.check_all(False)),
        ):
            control = W.QPushButton(text)
            control.clicked.connect(lambda checked=False, fn=callback: host.guard(fn))
            actions.addWidget(control)
        actions.addStretch()
        action_body.addLayout(actions)
        self.mode = W.QComboBox()
        self.mode.addItem("勾选动作轮采（每轮采完全部勾选动作）", "selected")
        self.mode.addItem("仅当前行补采（忽略勾选，仅采高亮行）", "current")
        action_body.addWidget(self.mode)
        layout.addWidget(self.tabs)
        self.summary = W.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.add_condition(dict(name="静息", body_part="放松", effort="自然放松", save_name="静息"))
        self.add_condition(
            dict(name="握拳", body_part="右手", effort="轻力", save_name="握拳_轻力")
        )
        self.add_condition(
            dict(name="握拳", body_part="右手", effort="重力", save_name="握拳_重力")
        )
        self.table.itemChanged.connect(self._changed)
        self.table.currentCellChanged.connect(self._changed)
        self.channels.itemChanged.connect(self._changed)
        self.mode.currentIndexChanged.connect(self._changed)
        self._changed()

    def _changed(self, *args):
        selected = len(self.selected_ids())
        self.summary.setText(
            f"已配置 {self.table.rowCount()} 个条件，本次选择 {selected} 个。重复次数由上方“动作组数”设置；保存名称留空时沿用动作名称。"
        )
        self.changed.emit()

    def add_condition(self, value=None):
        if self.table.rowCount() >= MAX_CONDITIONS:
            raise ValueError(f"最多配置 {MAX_CONDITIONS} 个条件，请拆分方案。")
        value = value if isinstance(value, dict) else {}
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        check = W.QTableWidgetItem()
        check.setFlags(C.Qt.ItemIsEnabled | C.Qt.ItemIsSelectable | C.Qt.ItemIsUserCheckable)
        check.setCheckState(C.Qt.Checked if value.get("selected", True) else C.Qt.Unchecked)
        self.table.setItem(row, 0, check)
        for column, key in enumerate(CONDITION_FIELDS, 1):
            item = W.QTableWidgetItem(value.get(key, f"动作 {row + 1}" if key == "name" else ""))
            if column == 1:
                item.setData(C.Qt.UserRole, value.get("id") or "a_" + uuid.uuid4().hex)
            self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        self.table.setCurrentCell(row, 1)
        if hasattr(self, "summary"):
            self._changed()

    def condition(self, row):
        value = {
            key: self.table.item(row, column).text().strip()
            for column, key in enumerate(CONDITION_FIELDS, 1)
        }
        value["id"] = self.table.item(row, 1).data(C.Qt.UserRole)
        return value

    def selected_ids(self):
        if self.mode.currentData() == "current":
            row = self.table.currentRow()
            return [self.table.item(row, 1).data(C.Qt.UserRole)] if row >= 0 else []
        return [
            self.table.item(row, 1).data(C.Qt.UserRole)
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == C.Qt.Checked
        ]

    def duplicate_condition(self):
        row = self.table.currentRow()
        if row < 0:
            raise ValueError("请先选择一行动作。")
        value = self.condition(row)
        value.pop("id")
        self.add_condition(value)

    def remove_condition(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._changed()

    def check_all(self, selected):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(C.Qt.Checked if selected else C.Qt.Unchecked)
        self.table.blockSignals(False)
        self._changed()

    def sync_channels(self):
        profile = self.host.backend.profile
        if not profile:
            raise ValueError("请先连接设备，再刷新实际通道。")
        previous = {r["channel_id"]: r for r in self.channel_values()}
        self.set_channels(
            [
                dict(previous.get(identity, {}), channel_id=identity)
                for identity in profile["channel_ids"]
            ]
        )
        self.channel_info.setText(
            f"当前设备：{profile['device']} · 实际 {len(profile['channel_ids'])} 通道 · {profile['channel_ids']}。更改通道请回设备连接页重新连接。"
        )

    def set_channels(self, channels):
        self.channels.blockSignals(True)
        self.channels.setRowCount(len(channels))
        for row, value in enumerate(channels):
            item = W.QTableWidgetItem(str(value["channel_id"]))
            item.setData(C.Qt.UserRole, value["channel_id"])
            item.setFlags(C.Qt.ItemIsSelectable | C.Qt.ItemIsEnabled)
            self.channels.setItem(row, 0, item)
            self.channels.setItem(row, 1, W.QTableWidgetItem(value.get("muscle", "")))
            self.channels.setItem(row, 2, W.QTableWidgetItem(value.get("notes", "")))
        self.channels.blockSignals(False)

    def channel_values(self):
        return [
            dict(
                channel_id=self.channels.item(row, 0).data(C.Qt.UserRole),
                muscle=self.channels.item(row, 1).text(),
                notes=self.channels.item(row, 2).text(),
            )
            for row in range(self.channels.rowCount())
        ]

    def plan(self):
        return validate_plan(
            dict(
                version=1,
                operator=self.operator.text(),
                wearing=self.wearing.text(),
                notes=self.notes.text(),
                channels=self.channel_values(),
                conditions=[self.condition(row) for row in range(self.table.rowCount())],
                selected_ids=self.selected_ids(),
                timing=dict(
                    trial_count=self.host.trial_count.value(),
                    action_seconds=self.host.action_seconds.value(),
                    random_order=self.host.random_order.isChecked(),
                ),
            )
        )

    def set_plan(self, plan):
        plan = validate_plan(plan)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        # Suppress selection callbacks while each row is being constructed.
        for value in plan["conditions"]:
            self.add_condition(dict(value, selected=value["id"] in plan["selected_ids"]))
        self.table.blockSignals(False)
        self.mode.setCurrentIndex(0)
        self.operator.setText(plan["operator"])
        self.wearing.setText(plan["wearing"])
        self.notes.setText(plan["notes"])
        self.set_channels(plan["channels"])
        if "timing" in plan:
            self.host.trial_count.setValue(plan["timing"]["trial_count"])
            self.host.action_seconds.setValue(plan["timing"]["action_seconds"])
            self.host.random_order.setChecked(plan["timing"]["random_order"])
        self._changed()

    def save_plan(self):
        plan = self.plan()
        path, _ = W.QFileDialog.getSaveFileName(
            self,
            "保存采集方案",
            str(self.host.backend.root / "capture-plan.json"),
            "采集方案 (*.json)",
        )
        if path:
            self.host.backend.save_capture_plan(path, plan)
            self.host.message("方案已保存；下次可加载并调整。实际通道仍以设备为准。")

    def load_plan(self):
        path, _ = W.QFileDialog.getOpenFileName(
            self, "加载采集方案", str(self.host.backend.root), "采集方案 (*.json)"
        )
        if path:
            self.set_plan(self.host.backend.load_capture_plan(path))
            if self.host.backend.profile:
                self.sync_channels()
            self.host.message("已加载采集方案。开始前请核对操作者、佩戴和通道位置。")
