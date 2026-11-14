"""Small reusable notes and conservative signal checks for classroom capture."""

from PySide6 import QtWidgets as W

from emg_lab.contracts.notes import clean_notes


class CollectionNotesDialog(W.QDialog):
    def __init__(self, notes, task, parent=None):
        super().__init__(parent)
        self.setWindowTitle("采集记录 · 同一佩戴可沿用")
        self.resize(600, 470)
        layout = W.QVBoxLayout(self)
        tip = W.QLabel("可选填写，随数据一起保存。换人、重新佩戴或改变动作时再更新。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.operator = W.QLineEdit(notes.get("operator", ""))
        self.operator.setPlaceholderText("例如 P01，不用真实姓名")
        self.wearing = W.QLineEdit(notes.get("wearing", ""))
        self.wearing.setPlaceholderText("例如 第1次佩戴；坐姿")
        self.channels = W.QPlainTextEdit(notes.get("channels", ""))
        self.channels.setPlaceholderText("例如：1 左前臂；2 右前臂……")
        self.channels.setMaximumHeight(90)
        self.actions = W.QPlainTextEdit(
            notes.get("actions", "")
            or "\n".join(
                name + "：" + ("放松 / 静息" if i == 0 else "") for i, name in enumerate(task.names)
            )
        )
        self.actions.setPlaceholderText("填写操作者实际做的肌肉动作，不是机器人动作本身")
        form = W.QFormLayout()
        form.addRow("操作者代号", self.operator)
        form.addRow("本次佩戴", self.wearing)
        form.addRow("通道位置", self.channels)
        form.addRow("动作约定", self.actions)
        layout.addLayout(form)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Save | W.QDialogButtonBox.Cancel)
        buttons.button(W.QDialogButtonBox.Save).setText("保存并沿用")
        buttons.button(W.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def notes(self):
        return clean_notes(
            dict(
                operator=self.operator.text(),
                wearing=self.wearing.text(),
                channels=self.channels.toPlainText(),
                actions=self.actions.toPlainText(),
            )
        )
