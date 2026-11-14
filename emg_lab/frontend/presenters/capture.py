"""CapturePresenter: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import CollectionNotesDialog, W, safe_name


class CapturePresenter:
    def start_capture(self):
        if not self.backend.device_ready:
            raise ValueError("请先连接设备。")
        if self.custom_capture_active():
            self.custom_capture.sync_channels()
            self.custom_capture.plan()  # Validate before opening files or starting a run.
            self.begin_capture()
        elif self.scene_check.isChecked():
            self.prepare_scene("sample", self.begin_capture)
        else:
            self.begin_capture()

    def prepare_scene(self, mode, action):
        if self.scene_pending or self.backend.capture or self.backend.inference:
            raise ValueError("请先结束当前实验。")
        self.backend.set_pending(mode)
        self.scene_pending = (mode, action)
        self.message(
            "正在载入灵巧手 3D 模型，完成后自动开始。"
            if self.task.key == "hand"
            else "正在准备机器人，站稳后自动开始。"
        )
        self.update_controls()
        try:
            if self.task.key == "robot":
                self.scene.source = self.source.currentData()
            self.scene.start(mode)
        except Exception:
            self.scene_pending = None
            self.backend.cancel_pending()
            self.scene.stop()
            self.update_controls()
            raise

    def finish_scene_start(self):
        pending, self.scene_pending = self.scene_pending, None
        if pending:
            self.guard(pending[1])
            self.update_controls()

    def on_scene_error(self, message):
        self.stop_capture()
        self.stop_inference()
        self.scene.stop()
        self.message(message + " 已采集的数据会保存；可重新开始，或取消显示 3D 画面。", True)

    def on_scene_closed(self):
        self.stop_capture()
        self.stop_inference()
        self.scene.stop()

    def edit_collection_notes(self):
        group = self.group.text().strip()
        safe_name(group)
        dialog = CollectionNotesDialog(self.backend.notes(group), self.task, self)
        if dialog.exec() == W.QDialog.Accepted:
            self.backend.save_notes(group, dialog.notes())
            self.message("采集记录已保存；本组、当前采集方案下次会沿用。换人或重新佩戴后请更新。")

    def reject_current_trial(self):
        capture = self.backend.capture
        if not capture or capture.completed:
            return
        trial = capture.status()["trial"]
        reason, ok = W.QInputDialog.getItem(
            self,
            f"标记第 {trial} 组无效",
            "原因（原始数据保留，稍后补采一组）",
            ["动作做错或没跟上", "信号异常或传感器问题", "疲劳 / 其他"],
            0,
            False,
        )
        if ok:
            self.backend.reject_capture_trial(capture, trial, reason)
            self.message(
                f"第 {trial} 组已标记无效，训练和基础评估会跳过。采集继续，结束后补采一组。"
            )

    def begin_capture(self):
        try:
            path = self.backend.start_capture(
                self.group.text(),
                self.experiment.text(),
                self.trial_count.value(),
                self.action_seconds.value(),
                random_order=self.random_order.isChecked(),
                collection_notes={}
                if self.custom_capture_active()
                else self.backend.notes(self.group.text().strip()),
                capture_plan=self.custom_capture.plan() if self.custom_capture_active() else None,
            )
            self._capture_identity = str(path)
        except Exception:
            self.scene.stop()
            raise
        self._last_cue = None
        self.message("采集中，请跟随动作提示；结束后会自动保存。")
        self.update_controls()
        self.reveal_activity("02  采集数据", self.cue)

    def stop_capture(self):
        if self.scene_pending and self.scene_pending[0] == "sample":
            self.scene_pending = None
            self.backend.cancel_pending()
            self.scene.stop()
            self.message("已取消采集，尚未开始记录数据。")
        capture = self.backend.stop_capture()
        self.show_capture_finished(capture)

    def show_capture_finished(self, capture):
        if capture:
            self._capture_identity = None
            self.scene.stop()
            meta = capture.metadata
            count = meta.get("usable_trials", meta.get("completed_trials", 0))
            rejected = len(meta.get("rejected_trials", []))
            self.cue.setText("本次采集已完成" if capture.completed else "本次采集已结束")
            self.capture_status.setText(
                f"已保存 1 个数据文件，可用 {count} 组动作。"
                + (f" 标记无效 {rejected} 组，请补采。" if rejected else "")
            )
            self.refresh_data()
            if meta.get("capture_only"):
                self.message(
                    f"已保存 {count} 轮自定义采集及动作索引 CSV。数据与模型页可查看、导出；暂不用于机器人训练或控制。"
                )
                self.update_controls()
                return
            self.select_latest()
            self.message(
                "数据已保存并选中，下一步进入“训练模型”。"
                if count
                else "数据已保存，但还没有完整的一组动作。"
            )
        self.update_controls()
