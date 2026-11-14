"""InferencePresenter: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    HAND5,
    HAND_RATE,
    REASONS,
    Path,
    QtCore,
    QtGui,
    RaceConfig,
    speed_summary,
)


class InferencePresenter:
    def update_hand_views(self):
        if not hasattr(self, "infer_hand_view"):
            return
        hand = self.task.key == "hand"
        for widget in (self.infer_hand_view, self.infer_hand_feedback):
            widget.setVisible(hand and self.infer_scene.isChecked())

    def hand_scene_status(self, status):
        text = f"3D 模拟 · {self.task.names[status['command']]} · 开合 {status['progress']:.0f}% · 固定 {HAND_RATE} %/s · 拇指保持默认姿态"
        if self.task == HAND5:
            text = (
                f"3D 预设姿态 · {self.task.names[status['command']]} · 平滑切换，停止保持当前位置"
            )
        self.infer_hand_feedback.setText(text)

    def connect_hand(self):
        if self.hand_output:
            return
        from emg_lab.frontend.bridge import HandOutput

        output = self.hand_output = HandOutput(self)
        output.changed.connect(self.hand_status.setText)
        output.changed.connect(self.update_controls)
        output.failed.connect(self.hand_failed)
        output.sample.connect(
            lambda sample: self.hand_feedback.setText(
                f"四指位置回读（0–1000）：{sample['positions'][2:]}"
            )
        )
        output.connect_hand()
        self.update_controls()

    def disconnect_hand(self):
        if self.backend.inference and self.hand_output and self.hand_output.enabled:
            self.stop_inference()
        output, self.hand_output = self.hand_output, None
        error = self.backend.disconnect_hand()
        if output:
            output.deleteLater()
        self.hand_status.setText(
            "连接已关闭；" + error if error else "灵巧手未连接。可先连接，再开始推理。"
        )
        self.hand_feedback.setText("连接后显示四指位置回读。")
        if error:
            self.message(error, True)
        self.update_controls()

    def hand_failed(self, message):
        self.stop_inference()
        self.disconnect_hand()
        self.hand_status.setText("灵巧手连接异常：" + message)
        self.message(message, True)

    def start_inference(self):
        self._inference_identity = None
        model = self.models.currentData()
        if not model:
            raise ValueError("请先选择模型。")
        source = self.source.currentData()
        if source == "replay" and self.backend.device_present:
            raise ValueError("请先在“设备连接”页断开设备，再开始数据回放。")
        if source == "live" and not self.backend.device_ready:
            raise ValueError("请先连接实时设备。")
        recording = self.replay_records.currentData()
        if source == "replay" and not recording:
            raise ValueError("请选择要回放的数据文件。")
        if self.task.key == "robot":
            self.scene.competition = None
        if self.practice_mode.currentData() == "coins":
            if self.task.key != "robot":
                raise ValueError("金币任务仅用于机器人。")
            if self.dds_check.isChecked():
                raise ValueError("金币比赛使用统一仿真，请关闭真机输出。")
            config = RaceConfig(
                seed=self.race_seed.value(),
                count=self.race_count.value(),
                limit_s=self.race_seconds.value(),
                official=self.race_official.isChecked(),
                group=self.race_group.text(),
            )
            self.scene.competition = self.backend.prepare_competition(
                config, model, source, recording
            )
            self.competition_token = self.scene.competition["context"]["run_token"]
            self.infer_scene.setChecked(True)
        self.check_real_output(source)
        if self.infer_scene.isChecked():
            self.prepare_scene("open", lambda: self.begin_inference(model, source, recording))
        else:
            self.begin_inference(model, source, recording)

    def begin_inference(self, model, source, recording):
        try:
            self.check_real_output(source)
            selected = (
                self.hand_check.isChecked()
                if self.task.key == "hand"
                else self.dds_check.isChecked()
            )
            self.backend.start_inference(
                model,
                source,
                recording,
                assessment=self.practice_mode.currentData() == "assessment",
                output=selected,
            )
            self._inference_identity = self.backend.inference_identity
            if self.practice_mode.currentData() == "coins":
                self.scene.arm_competition()
            if selected and self.task.key == "robot":
                self.dds_status.setText("正在发送控制指令；请由助教确认机器人响应。")
        except Exception:
            self.stop_inference()
            self.scene.stop()
            raise
        self.assessment_report.setEnabled(False)
        self._last_result_end = None
        self.infer_context.setText(
            "当前模型：" + self.models.currentText() + " · " + self.source.currentText()
        )
        self.infer_context.hide()
        self.message("推理已开始，请观察当前指令和动作反馈。")
        self.update_controls()
        self.reveal_activity(
            "04  使用模型",
            self.assessment_panel
            if self.practice_mode.currentData() == "assessment"
            else self.prediction.parentWidget().parentWidget(),
        )

    def stop_inference(self, reason="aborted"):
        presented = self._inference_identity is not None
        self._inference_identity = None
        if not isinstance(reason, str):
            reason = "aborted"  # QPushButton.clicked may supply a bool.
        if self.task.key == "robot":
            self.scene.end_competition(reason)
        if self.scene_pending and self.scene_pending[0] == "open":
            self.scene_pending = None
            self.backend.cancel_pending()
            self.scene.stop()
            self.message("已取消推理。")
        active = self.backend.inference or presented
        self.backend.stop_inference()
        self.assessment_report.setEnabled(self.backend.last_assessment_path is not None)
        if active:
            self.infer_context.hide()
            self.scene.stop()
            self.prediction.setText("推理已停止")
            self.message("推理已结束，预测结果已保存。")
        self.update_controls()

    def configure_competition(self):
        rules = self.backend.rules()
        if self.race_official.isChecked():
            self.race_count.setValue(rules["count"])
            self.race_seconds.setValue(rules["limit_s"])
        self.race_rules_hint.setText(
            "固定分类："
            + speed_summary()
            + "。所有模型统一榜单。\n教师规定种子："
            + "、".join(map(str, rules["official_seeds"]))
            + "。正式比赛的模型与代码必须提前审核并固定。"
        )
        self.update_controls()

    def on_competition_finished(self, path):
        self.last_competition_path = Path(path)
        report = self.backend.read_metadata(self.last_competition_path.with_name("result.json"))
        if report["context"].get("run_token") == self.competition_token:
            self.stop_inference()
            self.competition_token = None
        self.race_report.setEnabled(True)
        result = f"{report['count']} / {report['config']['count']} 枚 · 计分用时 {report['scored_seconds']:.2f} 秒 · {REASONS.get(report['reason'], report['reason'])}"
        self.race_result.setText(result + "\n" + str(self.last_competition_path.parent))
        self.message("金币任务已保存：" + result)
        if self.task.key == "robot" and self.practice_mode.currentData() == "coins":
            self.reveal_activity("04  使用模型", self.competition_panel)

    def open_competition_report(self):
        if self.last_competition_path:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self.last_competition_path.resolve()))
            )

    def open_assessment_report(self):
        if self.backend.last_assessment_path:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self.backend.last_assessment_path.resolve()))
            )

    def check_real_output(self, source):
        self.backend.check_output(
            source,
            self.hand_check.isChecked() if self.task.key == "hand" else self.dds_check.isChecked(),
        )

    def connect_dds(self):
        self.dds_output = self.backend.connect_dds(
            self.domain.value(), self.interface.text().strip()
        )
        self.dds_status.setText("DDS 发布端已连接 · 待机；请由助教确认机器人端就绪。")
        self.update_controls()

    def disconnect_dds(self):
        if self.backend.inference and self.dds_output:
            self.stop_inference()
        try:
            self.backend.disconnect_dds()
            self.dds_status.setText("机器人未连接。可先连接，再开始推理。")
        except Exception as error:
            self.message(str(error), True)
        self.dds_output = None
        self.update_controls()
