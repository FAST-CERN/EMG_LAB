"""TrainingPresenter: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    Path,
    QtCore,
    TrainingRequest,
    device_name,
    evaluation_details,
)


class TrainingPresenter:
    def start_training(self):
        paths = tuple(
            self.records.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.records.count())
            if self.records.item(i).checkState() == QtCore.Qt.Checked
        )
        self.backend.start_training(
            TrainingRequest(paths, self.model_name.text(), self.epochs.value())
        )
        self.train_progress.setValue(0)
        self.training_result.clear()
        self.update_controls()
        self.reveal_activity("03  训练模型", self.train_progress.parentWidget())

    def on_train(self, event):
        if event["type"] == "progress":
            self.train_progress.setValue(round(event["progress"] * 1000))
            self.train_status.setText(
                event["stage"]
                + (
                    f" · 验证窗口分类 {event['val_accuracy']:.1%}"
                    if event.get("val_accuracy") is not None
                    else ""
                )
            )
        elif event["type"] == "complete":
            self.train_progress.setValue(1000)
            m = event["metadata"]
            self.training_result.setPlainText(
                f"模型“{m['name']}”已保存。\n{evaluation_details(m)}\n下一步：进入“使用模型”，这个模型已为你选好。"
            )
            self.train_status.setText("训练完成。")
            self.refresh_data()
            self.models.setCurrentIndex(self.models.findData(event["path"]))
            self.message("模型已保存，下一步进入“使用模型”。")
        elif event["type"] == "error":
            self.train_status.setText("训练失败，详情见下方提示。")
            self.message(event["message"], True)
        self.update_controls()

    def stop_training(self):
        self.backend.stop_training()
        self.train_status.setText("训练已停止；不完整模型不会出现在推理列表。")
        self.update_controls()

    def model_details(self):
        path = self.models.currentData()
        if path:
            try:
                m = self.backend.read_metadata(Path(path) / "metadata.json")
                self.model_summary.setText(
                    f"{device_name(m['device'])} · 传感器 {m['channel_ids']} · {m.get('name', '已选择模型')}"
                )
                self.model_info.setText(
                    f"适用设备：{device_name(m['device'])} · 传感器 {m['channel_ids']}\n{evaluation_details(m)}"
                )
            except (OSError, ValueError, KeyError):
                self.model_info.setText("模型信息不完整，请重新选择。")
                self.model_summary.setText("模型信息不完整，请重新选择。")
        else:
            self.model_info.setText("尚无模型，请先完成训练。")
            self.model_summary.setText("尚无模型，请先训练或导入。")
