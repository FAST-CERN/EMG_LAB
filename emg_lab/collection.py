"""Small reusable notes and conservative signal checks for classroom capture."""
import numpy as np
from PySide6 import QtWidgets as W
from .storage import read_json,write_json

NOTE_FIELDS=('operator','wearing','channels','actions')

def clean_notes(notes):
    if notes is None:return {}
    if not isinstance(notes,dict):raise ValueError('采集记录格式不正确。')
    if not notes:return {}
    return {key:str(notes.get(key,'')).strip()[:2000] for key in NOTE_FIELDS}

def load_notes(root,group,task):
    path=root/'.capture_notes.json'
    try:return clean_notes(read_json(path).get(group,{}).get(task.selector,{}))
    except (OSError,ValueError,TypeError):return {}

def save_notes(root,group,task,notes):
    path=root/'.capture_notes.json'
    try:data=read_json(path)
    except (OSError,ValueError):data={}
    data.setdefault(group,{})[task.selector]=clean_notes(notes)
    write_json(path,data)

def signal_check(raw,rate,channel_ids,age):
    """Detect exact flatlines only; no universal amplitude threshold across devices."""
    if age>1.:return '信号已中断，请检查设备连接。',True
    needed=max(2,round(rate*2))
    if len(raw)<needed:return '正在检查信号，请先放松，再试做一次动作。',False
    values=np.asarray(raw[-needed:])
    flat=np.flatnonzero(np.ptp(values,axis=0)==0)
    if len(flat):
        channels='、'.join(str(channel_ids[i]) for i in flat)
        return f'传感器 {channels} 连续 2 秒数据完全不变，请检查传感器状态与波形。',True
    return '各通道数据正在变化；请试做动作并观察波形。此检查不代表标签或佩戴一定正确。',False

class CollectionNotesDialog(W.QDialog):
    def __init__(self,notes,task,parent=None):
        super().__init__(parent);self.setWindowTitle('采集记录 · 同一佩戴可沿用');self.resize(600,470)
        layout=W.QVBoxLayout(self)
        tip=W.QLabel('可选填写，随数据一起保存。换人、重新佩戴或改变动作时再更新。');tip.setWordWrap(True);layout.addWidget(tip)
        self.operator=W.QLineEdit(notes.get('operator',''));self.operator.setPlaceholderText('例如 P01，不用真实姓名')
        self.wearing=W.QLineEdit(notes.get('wearing',''));self.wearing.setPlaceholderText('例如 第1次佩戴；坐姿')
        self.channels=W.QPlainTextEdit(notes.get('channels',''));self.channels.setPlaceholderText('例如：1 左前臂；2 右前臂……');self.channels.setMaximumHeight(90)
        self.actions=W.QPlainTextEdit(notes.get('actions','') or '\n'.join(name+'：'+('放松 / 静息' if i==0 else '') for i,name in enumerate(task.names)))
        self.actions.setPlaceholderText('填写操作者实际做的肌肉动作，不是机器人动作本身')
        form=W.QFormLayout();form.addRow('操作者代号',self.operator);form.addRow('本次佩戴',self.wearing);form.addRow('通道位置',self.channels);form.addRow('动作约定',self.actions);layout.addLayout(form)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel)
        buttons.button(W.QDialogButtonBox.Save).setText('保存并沿用');buttons.button(W.QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def notes(self):
        return clean_notes(dict(operator=self.operator.text(),wearing=self.wearing.text(),channels=self.channels.toPlainText(),actions=self.actions.toPlainText()))
