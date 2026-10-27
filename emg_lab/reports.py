"""Find and export existing reports; does not recompute or rank results."""
from datetime import datetime
from pathlib import Path
import shutil,uuid
from PySide6 import QtCore as C,QtGui as G,QtWidgets as W
from .storage import read_json

def find_reports(root,group=''):
    root=Path(root);rows=[]
    for path in [*root.glob('*/evaluations/*.json'),*root.glob('*/competitions/*/result.json')]:
        try:
            report=read_json(path)
            coin=path.name=='result.json'
            html=path.with_name('report.html') if coin else path.with_suffix('.html')
            name=report.get('config',{}).get('group','') if coin else report.get('group','')
            if not html.is_file() or (group and group!=name):continue
            context=report.get('context',{}) if coin else report
            accuracy=report.get('command',{}).get('accuracy')
            result=(f"{report.get('count',0)}/{report.get('config',{}).get('count',0)} 枚 · {report.get('elapsed',0):.1f} s" if coin else
                    f'{accuracy:.1%}' if accuracy is not None else '无有效窗口')
            if not coin and not report.get('complete'):result+=' · 提前结束'
            rows.append(dict(path=path,html=html,group=name,model=context.get('model_id',''),
                kind='金币任务' if coin else '基础评估',result=result,
                date=datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),stamp=path.stat().st_mtime))
        except (OSError,ValueError,TypeError,KeyError):continue
    return sorted(rows,key=lambda r:r['stamp'],reverse=True)

def export_reports(rows,destination):
    if not rows:raise ValueError('请先选中要导出的报告。')
    output=Path(destination)/f'评估记录_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}'
    output.mkdir(exist_ok=False)
    for i,row in enumerate(rows,1):
        folder=output/f'{i:02d}';folder.mkdir()
        for path in (row['path'],row['html']):shutil.copy2(path,folder/path.name)
        trace=row['path'].with_name('commands.jsonl')
        if row['kind']=='金币任务' and trace.is_file():shutil.copy2(trace,folder/trace.name)
    (output/'阅读说明.txt').write_text('每个编号文件夹含一份 HTML 报告和原始 JSON。金币任务另附现有指令记录。\n这些是已保存的结果，未重新计分。不同数据、佩戴、速度档位的结果不能直接说明算法优劣。\n',encoding='utf-8')
    return output

class ReportsDialog(W.QDialog):
    def __init__(self,host,group=''):
        super().__init__(host);self.host=host;self.rows=find_reports(host.session.root,group)
        self.setWindowTitle('评估记录'+(' · '+group if group else ''));self.resize(960,560)
        layout=W.QVBoxLayout(self)
        tip=W.QLabel('选择记录后打开报告，或多选导出作为作业材料。比较算法时请使用相同测试条件。');tip.setWordWrap(True);layout.addWidget(tip)
        self.table=W.QTableWidget(len(self.rows),5)
        self.table.setHorizontalHeaderLabels(['日期','组别','类型','模型','结果'])
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows);self.table.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers);self.table.verticalHeader().hide();self.table.setAlternatingRowColors(True)
        for i,row in enumerate(self.rows):
            for j,key in enumerate(('date','group','kind','model','result')):
                item=W.QTableWidgetItem(str(row[key]));item.setToolTip(str(row[key]));self.table.setItem(i,j,item)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3,W.QHeaderView.Stretch)
        layout.addWidget(self.table)
        if not self.rows:layout.addWidget(W.QLabel('还没有评估记录。完成一次基础评估或金币任务后会自动保存在这里。'))
        self.message=W.QLabel('');self.message.setWordWrap(True);layout.addWidget(self.message)
        buttons=W.QHBoxLayout()
        for title,action in [('打开报告',self.open_report),('导出选中…',self.export),('关闭',self.close)]:
            button=W.QPushButton(title);button.clicked.connect(lambda checked=False,fn=action:self.guard(fn));buttons.addWidget(button)
        layout.addLayout(buttons);self.table.cellDoubleClicked.connect(lambda *_:self.guard(self.open_report))

    def guard(self,action):
        try:action()
        except Exception as error:self.message.setText(str(error))

    def selected(self):return [self.rows[i.row()] for i in self.table.selectionModel().selectedRows()]

    def open_report(self):
        selected=self.selected()
        if len(selected)!=1:raise ValueError('请选择一份报告打开；可按住 Ctrl 多选后导出。')
        G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(selected[0]['html'])))

    def export(self):
        selected=self.selected()
        if not selected:raise ValueError('请先选中要导出的记录。')
        folder=W.QFileDialog.getExistingDirectory(self,'选择导出文件夹',str(self.host.session.root))
        if folder:
            output=export_reports(selected,folder)
            self.message.setText('评估记录已导出到：'+str(output))
            G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(output)))
