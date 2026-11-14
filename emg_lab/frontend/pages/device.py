"""DevicePage: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    W,
    WaveformPreview,
    available_devices,
    button,
    card,
    fields,
    row,
    text_label,
)


class DevicePage:
    def make_device_page(self):
        layout = self.page(
            "01  设备连接",
            "连接肌电设备",
            "选择设备并填写传感器编号。没有硬件时，选择“模拟设备”即可开始。",
        )
        panel, body = card("设备配置")
        self.device_combo = W.QComboBox()
        for text, value in available_devices():
            self.device_combo.addItem(text, value)
        self.device_combo.currentIndexChanged.connect(self.update_controls)
        self.channels = W.QLineEdit("1,2,3,4")
        self.channels.setPlaceholderText("例如 1,2,3,4；Delsys 使用配对编号")
        body.addLayout(fields(("肌电设备", self.device_combo), ("传感器编号", self.channels)))
        self.scan_button = button(
            "扫描传感器", lambda: self.guard(lambda: self.connect_device("scan"))
        )
        self.pair_number = W.QSpinBox()
        self.pair_number.setRange(1, 16)
        self.pair_button = button(
            "配对传感器", lambda: self.guard(lambda: self.connect_device("pair"))
        )
        self.delsys_panel = W.QWidget()
        self.delsys_panel.setLayout(
            row(self.scan_button, "配对编号", self.pair_number, self.pair_button, 1)
        )
        self.delsys_panel.layout().setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.delsys_panel)
        self.device_status = text_label("设备未连接", "status")
        body.addWidget(self.device_status)
        self.bandpass = W.QCheckBox("带通滤波 · 滤除杂波")
        self.bandpass.setToolTip("带通 20–450 Hz；上限不超过采样率的 45%。")
        self.bandpass.setChecked(True)
        self.notch = W.QCheckBox("50 Hz 陷波 · 抑制电源干扰")
        self.notch.setToolTip("50 Hz 陷波。")
        self.notch.setChecked(True)
        self.bandpass.toggled.connect(lambda: self.guard(self.apply_filters))
        self.notch.toggled.connect(lambda: self.guard(self.apply_filters))
        body.addLayout(row(self.bandpass, self.notch, 1, text_label("推荐保持开启")))
        layout.addWidget(panel)
        panel, body = card("实时波形")
        self.waveform = WaveformPreview()
        body.addWidget(self.waveform)
        self.device_health = text_label("连接后先观察波形，再开始采集。")
        body.addWidget(self.device_health)
        layout.addWidget(panel, 1)
        self.connect_button = button("连接设备", lambda: self.guard(self.connect_device), True)
        self.disconnect_button = button("断开设备", self.disconnect_device)
        self.page_actions["01  设备连接"].addLayout(
            row(
                self.connect_button,
                self.disconnect_button,
                1,
                button("下一步：采集数据 →", lambda: self.tabs.setCurrentIndex(1)),
            )
        )
