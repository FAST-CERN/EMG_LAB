"""One place to find, transfer and reuse classroom recordings and models."""
from datetime import date, timedelta
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W

from . import catalog
from .storage import usable_record
from .widgets import card, text_label


class LibraryWidget(W.QWidget):
    def __init__(self, host, footer):
        super().__init__()
        self.host = host
        self.entries = []
        self.visible_entries = []
        self.checked = set()
        self.idle = True
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(12)
        filters, body = card()
        body.setContentsMargins(16,12,16,12)
        body.setSpacing(10)
        self.query = W.QLineEdit()
        self.query.setPlaceholderText('搜索名称、组别或编号')
        self.kind = self.combo([('数据与模型',''),('仅数据','recording'),('仅模型','model')])
        self.target = self.combo([('全部实验',''),('机器人控制','robot'),('灵巧手控制','hand')])
        search_row = W.QHBoxLayout()
        search_row.addWidget(self.query,2)
        search_row.addWidget(self.kind,1)
        search_row.addWidget(self.target,1)
        body.addLayout(search_row)
        self.group = self.combo([('全部组别','')])
        self.device = self.combo([('全部设备','')])
        self.period = self.combo([('全部日期','all'),('最近 7 天','week'),('最近 30 天','month'),('自定义日期','custom')])
        filter_row = W.QHBoxLayout()
        for title,control in (('关键词',self.query),('文件类型',self.kind),('实验目标',self.target),
                              ('组别 / 学号',self.group),('采集设备',self.device),('采集 / 训练日期',self.period)):
            control.setAccessibleName(title)
            control.setToolTip(title)
        for control in (self.group,self.device,self.period):
            filter_row.addWidget(control,1)
        self.reset_button = self.button('重置筛选',self.reset_filters)
        self.refresh_button = self.button('刷新',host.refresh_data)
        filter_row.addWidget(self.reset_button)
        filter_row.addWidget(self.refresh_button)
        body.addLayout(filter_row)
        self.date_range = W.QWidget()
        dates = W.QHBoxLayout(self.date_range)
        dates.setContentsMargins(0,0,0,0)
        self.start = W.QDateEdit(C.QDate.currentDate().addMonths(-1))
        self.end = W.QDateEdit(C.QDate.currentDate())
        for widget in (self.start,self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat('yyyy-MM-dd')
        dates.addWidget(text_label('开始日期'))
        dates.addWidget(self.start)
        dates.addWidget(text_label('结束日期'))
        dates.addWidget(self.end)
        dates.addStretch()
        body.addWidget(self.date_range)
        self.date_range.hide()
        layout.addWidget(filters)
        self.table = W.QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(['选择','类型','名称','实验','组别','日期','设备'])
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setMinimumHeight(170)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(W.QHeaderView.Fixed)
        for index,width in enumerate((46,58,180,80,84,110,86)):
            self.table.setColumnWidth(index,width)
        header.setSectionResizeMode(2,W.QHeaderView.Stretch)
        header.setMinimumSectionSize(40)
        self.table.itemChanged.connect(self.on_check)
        self.table.itemSelectionChanged.connect(self.show_detail)
        selection = W.QHBoxLayout()
        self.summary = text_label('')
        selection.addWidget(self.summary,1)
        selection.addWidget(self.button('勾选筛选结果',self.check_visible))
        selection.addWidget(self.button('清空勾选',self.clear_checked))
        selection.addWidget(self.button('评估记录',self.open_reports))
        self.details_toggle = W.QPushButton('文件详情')
        self.details_toggle.setCheckable(True)
        selection.addWidget(self.details_toggle)
        layout.addLayout(selection)
        layout.addWidget(self.table,1)
        self.detail = W.QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(135)
        self.detail.setMinimumHeight(110)
        self.detail.setPlaceholderText('点击一行查看通道、类别、数据质量和文件位置；勾选用于批量操作。')
        self.detail.hide()
        self.details_toggle.toggled.connect(self.detail.setVisible)
        layout.addWidget(self.detail)
        self.import_button = self.button('导入…',None)
        menu = W.QMenu(self.import_button)
        menu.addAction('导入数据 / 模型文件…',lambda:host.guard(self.import_files))
        menu.addAction('导入离线实验包文件夹…',lambda:host.guard(self.import_bundle))
        self.import_button.setMenu(menu)
        self.export_button = self.button('导出勾选…',self.export_files)
        self.bundle_button = self.button('导出离线实验包…',self.export_bundle)
        self.bundle_button.setToolTip('附带本机可找到的关联训练数据、文件校验和、版本清单与离线说明。源码与运行环境由教师另行提供。')
        self.train_button = self.button('用于训练',lambda:host.use_library('train',self.selected()))
        self.replay_button = self.button('用于回放',lambda:host.use_library('replay',self.selected()))
        self.model_button = self.button('使用模型',lambda:host.use_library('model',self.selected()))
        for button in (self.import_button,self.export_button,self.bundle_button):
            footer.addWidget(button)
        footer.addStretch()
        for button in (self.train_button,self.replay_button,self.model_button):
            footer.addWidget(button)
        for control in (self.kind,self.target,self.group,self.device,self.period):
            control.currentIndexChanged.connect(self.apply_filters)
        self.query.textChanged.connect(self.apply_filters)
        self.start.dateChanged.connect(self.apply_filters)
        self.end.dateChanged.connect(self.apply_filters)

    def button(self,text,action):
        button = W.QPushButton(text)
        button.setCursor(C.Qt.PointingHandCursor)
        if action:
            button.clicked.connect(lambda:self.host.guard(action))
        return button

    def open_reports(self):
        from .reports import ReportsDialog
        ReportsDialog(self.host,self.group.currentData() or '').exec()

    @staticmethod
    def combo(items):
        combo = W.QComboBox()
        for title,value in items:
            combo.addItem(title,value)
        return combo

    def refresh(self):
        self.entries = catalog.catalogue(self.host.session.root)
        for combo,key,title in ((self.group,'group','全部组别'),(self.device,'device','全部设备')):
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(title,'')
            for value in sorted({entry.meta.get(key,'') for entry in self.entries} - {''}):
                combo.addItem('模拟设备' if value=='模拟练习' else value,value)
            combo.setCurrentIndex(max(0,combo.findData(selected)))
            combo.blockSignals(False)
        self.apply_filters()

    def reset_filters(self):
        for control in (self.kind,self.target,self.group,self.device,self.period):
            control.blockSignals(True)
            control.setCurrentIndex(0)
            control.blockSignals(False)
        self.query.blockSignals(True)
        self.query.clear()
        self.query.blockSignals(False)
        self.apply_filters()

    def apply_filters(self):
        period = self.period.currentData()
        self.date_range.setVisible(period=='custom')
        start = end = None
        if period in ('week','month'):
            end = date.today()
            start = end-timedelta(days=6 if period=='week' else 29)
        elif period=='custom':
            start, end = self.start.date().toPython(), self.end.date().toPython()
        self.visible_entries = catalog.filter_entries(self.entries,query=self.query.text(),
            kind=self.kind.currentData(),target=self.target.currentData(),group=self.group.currentData(),
            device=self.device.currentData(),start=start,end=end)
        # Never leave invisible items selected for an export.
        self.checked &= {str(entry.path) for entry in self.visible_entries}
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.visible_entries))
        for row,entry in enumerate(self.visible_entries):
            values = ['', '数据' if entry.kind=='recording' else '模型',entry.meta['name'],
                      ('机器人' if entry.task.key=='robot' else '灵巧手')+f' {len(entry.task.classes)}类',entry.meta['group'],
                      entry.meta.get('created_at','')[:10], '模拟设备' if entry.meta.get('device')=='模拟练习' else entry.meta.get('device','')]
            for column,value in enumerate(values):
                item = W.QTableWidgetItem(value)
                item.setToolTip(catalog.describe(entry))
                if column==0:
                    item.setFlags(item.flags()|C.Qt.ItemIsUserCheckable)
                    item.setCheckState(C.Qt.Checked if str(entry.path) in self.checked else C.Qt.Unchecked)
                self.table.setItem(row,column,item)
        self.table.blockSignals(False)
        self.detail.clear()
        self.update_summary()
        if start and end and start>end:
            self.summary.setText('开始日期不能晚于结束日期。请调整日期范围。')

    def selected(self):
        return [entry for entry in self.visible_entries if str(entry.path) in self.checked]

    def on_check(self,item):
        if item.column()!=0 or item.row()>=len(self.visible_entries):
            return
        path = str(self.visible_entries[item.row()].path)
        if item.checkState()==C.Qt.Checked:
            self.checked.add(path)
        else:
            self.checked.discard(path)
        self.update_summary()

    def check_visible(self):
        self.checked = {str(e.path) for e in self.visible_entries}
        self.apply_filters()

    def clear_checked(self):
        self.checked.clear()
        self.apply_filters()

    def show_detail(self):
        row = self.table.currentRow()
        if 0<=row<len(self.visible_entries):
            self.detail.setPlainText(catalog.describe(self.visible_entries[row]))

    def set_idle(self,idle):
        self.idle = idle
        self.update_summary()

    def update_summary(self):
        selected = self.selected()
        self.summary.setText(f'共 {len(self.entries)} 项 · 筛选结果 {len(self.visible_entries)} 项 · 勾选 {len(selected)} 项'
                             + (' · 没有匹配文件，可重置筛选或导入文件。' if not self.visible_entries else ''))
        if not self.idle:
            self.summary.setText(self.summary.text()+' · 实验进行中，仅可浏览。')
        records = bool(selected) and all(e.kind=='recording' for e in selected)
        self.import_button.setEnabled(self.idle)
        for widget in (self.export_button,self.bundle_button):
            widget.setEnabled(self.idle and bool(selected))
        trainable = (records and len({e.task.task_type for e in selected})==1
                     and len({e.meta['group'] for e in selected})==1
                     and all(usable_record(e.meta) for e in selected))
        self.train_button.setEnabled(self.idle and trainable)
        self.train_button.setToolTip('请选择同一实验、同一组别且包含完整动作组的数据。')
        self.replay_button.setEnabled(self.idle and records and len(selected)==1)
        self.model_button.setEnabled(self.idle and len(selected)==1 and selected[0].kind=='model')

    def import_files(self):
        self.host.require_transfer_idle()
        paths,_ = W.QFileDialog.getOpenFileNames(self,'导入数据 / 模型（可多选）',self.host.last_transfer_folder,
            '数据与模型 (*.emg *.emgmodel *.onnx emg.bin);;所有文件 (*)')
        if paths:
            self.import_paths(paths)

    def import_paths(self,paths):
        self.host.require_transfer_idle()
        imported, errors, reused = [], [], 0
        for path in paths:
            try:
                result = catalog.import_file(path,self.host.session.root)
                imported.append(result.path)
                reused += int(result.reused)
            except Exception as exc:
                errors.append(f'{Path(path).name}：{exc}')
        if paths:
            self.host.last_transfer_folder = str(Path(paths[0]).parent)
        self.host.refresh_data()
        self.reset_filters()
        self.checked = {str(path) for path in imported}
        self.apply_filters()
        self.host.show_transfer_result('导入文件',imported,errors,reused=reused)

    def import_bundle(self):
        self.host.require_transfer_idle()
        folder = W.QFileDialog.getExistingDirectory(self,'选择包含 manifest.json 的离线实验包文件夹',self.host.last_transfer_folder)
        if folder:
            paths,_ = catalog.bundle_files(folder)
            self.import_paths(paths)

    def export_files(self):
        self.host.require_transfer_idle()
        selected = self.selected()
        if not selected:
            raise ValueError('请先勾选要导出的数据或模型。')
        destination = self.host.choose_export_folder()
        if not destination:
            return
        paths, errors = [], []
        for entry in selected:
            try:
                paths.append(catalog.export_entry(entry,destination))
            except Exception as exc:
                errors.append(f"{entry.meta['name']}：{exc}")
        self.host.show_transfer_result('导出文件',paths,errors,exported=True)

    def export_bundle(self):
        self.host.require_transfer_idle()
        if not self.selected():
            raise ValueError('请先勾选要带走的数据或模型。')
        destination = self.host.choose_export_folder()
        if destination:
            folder,manifest = catalog.export_bundle(self.selected(),self.entries,destination)
            count = len(manifest['files'])
            missing = len(manifest['missing_training_record_ids'])
            self.host.message(f'离线实验包已导出，共 {count} 项，缺少关联训练数据 {missing} 份。目录：{folder}')
            box = W.QMessageBox(self)
            box.setWindowTitle('离线实验包已导出')
            box.setText(f'已保存 {count} 项数据 / 模型及校验清单。\n缺少关联训练数据 {missing} 份。\n\n{folder}\n\n请同时发放同版本源码与资源包；本实验包不包含源码和运行环境。')
            box.addButton('完成',W.QMessageBox.AcceptRole)
            open_button = box.addButton('打开实验包',W.QMessageBox.ActionRole)
            box.exec()
            if box.clickedButton()==open_button:
                self.host.open_folder(folder)
