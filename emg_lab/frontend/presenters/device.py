"""DevicePresenter: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import DeviceConfig, SignalConfig, device_name


class DevicePresenter:
    def connect_device(self, action="connect"):
        channels = tuple(
            sorted(
                set(
                    int(x.strip())
                    for x in self.channels.text().replace("，", ",").split(",")
                    if x.strip()
                )
            )
        )
        self.backend.connect_device(
            DeviceConfig(
                self.device_combo.currentData(), channels, action, self.pair_number.value()
            )
        )
        self.device_status.setText("正在连接…" if action == "connect" else "正在扫描/配对…")
        self.update_controls()

    def device_message(self, event):
        self.backend.accept_device_event(event)

    def on_device(self, event):
        kind = event["type"]
        if kind == "connected":
            profile = event["profile"]
            self.device_status.setText(
                f"{device_name(profile['device'])} 已连接 · 传感器 {profile['channel_ids']}"
            )
            self.device_status.setToolTip(
                f"采样率 {profile['sampling_rate']:g} Hz；信号单位 {profile['unit']}"
            )
            self.waveform.set_profile(profile)
            self.capture_waveform.set_profile(profile)
            if self.custom_capture_active():
                self.custom_capture.sync_channels()
            self.message("设备已连接。确认波形后，进入数据采集。")
        elif kind == "sensors":
            values = event["sensors"]
            self.device_status.setText(
                "扫描结果："
                + "；".join(f"#{v['pair_number']} {v['name']} [{v['mode']}]" for v in values)
            )
            if values:
                self.channels.setText(",".join(str(v["pair_number"]) for v in values))
        elif kind in ("error", "exited"):
            self.disconnect_device()
            if kind == "error":
                self.message(event["message"], True)
        self.update_controls()

    def disconnect_device(self):
        self.stop_capture()
        self.stop_inference()
        self.backend.disconnect_device()
        self.device_status.setText("设备未连接")
        self.update_controls()

    def apply_filters(self):
        self.backend.set_filter(
            SignalConfig(bandpass=self.bandpass.isChecked(), notch=self.notch.isChecked())
        )
