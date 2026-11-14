"""Find and export existing reports; does not recompute or rank results."""

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W


class ReportsDialog(W.QDialog):
    def __init__(self, host, group=""):
        super().__init__(host)
        self.host = host
        self.rows = host.backend.find_reports(group)
        self.setWindowTitle("评估记录" + (" · " + group if group else ""))
        self.resize(960, 560)
        layout = W.QVBoxLayout(self)
        tip = W.QLabel("选择记录后打开报告，或多选导出作为作业材料。比较算法时请使用相同测试条件。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.table = W.QTableWidget(len(self.rows), 5)
        self.table.setHorizontalHeaderLabels(["日期", "组别", "类型", "模型", "结果"])
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        for i, row in enumerate(self.rows):
            for j, key in enumerate(("date", "group", "kind", "model", "result")):
                item = W.QTableWidgetItem(str(row[key]))
                item.setToolTip(str(row[key]))
                self.table.setItem(i, j, item)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, W.QHeaderView.Stretch)
        layout.addWidget(self.table)
        if not self.rows:
            layout.addWidget(
                W.QLabel("还没有评估记录。完成一次基础评估或金币任务后会自动保存在这里。")
            )
        self.message = W.QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = W.QHBoxLayout()
        for title, action in [
            ("打开报告", self.open_report),
            ("导出选中…", self.export),
            ("关闭", self.close),
        ]:
            button = W.QPushButton(title)
            button.clicked.connect(lambda checked=False, fn=action: self.guard(fn))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.table.cellDoubleClicked.connect(lambda *_: self.guard(self.open_report))

    def guard(self, action):
        try:
            action()
        except Exception as error:
            self.message.setText(str(error))

    def selected(self):
        return [self.rows[i.row()] for i in self.table.selectionModel().selectedRows()]

    def open_report(self):
        selected = self.selected()
        if len(selected) != 1:
            raise ValueError("请选择一份报告打开；可按住 Ctrl 多选后导出。")
        G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(selected[0]["html"])))

    def export(self):
        selected = self.selected()
        if not selected:
            raise ValueError("请先选中要导出的记录。")
        folder = W.QFileDialog.getExistingDirectory(
            self, "选择导出文件夹", str(self.host.session.root)
        )
        if folder:
            output = self.host.backend.export_reports(selected, folder)
            self.message.setText("评估记录已导出到：" + str(output))
            G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(output)))
