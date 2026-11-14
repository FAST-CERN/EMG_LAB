"""ArtifactPresenter: desktop presentation and application-port calls."""

from __future__ import annotations

from emg_lab.frontend.components import (
    Path,
    QtCore,
    W,
    device_name,
    record_label,
    require_task,
    usable_record,
)


class ArtifactPresenter:
    def open_library(self, kind=None):
        self.library.refresh()
        self.library.reset_filters()
        if kind:
            self.library.kind.setCurrentIndex(self.library.kind.findData(kind))
            self.library.target.setCurrentIndex(self.library.target.findData(self.task.key))
        self.stack.setCurrentIndex(1)
        self.tabs.setCurrentIndex(4)
        self.page_scrolls["数据与模型"].verticalScrollBar().setValue(0)

    def use_library(self, action, entries):
        self.require_transfer_idle()
        self.backend.validate_use(action, entries)
        self.select_task(entries[0].task.selector)
        self.refresh_data()
        if action == "train":
            selected = {str(entry.path) for entry in entries}
            for i in range(self.records.count()):
                item = self.records.item(i)
                item.setCheckState(
                    QtCore.Qt.Checked
                    if item.data(QtCore.Qt.UserRole) in selected
                    else QtCore.Qt.Unchecked
                )
            self.tabs.setCurrentIndex(2)
            self.message(f"已选择 {len(entries)} 份数据，请设置模型名称与学习遍数后开始训练。")
        else:
            combo = self.models if action == "model" else self.replay_records
            combo.setCurrentIndex(combo.findData(str(entries[0].path)))
            if action == "replay":
                self.source.setCurrentIndex(self.source.findData("replay"))
            self.tabs.setCurrentIndex(3)
            self.message(
                "已选择模型。请确认数据来源后开始推理。"
                if action == "model"
                else "已选择回放数据，请选择兼容模型。回放前需在设备连接页断开采集设备。"
            )
        self.page_scrolls[self.tabs.tabText(self.tabs.currentIndex())].verticalScrollBar().setValue(
            0
        )

    def refresh_data(self):
        checked = {
            self.records.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.records.count())
            if self.records.item(i).checkState() == QtCore.Qt.Checked
        }
        current_record = self.replay_records.currentData()
        current_model = self.models.currentData()
        self.records.clear()
        self.replay_records.clear()
        all_records = dict(self.imported_records)
        all_records.update({str(p): m for p, m in self.backend.recordings()})
        for path, meta in sorted(
            all_records.items(), key=lambda pair: pair[1].get("created_at", ""), reverse=True
        ):
            try:
                require_task(meta, self.task)
            except ValueError:
                continue
            self.add_record(path, meta, str(path) in checked)
            self.replay_records.addItem(record_label(meta), str(path))
        self.models.clear()
        all_models = dict(self.imported_models)
        all_models.update({str(p): m for p, m in self.backend.models()})
        for path, meta in sorted(
            all_models.items(), key=lambda pair: pair[1].get("created_at", ""), reverse=True
        ):
            try:
                require_task(meta, self.task)
            except ValueError:
                continue
            self.models.addItem(
                f"{meta['name']} · {meta['group']} · {device_name(meta['device'])} · {meta['created_at'][:19].replace('T', ' ')}",
                str(path),
            )
        for combo, value in ((self.models, current_model), (self.replay_records, current_record)):
            i = combo.findData(value)
            if i >= 0:
                combo.setCurrentIndex(i)
        self.model_details()
        self.update_record_summary()
        if hasattr(self, "library"):
            self.library.refresh()

    def add_record(self, path, meta, checked=False):
        item = W.QListWidgetItem(record_label(meta))
        item.setData(QtCore.Qt.UserRole, str(path))
        item.setToolTip(str(path))
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(
            QtCore.Qt.Checked if checked and usable_record(meta) else QtCore.Qt.Unchecked
        )
        if not usable_record(meta):
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
        self.records.addItem(item)

    def select_latest(self):
        selected = None
        for i in range(self.records.count()):
            item = self.records.item(i)
            if selected is None and item.flags() & QtCore.Qt.ItemIsEnabled:
                selected = i
            item.setCheckState(QtCore.Qt.Checked if i == selected else QtCore.Qt.Unchecked)

    def choose_data(self):
        path, _ = W.QFileDialog.getOpenFileName(
            self,
            "选择采集的数据文件",
            str(self.backend.root),
            "肌电数据 (*.emg);;旧版肌电数据 (emg.bin)",
        )
        if path:
            return str(Path(path).parent) if Path(path).name == "emg.bin" else str(Path(path))
        return None

    def require_transfer_idle(self):
        self.backend.require_idle()

    def show_transfer_result(self, title, paths, errors=(), *, exported=False, reused=0):
        text = f"{title}：成功 {len(paths)} 项"
        if reused:
            text += f"（其中 {reused} 项已存在，已重新选中）"
        if errors:
            text += f"；失败 {len(errors)} 项"
        if exported and paths:
            text += f"\n保存到：{Path(paths[0]).parent}"
        elif paths:
            text += "\n已保存在本机数据目录，重启后仍可使用。"
        self.message(text, error=bool(errors))
        if exported or errors:
            box = W.QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(W.QMessageBox.Warning if errors else W.QMessageBox.Information)
            box.setText(text)
            box.setDetailedText("\n".join([*[str(p) for p in paths], *errors]))
            box.addButton(W.QMessageBox.Ok)
            open_button = (
                box.addButton("打开导出文件夹", W.QMessageBox.ActionRole)
                if exported and paths
                else None
            )
            box.exec()
            if open_button is not None and box.clickedButton() == open_button:
                self.open_folder(Path(paths[0]).parent)

    def choose_export_folder(self):
        selected = W.QFileDialog.getExistingDirectory(
            self, "选择导出到哪个文件夹", self.last_transfer_folder
        )
        if selected:
            self.last_transfer_folder = selected
        return selected

    def import_record(self):
        self.require_transfer_idle()
        selected, _ = W.QFileDialog.getOpenFileNames(
            self,
            "导入数据（可多选）",
            self.last_transfer_folder,
            "肌电数据 (*.emg);;旧版肌电数据 (emg.bin)",
        )
        if not selected:
            return
        paths, errors, reused = [], [], 0
        for source in selected:
            try:
                result = self.backend.transfer.import_recording(
                    source, self.backend.root, self.task
                )
                paths.append(result.path)
                reused += result.reused
            except Exception as exc:
                errors.append(f"{Path(source).name}：{exc}")
        if paths:
            self.last_transfer_folder = str(Path(selected[0]).parent)
            self.refresh_data()
            for i in range(self.records.count()):
                item = self.records.item(i)
                checked = Path(item.data(QtCore.Qt.UserRole)) in paths and bool(
                    item.flags() & QtCore.Qt.ItemIsEnabled
                )
                item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
            self.replay_records.setCurrentIndex(self.replay_records.findData(str(paths[-1])))
        self.show_transfer_result("导入数据", paths, errors, reused=reused)

    def export_records(self):
        self.require_transfer_idle()
        paths = [
            self.records.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.records.count())
            if self.records.item(i).checkState() == QtCore.Qt.Checked
        ]
        if not paths:
            raise ValueError("请先勾选要导出的数据。")
        self.export_record_paths(paths)

    def export_record_paths(self, paths):
        destination = self.choose_export_folder()
        if not destination:
            return
        exported, errors = [], []
        for path in paths:
            try:
                exported.append(
                    self.backend.transfer.export_recording(path, destination, self.task)
                )
            except Exception as exc:
                errors.append(f"{Path(path).name}：{exc}")
        self.show_transfer_result("导出数据", exported, errors, exported=True)

    def export_replay(self):
        self.require_transfer_idle()
        path = self.replay_records.currentData()
        if not path:
            raise ValueError("请先选择要导出的回放数据。")
        self.export_record_paths([path])

    def import_model(self):
        self.require_transfer_idle()
        selected, _ = W.QFileDialog.getOpenFileName(
            self,
            "导入模型包或 model.onnx",
            self.last_transfer_folder,
            "模型包或 ONNX (*.emgmodel *.onnx);;模型包 (*.emgmodel);;原模型文件 (model.onnx)",
        )
        if selected:
            result = self.backend.transfer.import_model(selected, self.backend.root, self.task)
            self.last_transfer_folder = str(Path(selected).parent)
            self.refresh_data()
            self.models.setCurrentIndex(self.models.findData(str(result.path)))
            self.show_transfer_result("导入模型", [result.path], reused=int(result.reused))

    def export_model(self):
        self.require_transfer_idle()
        path = self.models.currentData()
        if not path:
            raise ValueError("请先训练或选择一个模型。")
        destination = self.choose_export_folder()
        if destination:
            output = self.backend.transfer.export_model(path, destination, self.task)
            self.show_transfer_result("导出模型", [output], exported=True)

    def import_replay(self):
        self.require_transfer_idle()
        path = self.choose_data()
        if path:
            result = self.backend.transfer.import_recording(path, self.backend.root, self.task)
            self.refresh_data()
            self.replay_records.setCurrentIndex(self.replay_records.findData(str(result.path)))
            self.source.setCurrentIndex(1)
            self.show_transfer_result("导入回放数据", [result.path], reused=int(result.reused))
