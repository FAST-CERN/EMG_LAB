"""StatusPresenter: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    HAND,
    HAND5,
    ROBOT,
    ROBOT7,
    device_name,
    preparation_countdown,
    time,
)


class StatusPresenter:
    def update_controls(self):
        if not hasattr(self, "infer_start"):
            return
        capture = self.backend.capture is not None
        inference = self.backend.inference
        training = self.backend.training
        pending = self.scene_pending[0] if self.scene_pending else None
        task = capture or inference or training or pending is not None
        coin_index = self.practice_mode.findData("coins")
        self.practice_mode.model().item(coin_index).setEnabled(self.task.key == "robot")
        if self.task.key != "robot" and self.practice_mode.currentData() == "coins":
            self.practice_mode.setCurrentIndex(0)
        coins = self.practice_mode.currentData() == "coins"
        self.hardware_output_panel.setVisible(not coins)
        self.competition_panel.setVisible(coins)
        for widget in (self.race_group, self.race_seed, self.race_official):
            widget.setEnabled(not task)
        for widget in (self.race_count, self.race_seconds):
            widget.setEnabled(not task and not self.race_official.isChecked())
        replay = self.source.currentData() == "replay"
        for widget in (
            self.device_combo,
            self.channels,
            self.scan_button,
            self.pair_button,
            self.pair_number,
        ):
            widget.setEnabled(not self.backend.device_present and not task)
        self.connect_button.setEnabled(not self.backend.device_present and not task)
        self.disconnect_button.setEnabled(self.backend.device_present)
        for widget in (self.bandpass, self.notch):
            widget.setEnabled(not task)
        for widget in (
            self.group,
            self.experiment,
            self.trial_count,
            self.action_seconds,
            self.scene_check,
            self.random_order,
            self.task_choice,
            self.training_task_choice,
            self.inference_task_choice,
            self.collection_notes_button,
        ):
            widget.setEnabled(not task)
        self.capture_start.setEnabled(self.backend.device_ready and not task)
        self.capture_stop.setEnabled(capture or pending == "sample")
        self.reject_trial_button.setEnabled(bool(capture))
        for widget in (
            self.records,
            self.model_name,
            self.epochs,
            self.record_refresh,
            self.record_latest,
        ):
            widget.setEnabled(not task)
        self.train_start.setEnabled(not task)
        self.train_stop.setEnabled(training)
        for widget in (
            self.source,
            self.models,
            self.infer_scene,
            self.model_refresh,
            self.practice_mode,
        ):
            widget.setEnabled(not task)
        if coins:
            self.infer_scene.setChecked(True)
            self.infer_scene.setEnabled(False)
            self.dds_check.setChecked(False)
        self.assessment_panel.setVisible(self.practice_mode.currentData() == "assessment")
        self.practice_hint.setText(
            "金币任务：相同种子生成相同完整路线。练习支持实时与回放；正式成绩只接受真实肌电实时控制。"
            if coins
            else "基础评估：实时随机提示共 2 轮，每次准备 3 秒、动作 3 秒；回放按文件原标签对照。先另采一轮数据再评估。"
            if self.practice_mode.currentData() == "assessment"
            else "自由练习：张开 → 停止保持 → 握拳 → 食指指向 → 双指伸展；中途放松，检查是否立即停止。"
            if self.task == HAND5
            else "自由练习：张开 → 停止保持 → 握合 → 停止保持，试着停在不同开合位置。"
            if self.task.key == "hand"
            else "自由练习：前进 → 停止 → 左转 → 前进 → 停止；七类还可练习后退和左右侧移。"
        )
        self.replay_records.setEnabled(not task and replay)
        self.replay_field.setVisible(replay)
        self.replay_actions.setVisible(replay)
        self.live_source_info.setVisible(not replay)
        self.source_explanation.setText(
            "离线回放：原始肌电重新经过模型解码，标签只用于评估；与实时推理共用同一模拟场景。"
            if replay
            else "实时推理：设备肌电经过模型解码后驱动模拟场景；可选择自由练习、基础评估或金币任务。"
            if self.task.key == "robot"
            else "实时推理：设备肌电经过模型解码，控制当前任务的手部动作或姿态。"
        )
        if hasattr(self, "library"):
            self.library.set_idle(not task)
        if self.backend.device_ready and self.backend.profile:
            p = self.backend.profile
            self.live_source_info.setText(
                f"当前设备：{device_name(p['device'])} · 传感器 {p['channel_ids']}"
            )
        else:
            self.live_source_info.setText("请先在设备连接页选择设备和传感器。")
        self.infer_start.setEnabled(not task)
        self.infer_stop.setEnabled(inference or pending == "open")
        hand = self.task.key == "hand"
        self.hand_panel.setVisible(hand)
        self.hand_status.setVisible(hand)
        self.hand_details.setVisible(hand)
        self.dds_panel.setVisible(not hand and not coins)
        self.dds_status.setVisible(not hand and not coins)
        self.dds_settings.setVisible(not hand and not coins)
        self.hand_check.setEnabled(not task and self.task == HAND)
        self.dds_check.setEnabled(not task and self.task == ROBOT and not coins)
        self.hand_connect.setEnabled(
            hand and self.hand_check.isChecked() and self.hand_output is None and not task
        )
        self.hand_disconnect.setEnabled(self.hand_output is not None and not task)
        self.dds_connect.setEnabled(
            not hand and self.dds_check.isChecked() and self.dds_output is None and not task
        )
        self.dds_disconnect.setEnabled(self.dds_output is not None and not task)
        self.domain.setEnabled(self.dds_output is None and not task)
        self.interface.setEnabled(self.dds_output is None and not task)
        self.mock_action.setEnabled(
            inference and self.backend.device_ready and self.backend.profile["device"] == "模拟练习"
        )
        simulated = (
            self.backend.device_ready
            and self.backend.profile
            and self.backend.profile["device"] == "模拟练习"
        )
        self.mock_panel.setVisible(bool(simulated and not replay))
        self.delsys_panel.setVisible(self.device_combo.currentData() == "Delsys")
        self.device_status.setProperty("connected", self.backend.device_ready)
        self.device_status.style().unpolish(self.device_status)
        self.device_status.style().polish(self.device_status)
        self.update_record_summary()
        self.infer_run_status.setText(
            "推理中" if inference else "准备场景…" if pending == "open" else "等待开始"
        )
        self.hand_check.setToolTip(
            "五类姿态目前只做 3D 验证；基础三类可连接真机。"
            if self.task == HAND5
            else "可在推理前连接；只有真实肌电的实时推理才会启用动作。"
        )
        self.dds_check.setToolTip(
            "七类目前用于 MuJoCo，DDS 仍使用原有四类协议。"
            if self.task == ROBOT7
            else "可在推理前连接；只有真实肌电的实时推理才会发送控制指令。"
        )

    def tick(self):
        snapshot = self.backend.snapshot()
        if self.backend.device_ready and snapshot["profile"] and self.tabs.currentIndex() in (0, 1):
            preview = self.waveform if self.tabs.currentIndex() == 0 else self.capture_waveform
            preview.update_data(
                snapshot["raw"], snapshot["filtered"], snapshot["profile"]["sampling_rate"]
            )
        if time.monotonic() - self._health_checked >= 1.0:
            self._health_checked = time.monotonic()
            text, warning = ("未连接设备。", False)
            if self.backend.device_ready and snapshot["profile"]:
                p = snapshot["profile"]
                text, warning = self.backend.signal_check(
                    snapshot["raw"],
                    p["sampling_rate"],
                    p["channel_ids"],
                    time.monotonic() - snapshot["last_frame"],
                )
            for widget in (self.device_health, self.capture_health):
                widget.setText(text)
                widget.setStyleSheet("color:#a33b21;font-weight:600;" if warning else "")
        status = snapshot["capture"]
        self.reject_trial_button.setEnabled(
            bool(status and not status["done"] and not status.get("rejected"))
        )
        if status:
            self.scene.sample(status)
            self.capture_progress.setValue(round(status["progress"] * 1000))
            if status["done"]:
                self.cue.setText("采集完成，正在保存…")
            else:
                action = self.task.names[status["cue"]]
                if status["phase"] == "准备":
                    name = "休息" if status["cue"] == 0 else action
                    self.cue.setText(f"准备：{name}  {preparation_countdown(status)}")
                elif status["phase"] == "动作":
                    self.cue.setText(
                        ("停止 · 放松肌肉" if status["cue"] == 0 else action)
                        if self.task.key == "hand"
                        else action
                    )
                else:
                    self.cue.setText("休息，放松肌肉")
                self.capture_status.setText(
                    f"第 {status['trial']} / {status['trial_count']} 组 · 第 {status['action_index']} / {len(self.task.classes)} 个动作 · 剩余 {status['remaining']:.1f} 秒"
                    + (
                        " · 保持动作直到倒计时结束"
                        if status["phase"] == "动作" and status["cue"]
                        else " · 放松肌肉"
                    )
                    + (" · 本组已标记无效" if status.get("rejected") else "")
                )
        assessment = snapshot.get("assessment")
        if assessment:
            target = assessment["target"]
            cue = (
                "评估结束"
                if target is None
                else f"{assessment['phase']}：{self.task.names[target]}  {assessment['remaining']:.1f} 秒"
            )
            self.assessment_cue.setText(cue)
            score = (
                "等待完整动作窗口"
                if assessment["accuracy"] is None
                else f"最终指令正确率 {assessment['accuracy']:.1%} · {assessment['correct']} / {assessment['total']} 个有效窗口"
            )
            self.assessment_stats.setText(score + "；提示仅作对照，不驱动动作。")
        result = snapshot["result"]
        if snapshot["inferencing"] and result:
            self.prediction.setText(f"当前指令：{self.task.names[result['filtered_class']]}")
            for bar, p in zip(self.probabilities, result["probabilities"]):
                bar.setValue(round(p * 100))
