"""A four-tab classroom workflow; all data processing lives outside widgets."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time
import uuid
from PySide6 import QtCore, QtGui, QtWidgets as W
from .engine import Session
from .collection import CollectionNotesDialog, load_notes, save_notes, signal_check
from .version import VERSION
from .evaluation import evaluation_text, evaluation_details
from .capture import PREPARE_SECONDS, ACTION_SECONDS, REST_SECONDS, preparation_countdown
from .processes import DeviceProcess, JsonProcess
from .robot import RobotScene, DdsBroadcast
from .signal import SignalConfig
from .waveform import WaveformPreview
from .tasks import ROBOT, HAND, ROBOT7, HAND5, TASKS, HAND_RATE, task_from_metadata, require_task
from .hand.scene import HandScene, HandView
from . import transfer
from .competition import RaceConfig, check_entry, file_hash, load_rules, REASONS
from .physics.commands import speed_summary
from .library import LibraryWidget
from .theme import apply_theme
from .widgets import card, field, fields, text_label
from .storage import ROOT, DATA_ROOT, CLASS_NAMES, list_recordings, list_models, record_label, read_json, write_json, safe_name, usable_record, recording_metadata


class Bridge(QtCore.QObject):
    device_event = QtCore.Signal(dict)
    train_event = QtCore.Signal(dict)


def label(text, title=False):
    item = W.QLabel(text)
    item.setWordWrap(True)
    if title:
        item.setObjectName('heading')
    return item


def button(text, action, primary=False):
    item = W.QPushButton(text)
    item.clicked.connect(action)
    item.setMinimumHeight(24)
    item.setCursor(QtCore.Qt.PointingHandCursor)
    if text.startswith(('停止','提前结束')):
        item.setObjectName('danger')
    if primary:
        item.setObjectName('primary')
    return item


def row(*items):
    layout = W.QHBoxLayout()
    layout.setSpacing(10)
    for item in items:
        if isinstance(item,str):
            text = label(item)
            text.setSizePolicy(W.QSizePolicy.Maximum,W.QSizePolicy.Preferred)
            layout.addWidget(text)
        elif isinstance(item,W.QWidget):
            layout.addWidget(item)
        else:
            layout.addStretch(item)
    return layout


def details(title):
    section = W.QWidget()
    layout = W.QVBoxLayout(section)
    layout.setContentsMargins(0,0,0,0)
    toggle = W.QToolButton()
    toggle.setText(title)
    toggle.setCheckable(True)
    toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    toggle.setArrowType(QtCore.Qt.RightArrow)
    content = W.QWidget()
    content.setVisible(False)
    toggle.toggled.connect(content.setVisible)
    toggle.toggled.connect(lambda checked:toggle.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow))
    layout.addWidget(toggle)
    layout.addWidget(content)
    section.toggle = toggle
    return section,W.QVBoxLayout(content)


def device_name(value):
    return '模拟设备' if value=='模拟练习' else value


def available_devices(platform_name=None):
    """真机设备仅 Windows 全功能档可见（ADR 0002）；其余平台只提供模拟练习。"""
    devices=[('Cometa','Cometa'),('Delsys','Delsys'),('模拟设备（无需硬件）','模拟练习')]
    return devices if (platform_name or sys.platform)=='win32' else [devices[-1]]


class MainWindow(W.QMainWindow):
    def __init__(self, data_root=DATA_ROOT):
        super().__init__()
        self.setWindowTitle('EMG Lab · 课堂实验 · '+VERSION)
        self.resize(1160,820)
        self.setMinimumSize(900,600)
        self.session = Session(data_root)
        self.task = ROBOT
        self.hand_output = None
        self.dds_output = None
        self.page_actions, self.page_scrolls = {}, {}
        self.page_titles, self.page_hints = {}, {}
        self.scene_pending = None
        self.scene = RobotScene(self)
        self.scene.ready.connect(self.finish_scene_start)
        self.scene.failed.connect(self.on_scene_error)
        self.scene.closed.connect(self.on_scene_closed)
        self.scene.competition_finished.connect(self.on_competition_finished)
        self.last_competition_path = None
        self.competition_token = None
        self._last_result_end = None
        self.device = self.training = None
        self.device_ready = False
        self.connecting = False
        self._last_cue = None
        self._dds_interface = None
        self.imported_records = {}
        self.imported_models = {}
        self.help_dialog = None
        self.last_transfer_folder = str(self.session.root)
        self._health_checked = 0.
        self.bridge = Bridge()
        self.bridge.device_event.connect(self.on_device)
        self.bridge.train_event.connect(self.on_train)
        self.stack = W.QStackedWidget()
        self.setCentralWidget(self.stack)
        self.make_choice()
        self.make_workspace()
        self.help_action = QtGui.QAction('帮助 / 操作教程', self)
        self.help_action.setShortcut(QtGui.QKeySequence('F1'))
        self.help_action.triggered.connect(lambda:self.guard(self.open_help))
        self.addAction(self.help_action)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.refresh_data()
        self.update_controls()

    def guard(self, action):
        try:
            return action()
        except Exception as exc:
            self.message(str(exc), error=True)
            return None

    def message(self, text, error=False):
        self.notice.setText(('提示：' if error else '')+str(text))
        self.notice.setProperty('tone','error' if error else 'info')
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)


    def make_choice(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(64,40,64,40)
        layout.setSpacing(16)
        layout.addLayout(row(text_label('EMG LAB', 'brand'),1,text_label('肌电 · 课堂实验', 'muted')))
        layout.addStretch(1)
        layout.addWidget(text_label('从肌肉信号，到动作控制', 'hero'))
        layout.addWidget(text_label('选择实验目标，按四个步骤完成采集、训练与实时控制。'))
        layout.addSpacing(12)
        choices = W.QHBoxLayout()
        choices.setSpacing(20)
        for key, number, title, description, tags in (
            ('robot','EXPERIMENT 01','机器人控制','学习用肌电信号控制机器人方向，观察动作识别与运动反馈。','前进 / 停止 / 左转 / 右转'),
            ('hand','EXPERIMENT 02','灵巧手控制','学习手部动作分类，在 3D 模拟中观察灵巧手的开合与停止。','张开 / 握合 / 停止')):
            panel, body = card()
            body.setContentsMargins(24,24,24,24)
            body.setSpacing(18)
            body.addWidget(text_label(number,'eyebrow'))
            body.addWidget(label(title,True))
            body.addWidget(text_label(description))
            body.addSpacing(6)
            body.addWidget(text_label(tags,'fieldLabel'))
            body.addStretch()
            body.addWidget(button('进入'+title+'  →',lambda checked=False,k=key:self.guard(lambda:self.select_task(k)),True))
            choices.addWidget(panel,1)
        layout.addLayout(choices)
        layout.addWidget(text_label('没有硬件也能开始：进入实验后选择“模拟设备”，即可体验完整流程。'))
        layout.addStretch(1)
        workflow = text_label('01 连接  →  02 采集  →  03 训练  →  04 使用')
        workflow.setWordWrap(False)
        layout.addLayout(row(button('操作教程  ·  F1',lambda:self.guard(self.open_help)),
                            button('开发技术文档',lambda:self.guard(lambda:self.open_help(1))),
                            button('数据与模型',lambda:self.guard(self.open_library)),1,workflow))
        self.stack.addWidget(page)

    def page(self, name, title, hint):
        widget = W.QWidget()
        widget.setObjectName('pageContent')
        layout = W.QVBoxLayout(widget)
        layout.setContentsMargins(24,20,24,20)
        layout.setSpacing(14)
        self.page_titles[name] = label(title,True)
        self.page_hints[name] = text_label(hint)
        layout.addWidget(self.page_titles[name])
        layout.addWidget(self.page_hints[name])
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.NoFrame)
        scroll.setWidget(widget)
        page = W.QWidget()
        outer = W.QVBoxLayout(page)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        outer.addWidget(scroll,1)
        actions = W.QFrame()
        actions.setObjectName('actionBar')
        footer = W.QHBoxLayout(actions)
        footer.setContentsMargins(24,12,24,12)
        outer.addWidget(actions)
        self.page_actions[name] = footer
        self.page_scrolls[name] = scroll
        self.tabs.addTab(page,name)
        return layout

    def reveal_activity(self, name, widget):
        """Focus the live feedback without collapsing or discarding its setup."""
        scroll = self.page_scrolls[name]
        def reveal():
            position = widget.mapTo(scroll.widget(), QtCore.QPoint(0,0)).y()
            scroll.verticalScrollBar().setValue(max(0,position-18))
        QtCore.QTimer.singleShot(0,reveal)


    def make_workspace(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        header_panel = W.QFrame()
        header_panel.setObjectName('header')
        header_layout = W.QHBoxLayout(header_panel)
        header_layout.setContentsMargins(24,14,24,14)
        self.workspace_header = text_label('EMG Lab  /  机器人控制','brand')
        self.workspace_header.setWordWrap(False)
        header_layout.addLayout(row(self.workspace_header,1,button('帮助  ·  F1',lambda:self.guard(self.open_help)),
                                    button('切换实验',lambda:self.guard(self.back_home))))
        layout.addWidget(header_panel)
        self.tabs = W.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.setUsesScrollButtons(False)
        layout.addWidget(self.tabs,1)
        self.notice = label('从“设备连接”开始，按页面顺序完成实验。')
        self.notice.setObjectName('notice')
        self.notice.setMinimumHeight(18)
        notice_layout = W.QVBoxLayout()
        notice_layout.setContentsMargins(16,8,16,8)
        notice_layout.addWidget(self.notice)
        layout.addLayout(notice_layout)
        self.make_device_page()
        self.make_capture_page()
        self.make_training_page()
        self.make_inference_page()
        self.make_library_page()
        self.tabs.currentChanged.connect(self.update_workspace_heading)
        for name in ('time_window','display','scale'):
            first,second=getattr(self.waveform,name),getattr(self.capture_waveform,name)
            first.currentIndexChanged.connect(second.setCurrentIndex)
            second.currentIndexChanged.connect(first.setCurrentIndex)
        self.waveform.fixed_limit.valueChanged.connect(self.capture_waveform.fixed_limit.setValue)
        self.capture_waveform.fixed_limit.valueChanged.connect(self.waveform.fixed_limit.setValue)
        self.stack.addWidget(page)


    def make_device_page(self):
        layout = self.page('01  设备连接','连接肌电设备','选择设备并填写传感器编号。没有硬件时，选择“模拟设备”即可开始。')
        panel, body = card('设备配置')
        self.device_combo = W.QComboBox()
        for text,value in available_devices():
            self.device_combo.addItem(text,value)
        self.device_combo.currentIndexChanged.connect(self.update_controls)
        self.channels = W.QLineEdit('1,2,3,4')
        self.channels.setPlaceholderText('例如 1,2,3,4；Delsys 使用配对编号')
        body.addLayout(fields(('肌电设备',self.device_combo),('传感器编号',self.channels)))
        self.scan_button = button('扫描传感器',lambda:self.guard(lambda:self.connect_device('scan')))
        self.pair_number = W.QSpinBox()
        self.pair_number.setRange(1,16)
        self.pair_button = button('配对传感器',lambda:self.guard(lambda:self.connect_device('pair')))
        self.delsys_panel = W.QWidget()
        self.delsys_panel.setLayout(row(self.scan_button,'配对编号',self.pair_number,self.pair_button,1))
        self.delsys_panel.layout().setContentsMargins(0,0,0,0)
        body.addWidget(self.delsys_panel)
        self.device_status = text_label('设备未连接','status')
        body.addWidget(self.device_status)
        self.bandpass = W.QCheckBox('带通滤波 · 滤除杂波')
        self.bandpass.setToolTip('带通 20–450 Hz；上限不超过采样率的 45%。')
        self.bandpass.setChecked(True)
        self.notch = W.QCheckBox('50 Hz 陷波 · 抑制电源干扰')
        self.notch.setToolTip('50 Hz 陷波。')
        self.notch.setChecked(True)
        self.bandpass.toggled.connect(lambda:self.guard(self.apply_filters))
        self.notch.toggled.connect(lambda:self.guard(self.apply_filters))
        body.addLayout(row(self.bandpass,self.notch,1,text_label('推荐保持开启')))
        layout.addWidget(panel)
        panel, body = card('实时波形')
        self.waveform = WaveformPreview()
        body.addWidget(self.waveform)
        self.device_health=text_label('连接后先观察波形，再开始采集。')
        body.addWidget(self.device_health)
        layout.addWidget(panel,1)
        self.connect_button = button('连接设备',lambda:self.guard(self.connect_device),True)
        self.disconnect_button = button('断开设备',self.disconnect_device)
        self.page_actions['01  设备连接'].addLayout(row(self.connect_button,self.disconnect_button,1,button('下一步：采集数据 →',lambda:self.tabs.setCurrentIndex(1))))


    def make_capture_page(self):
        layout = self.page('02  采集数据','跟随提示，采集动作数据','填写本次数据的名称与组别，再按屏幕提示完成动作。结束后自动保存。')
        self.capture_settings,settings = card('采集设置')
        layout.addWidget(self.capture_settings)
        self.task_choice = W.QComboBox()
        self.sync_capture_choices(self.task)
        self.task_choice.currentIndexChanged.connect(lambda:self.guard(lambda:self.choose_task(self.task_choice)))
        settings.addLayout(fields(('任务方案',self.task_choice)))
        settings.addWidget(text_label('先采基础类别，再扩展类别。方案决定采集标签和匹配的模型；切换机器人/灵巧手请用右上角“切换实验”。'))
        self.group = W.QLineEdit('G01')
        self.group.setMaxLength(40)
        self.experiment = W.QLineEdit('方向控制练习')
        self.experiment.setMaxLength(60)
        settings.addLayout(fields(('组别 / 学号',self.group),('数据名称',self.experiment)))
        self.group.textChanged.connect(self.name_preview)
        self.experiment.textChanged.connect(self.name_preview)
        self.trial_count = W.QSpinBox()
        self.trial_count.setRange(1,9999)
        self.trial_count.setValue(5)
        self.trial_count.setSuffix(' 组')
        self.action_seconds = W.QDoubleSpinBox()
        self.action_seconds.setRange(1,10)
        self.action_seconds.setValue(ACTION_SECONDS)
        self.action_seconds.setSuffix(' 秒')
        self.scene_check = W.QCheckBox('独立窗口显示机器人示范')
        self.scene_check.setChecked(True)
        self.scene_check.toggled.connect(self.update_hand_views)
        controls = fields(('动作组数',self.trial_count),('每个动作持续',self.action_seconds))
        controls.addWidget(self.scene_check,1,QtCore.Qt.AlignBottom)
        settings.addLayout(controls)
        self.random_order = W.QCheckBox('随机动作顺序')
        self.random_order.setToolTip('每组仍包含全部类别。先按固定顺序熟悉动作，再勾选随机采集。')
        settings.addWidget(self.random_order)
        self.collection_notes_button=button('采集记录…',lambda:self.guard(self.edit_collection_notes))
        settings.addLayout(row(self.collection_notes_button,text_label('选填操作者、通道位置与动作约定；同一佩戴可沿用，随数据一起带走。'),1))
        self.capture_plan = text_label('')
        settings.addWidget(self.capture_plan)
        self.trial_count.valueChanged.connect(self.update_capture_plan)
        self.action_seconds.valueChanged.connect(self.update_capture_plan)
        self.group.textChanged.connect(self.update_capture_plan)
        self.path_preview = text_label('')
        self.path_preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        storage_info,storage_body = details('保存位置与命名规则')
        storage_body.addWidget(self.path_preview)
        storage_body.addWidget(button('打开数据目录',lambda:self.open_folder(self.session.root)),0,QtCore.Qt.AlignLeft)
        settings.addWidget(storage_info)
        self.cue = label('准备就绪后，开始采集')
        self.cue.setObjectName('cueBanner')
        self.cue.setAlignment(QtCore.Qt.AlignCenter)
        self.cue.setMinimumHeight(44)
        layout.addWidget(self.cue)
        self.capture_progress = W.QProgressBar()
        self.capture_progress.setRange(0,1000)
        self.capture_progress.setValue(0)
        self.capture_progress.setFixedWidth(170)
        self.capture_status = text_label('准备时放松；动作提示出现后，完成助教约定的肌肉动作。')
        self.reject_trial_button=button('标记本组无效',lambda:self.guard(self.reject_current_trial))
        self.reject_trial_button.setToolTip('保留原始信号；训练和基础评估跳过这一组。结束后另采一组补足。')
        layout.addLayout(row(self.capture_status,self.capture_progress,self.reject_trial_button))
        panel, body = card('采集波形')
        self.capture_waveform = WaveformPreview(compact=True)
        body.addWidget(self.capture_waveform)
        self.capture_health=text_label('连接后先观察波形，再开始采集。')
        body.addWidget(self.capture_health)
        layout.addWidget(panel,1)
        self.capture_start = button('开始采集并保存',lambda:self.guard(self.start_capture),True)
        self.capture_stop = button('提前结束并保存',self.stop_capture)
        self.page_actions['02  采集数据'].addLayout(row(self.capture_start,self.capture_stop,1,button('下一步：训练模型 →',lambda:(self.refresh_data(),self.tabs.setCurrentIndex(2)))))
        self.name_preview()
        self.update_capture_plan()

    def update_capture_plan(self):
        count = self.trial_count.value()
        actions = len(self.task.classes)
        seconds = round(count*actions*(self.action_seconds.value()+PREPARE_SECONDS+REST_SECONDS))
        duration = f'{seconds//60} 分 {seconds%60} 秒' if seconds>=60 else f'{seconds} 秒'
        self.capture_plan.setText(f'本次共 {count} 组、{count*actions} 个动作，预计 {duration}。每个动作前准备 {PREPARE_SECONDS:g} 秒，完成后直接进入下一个动作的准备。')


    def make_training_page(self):
        layout = self.page('03  训练模型','让模型学习你的动作','勾选训练数据并填写模型名称。一份数据、一个完整动作组也能训练。')
        self.training_task_choice = W.QComboBox()
        self.training_task_choice.currentIndexChanged.connect(lambda:self.guard(lambda:self.choose_task(self.training_task_choice)))
        layout.addLayout(fields(('任务方案',self.training_task_choice)))
        self.train_task_classes = text_label('')
        layout.addWidget(self.train_task_classes)
        self.sync_capture_choices(self.task)
        setup = W.QHBoxLayout()
        setup.setSpacing(16)
        panel, body = card('训练数据')
        self.records = W.QListWidget()
        self.records.setMinimumHeight(130)
        self.records.setMaximumHeight(165)
        self.records.setWordWrap(True)
        self.records.setSpacing(2)
        body.addWidget(self.records,1)
        self.manage_data = button('数据管理 / 导入导出…',lambda:self.open_library('recording'))
        self.record_refresh = button('刷新列表',self.refresh_data)
        self.record_latest = button('选择最近一次采集',self.select_latest)
        body.addLayout(row(self.manage_data,1))
        body.addLayout(row(self.record_refresh,self.record_latest,1))
        self.record_summary = text_label('')
        body.addWidget(self.record_summary)
        self.records.itemChanged.connect(self.update_record_summary)
        setup.addWidget(panel,3)
        panel, body = card('模型设置')
        self.model_name = W.QLineEdit('方向分类模型')
        self.epochs = W.QSpinBox()
        self.epochs.setRange(1,200)
        self.epochs.setValue(30)
        self.epochs.setSuffix(' 遍')
        body.addWidget(field('模型名称',self.model_name))
        body.addWidget(field('学习遍数（Epochs）',self.epochs))
        body.addWidget(text_label('建议先使用默认 30 遍。训练结束后，模型会自动保存并出现在“使用模型”页。'))
        body.addStretch()
        setup.addWidget(panel,2)
        layout.addLayout(setup)
        panel, body = card('训练进度与结果')
        self.train_progress = W.QProgressBar()
        self.train_progress.setRange(0,1000)
        self.train_progress.setValue(0)
        body.addWidget(self.train_progress)
        self.train_status = text_label('等待开始。软件会自动安排训练和效果评估。')
        body.addWidget(self.train_status)
        self.training_result = W.QPlainTextEdit()
        self.training_result.setReadOnly(True)
        self.training_result.setMinimumHeight(150)
        self.training_result.setMaximumHeight(220)
        self.training_result.setPlaceholderText('训练完成后，查看模型保存位置、评估结果与下一步操作。')
        body.addWidget(self.training_result)
        explanation,extra = details('这些分数怎么计算？')
        extra.addWidget(text_label('窗口分类：取每个信号窗口中概率最大的类别，与动作标签比较。最终指令：连续回放数据，经过与实时推理相同的置信度和连续判定，再与标签比较。'))
        extra.addWidget(text_label('默认使用 0.5 秒窗口，每 0.1 秒推理一次；运动指令要求概率至少 65%，连续 3 次一致。只统计留出动作段内的完整窗口，并跳过每段开头 0.2 秒。窗口互相重叠，不是独立动作次数。'))
        body.addWidget(explanation)
        layout.addWidget(panel)
        self.train_start = button('开始训练',lambda:self.guard(self.start_training),True)
        self.train_stop = button('停止训练',self.stop_training)
        self.page_actions['03  训练模型'].addLayout(row(self.train_start,self.train_stop,1,button('下一步：使用模型 →',lambda:(self.refresh_data(),self.tabs.setCurrentIndex(3)))))

    def update_record_summary(self):
        total = self.records.count()
        checked = sum(self.records.item(i).checkState()==QtCore.Qt.Checked for i in range(total))
        self.record_summary.setText(f'共 {total} 份数据 · 已勾选 {checked} 份。导入导出统一在“数据与模型”页管理。'
                                    if total else '还没有数据。请先采集，或进入“数据与模型”导入已有文件。')


    def make_inference_page(self):
        page_layout = self.page('04  使用模型','用肌电控制机器人','选择模型和数据来源，再开始推理。当前配置始终保留在页面中。')
        self.infer_setup,layout = card('模型与数据来源')
        layout.setSpacing(8)
        self.inference_task_choice = W.QComboBox()
        self.inference_task_choice.currentIndexChanged.connect(lambda:self.guard(lambda:self.choose_task(self.inference_task_choice)))
        layout.addLayout(fields(('任务方案',self.inference_task_choice)))
        self.infer_task_classes = text_label('')
        layout.addWidget(self.infer_task_classes)
        self.sync_capture_choices(self.task)
        page_layout.addWidget(self.infer_setup)
        self.infer_context = text_label('','status')
        self.infer_context.hide()
        page_layout.addWidget(self.infer_context)
        self.models = W.QComboBox()
        self.models.setMinimumWidth(200)
        self.models.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.models.setMinimumContentsLength(16)
        self.models.setSizePolicy(W.QSizePolicy.Expanding,W.QSizePolicy.Fixed)
        self.models.currentIndexChanged.connect(self.model_details)
        self.manage_models = button('模型管理 / 导入导出…',lambda:self.open_library('model'))
        self.model_refresh = button('刷新',self.refresh_data)
        model_row = row(self.models,self.manage_models,self.model_refresh)
        layout.addLayout(model_row)
        self.model_summary = text_label('尚无模型，请先训练或导入。')
        layout.addWidget(self.model_summary)
        self.source = W.QComboBox()
        self.source.addItem('使用设备的实时信号','live')
        self.source.addItem('回放已采集的数据','replay')
        self.source.currentIndexChanged.connect(self.update_controls)
        self.replay_records = W.QComboBox()
        self.replay_records.setMinimumWidth(200)
        self.replay_records.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.replay_records.setMinimumContentsLength(16)
        self.replay_records.setSizePolicy(W.QSizePolicy.Expanding,W.QSizePolicy.Fixed)
        self.replay_field = field('回放数据',self.replay_records)
        source_fields = fields(('数据来源',self.source))
        source_fields.addWidget(self.replay_field,1)
        layout.addLayout(source_fields)
        self.replay_manage = button('选择回放数据 / 导入导出…',lambda:self.open_library('recording'))
        self.live_source_info = text_label('请先连接设备。')
        layout.addWidget(self.live_source_info)
        self.source_explanation = text_label('')
        layout.addWidget(self.source_explanation)
        self.practice_mode = W.QComboBox()
        self.practice_mode.addItem('自由练习','free')
        self.practice_mode.addItem('基础评估 · 实时提示 / 回放标签对照','assessment')
        self.practice_mode.addItem('金币任务 · 练习 / 正式比赛','coins')
        self.practice_mode.currentIndexChanged.connect(self.update_controls)
        layout.addLayout(fields(('练习方式',self.practice_mode)))
        self.practice_hint=text_label('自由练习：前进 → 停止 → 左转 → 前进 → 停止，观察转向后前进方向。')
        layout.addWidget(self.practice_hint)
        self.competition_panel,race_body = card('金币任务')
        self.race_group = W.QLineEdit('G01')
        self.race_group.setMaxLength(40)
        self.race_seed = W.QSpinBox()
        self.race_seed.setRange(0,2147483647)
        self.race_seed.setValue(20261025)
        self.race_count = W.QSpinBox()
        self.race_count.setRange(1,20)
        self.race_count.setValue(6)
        self.race_seconds = W.QSpinBox()
        self.race_seconds.setRange(20,600)
        self.race_seconds.setValue(120)
        self.race_seconds.setSuffix(' 秒')
        race_body.addLayout(fields(('参赛组别',self.race_group),('随机种子',self.race_seed)))
        race_body.addLayout(fields(('金币数',self.race_count),('整局限时',self.race_seconds)))
        self.race_official = W.QCheckBox('正式比赛：真实肌电、教师规定种子、程序校验')
        self.race_official.toggled.connect(lambda:self.guard(self.configure_competition))
        race_body.addWidget(self.race_official)
        self.race_rules_hint = text_label('固定分类：'+speed_summary()+'。所有模型统一榜单；连续/混合控制通过教师验收后可使用更高速度档，计时规则相同。')
        race_body.addWidget(self.race_rules_hint)
        self.race_result = text_label('每局自动保存成绩、路线、模型校验值与逐步控制记录；提前退出也留档。')
        race_body.addWidget(self.race_result)
        self.race_report = button('打开最近一局报告',self.open_competition_report)
        self.race_report.setEnabled(False)
        race_body.addLayout(row(self.race_report,button('比赛规则与教师操作',lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(ROOT/'docs/机器人金币任务说明.html')))),1))
        page_layout.addWidget(self.competition_panel)
        self.replay_actions = W.QWidget()
        self.replay_actions.setLayout(row(self.replay_manage,1))
        self.replay_actions.layout().setContentsMargins(0,0,0,0)
        layout.addWidget(self.replay_actions)
        self.infer_scene = W.QCheckBox('显示机器人练习场')
        self.infer_scene.setChecked(True)
        self.infer_scene.toggled.connect(self.update_hand_views)
        self.model_info = label('尚无模型，请先完成训练。')
        model_section,model_body = details('模型信息与评估详情')
        model_body.addWidget(self.model_info)
        layout.addLayout(row(self.infer_scene,1,model_section.toggle))
        layout.addWidget(model_section)
        model_section.hide()
        model_section.toggle.toggled.connect(model_section.setVisible)
        panel,body = card('实时识别')
        self.prediction = label('选择模型后，点击“开始推理”')
        self.prediction.setObjectName('prediction')
        self.prediction.setAlignment(QtCore.Qt.AlignCenter)
        self.prediction.setMinimumHeight(60)
        feedback_row = W.QHBoxLayout()
        result_panel = W.QWidget()
        result_layout = W.QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0,0,0,0)
        result_layout.setSpacing(10)
        result_layout.addWidget(self.prediction)
        feedback_row.addWidget(result_panel,1)
        self.probabilities = []
        probability_grid = self.probability_grid = W.QGridLayout()
        probability_grid.setSpacing(10)
        for i in range(max(len(task.classes) for task in TASKS.values())):
            name=self.task.names[i] if i<len(self.task.names) else ''
            bar = W.QProgressBar()
            bar.setRange(0,100)
            bar.setValue(0)
            bar.setFormat(name+'  %p%')
            bar.setVisible(i<4)
            probability_grid.addWidget(bar,i//2,i%2)
            self.probabilities.append(bar)
        result_layout.addLayout(probability_grid)
        self.infer_hand_view = HandView()
        self.infer_hand_view.setMinimumWidth(280)
        self.infer_hand_view.hide()
        feedback_row.addWidget(self.infer_hand_view,1)
        body.addLayout(feedback_row)
        self.infer_hand_feedback = text_label('')
        self.infer_hand_feedback.hide()
        body.addWidget(self.infer_hand_feedback)
        page_layout.addWidget(panel)
        self.assessment_panel,assessment_body = card('基础评估')
        self.assessment_cue = text_label('实时：按随机提示做动作；回放：与原始标签对照。','cueBanner')
        self.assessment_stats = text_label('仅评估模型预测，提示不会直接控制场景。')
        self.assessment_report = button('打开完整评估报告',self.open_assessment_report)
        self.assessment_report.setEnabled(False)
        assessment_body.addWidget(self.assessment_cue)
        assessment_body.addWidget(self.assessment_stats)
        assessment_body.addWidget(self.assessment_report,0,QtCore.Qt.AlignLeft)
        page_layout.insertWidget(page_layout.indexOf(panel),self.assessment_panel)
        self.mock_panel = W.QGroupBox('模拟设备体验')
        body = W.QVBoxLayout(self.mock_panel)
        body.addLayout(row('模拟输入的动作',self.mock_action_combo(),1))
        body.addWidget(text_label('推理开始后，切换动作来生成模拟信号，观察上方的识别结果。'))
        page_layout.addWidget(self.mock_panel)
        panel,body = card('真实设备输出')
        self.hardware_output_panel = panel
        body.addWidget(text_label('使用硬件实验时开启，由助教确认设备已就绪。'))
        self.hand_check = W.QCheckBox('使用真实灵巧手（达妙 USB）')
        self.hand_check.toggled.connect(self.update_controls)
        self.hand_connect = button('连接灵巧手',lambda:self.guard(self.connect_hand))
        self.hand_disconnect = button('断开',self.disconnect_hand)
        self.hand_panel = W.QWidget()
        self.hand_panel.setLayout(row(self.hand_check,1,self.hand_connect,self.hand_disconnect))
        self.hand_panel.layout().setContentsMargins(0,0,0,0)
        body.addWidget(self.hand_panel)
        self.hand_status = text_label('灵巧手未连接。连接后待机，开始推理才启用动作输出。')
        body.addWidget(self.hand_status)
        self.hand_feedback = label('连接后显示四指位置回读。')
        self.hand_details,hand_body = details('灵巧手状态详情')
        hand_body.addWidget(self.hand_feedback)
        body.addWidget(self.hand_details)
        self.dds_check = W.QCheckBox('使用真实机器人（DDS）')
        self.dds_check.toggled.connect(self.update_controls)
        self.domain = W.QSpinBox()
        self.domain.setRange(0,232)
        self.interface = W.QLineEdit()
        self.interface.setPlaceholderText('留空自动选择')
        self.dds_connect = button('连接机器人',lambda:self.guard(self.connect_dds))
        self.dds_disconnect = button('断开',self.disconnect_dds)
        self.dds_panel = W.QWidget()
        self.dds_panel.setLayout(row(self.dds_check,1,self.dds_connect,self.dds_disconnect))
        self.dds_panel.layout().setContentsMargins(0,0,0,0)
        body.addWidget(self.dds_panel)
        self.dds_status = text_label('机器人未连接。可在推理前连接，开始推理才发送指令。')
        body.addWidget(self.dds_status)
        self.dds_settings,extra = details('机器人连接设置（由助教设置）')
        extra.addLayout(fields(('DDS Domain',self.domain),('网卡名称',self.interface)))
        body.addWidget(self.dds_settings)
        page_layout.addWidget(panel)
        self.infer_start = button('开始推理',lambda:self.guard(self.start_inference),True)
        self.infer_stop = button('停止推理',self.stop_inference)
        self.infer_run_status = text_label('等待开始','status')
        self.page_actions['04  使用模型'].addLayout(row(self.infer_start,self.infer_stop,1,self.infer_run_status))
        page_layout.addStretch()


    def make_library_page(self):
        layout = self.page('数据与模型','管理课堂数据与模型','按组别、日期和实验目标查找文件，统一导入导出，再选择用于训练或离线回放。')
        self.library = LibraryWidget(self,self.page_actions['数据与模型'])
        layout.addWidget(self.library,1)

    def open_library(self,kind=None):
        self.library.refresh()
        self.library.reset_filters()
        if kind:
            self.library.kind.setCurrentIndex(self.library.kind.findData(kind))
            self.library.target.setCurrentIndex(self.library.target.findData(self.task.key))
        self.stack.setCurrentIndex(1)
        self.tabs.setCurrentIndex(4)
        self.page_scrolls['数据与模型'].verticalScrollBar().setValue(0)

    def update_workspace_heading(self):
        self.workspace_header.setText('EMG Lab  /  '+('数据与模型' if self.tabs.currentIndex()==4 else self.task.title))

    def use_library(self,action,entries):
        self.require_transfer_idle()
        if not entries:
            raise ValueError('请先勾选数据或模型。')
        if len({entry.task.task_type for entry in entries})!=1:
            raise ValueError('一次操作请选择同一个实验目标的文件。')
        if action=='train':
            from .signal import compatible_profile
            if any(entry.kind!='recording' or not usable_record(entry.meta) for entry in entries):
                raise ValueError('训练只能选择至少包含一组完整动作的数据。')
            first = entries[0].meta
            for entry in entries:
                compatible_profile(first,entry.meta)
                if first['group']!=entry.meta['group'] or first['preprocessing']!=entry.meta['preprocessing']:
                    raise ValueError('一次训练请选择同一组别、相同滤波设置的数据。')
        elif action=='replay':
            if len(entries)!=1 or entries[0].kind!='recording':
                raise ValueError('回放请选择一份数据。')
        elif action=='model':
            if len(entries)!=1 or entries[0].kind!='model':
                raise ValueError('请选择一个模型。')
        else:
            raise ValueError('未知的文件操作。')
        self.select_task(entries[0].task.selector)
        self.refresh_data()
        if action=='train':
            selected = {str(entry.path) for entry in entries}
            for i in range(self.records.count()):
                item = self.records.item(i)
                item.setCheckState(QtCore.Qt.Checked if item.data(QtCore.Qt.UserRole) in selected else QtCore.Qt.Unchecked)
            self.tabs.setCurrentIndex(2)
            self.message(f'已选择 {len(entries)} 份数据，请设置模型名称与学习遍数后开始训练。')
        else:
            combo = self.models if action=='model' else self.replay_records
            combo.setCurrentIndex(combo.findData(str(entries[0].path)))
            if action=='replay':
                self.source.setCurrentIndex(self.source.findData('replay'))
            self.tabs.setCurrentIndex(3)
            self.message('已选择模型。请确认数据来源后开始推理。' if action=='model'
                         else '已选择回放数据，请选择兼容模型。回放前需在设备连接页断开采集设备。')
        self.page_scrolls[self.tabs.tabText(self.tabs.currentIndex())].verticalScrollBar().setValue(0)

    def mock_action_combo(self):
        self.mock_action = W.QComboBox()
        self.mock_action.addItems(CLASS_NAMES)
        self.mock_action.currentIndexChanged.connect(lambda cue:self.guard(lambda:self.device.send('cue',cue=cue)) if self.device and not self.session.capture else None)
        return self.mock_action

    def name_preview(self):
        try:
            group,title = safe_name(self.group.text()),safe_name(self.experiment.text())
            self.path_preview.setText(f'将保存为一份“{title}”数据，归入 {group}。时间和文件编号自动添加。')
        except ValueError as exc:
            self.path_preview.setText(str(exc))

    def choose_task(self,choice):
        key=choice.currentData()
        if key is None: return
        try:
            self.select_task(key)
        finally:
            # If switching is refused during a run, the visible choices stay truthful.
            self.sync_capture_choices(self.task)

    def sync_capture_choices(self,task):
        captions={'robot':'基础四类','robot7':'扩展七类','hand':'基础开合三类','hand5':'预设姿态五类'}
        for attr in ('task_choice','training_task_choice','inference_task_choice'):
            choice=getattr(self,attr,None)
            if choice is None:continue
            choice.blockSignals(True);choice.clear()
            for key,candidate in TASKS.items():
                if candidate.key==task.key:
                    choice.addItem(captions.get(key,f'{candidate.title}（{len(candidate.classes)} 类）'),key)
            choice.setCurrentIndex(choice.findData(task.selector));choice.blockSignals(False)
        for attr in ('train_task_classes','infer_task_classes'):
            if hasattr(self,attr):
                getattr(self,attr).setText('类别：'+'、'.join(task.names)+'。三页方案同步，列表只显示匹配的数据与模型。')

    def select_task(self,key):
        if self.session.capture or self.session.inference or self.training or self.scene_pending:
            raise ValueError('请先结束当前实验，再切换目标。')
        task=TASKS[key]
        self.sync_capture_choices(task)
        if task != self.task:
            self.disconnect_hand()
            self.disconnect_dds()
            self.hand_check.setChecked(False)
            self.dds_check.setChecked(False)
            self.scene.stop()
            self.scene.deleteLater()
            self.task=self.session.task=task
            self.scene=HandScene(self,(self.infer_hand_view,),task=task) if task.key=='hand' else RobotScene(self)
            self.scene.ready.connect(self.finish_scene_start)
            self.scene.failed.connect(self.on_scene_error)
            self.scene.closed.connect(self.on_scene_closed)
            if task.key=='robot': self.scene.competition_finished.connect(self.on_competition_finished)
            if task.key=='hand': self.scene.changed.connect(self.hand_scene_status)
            self._last_result_end=None
            self.session.result=None
            self.session.last_assessment_path=None
            self.assessment_report.setEnabled(False)
            self.assessment_cue.setText('实时：按随机提示做动作；回放：与原始标签对照。')
            self.assessment_stats.setText('仅评估模型预测，提示不会直接控制场景。')
            self.update_workspace_heading()
            self.page_hints['02  采集数据'].setText('每次采集保存为一个数据文件。每组依次完成：'+ ' → '.join(task.names[i] for i in task.order)+'。停止用放松／静息打标。')
            self.page_titles['04  使用模型'].setText('用肌电控制'+('灵巧手' if task.key=='hand' else '机器人'))
            self.page_hints['04  使用模型'].setText('选择模型和数据来源，再开始推理。使用采集时相同的肌肉动作，观察模型输出与动作反馈。')
            self.experiment.setText('灵巧手控制练习' if task.key=='hand' else '方向控制练习')
            self.model_name.setText(task.title+'模型')
            self.scene_check.setText('独立窗口显示灵巧手示范' if task.key=='hand' else '独立窗口显示机器人示范')
            self.infer_scene.setText('显示灵巧手 3D 模拟' if task.key=='hand' else '显示机器人练习场')
            self.cue.setText('准备就绪后，开始采集')
            self.cue.setMinimumHeight(44)
            self.capture_status.setText('准备时放松；动作阶段按当前姿态提示完成约定的肌肉动作。3D 手为标签示范，不控制真机。' if task.key=='hand' else '准备时放松；动作提示出现后，完成助教约定的肌肉动作。')
            self.prediction.setText('选择模型后，点击“开始推理”')
            while len(self.probabilities)<len(task.classes):
                i=len(self.probabilities);bar=W.QProgressBar();bar.setRange(0,100)
                self.probability_grid.addWidget(bar,i//2,i%2);self.probabilities.append(bar)
            for i,bar in enumerate(self.probabilities):
                bar.setVisible(i<len(task.classes))
                bar.setValue(0)
                if i<len(task.classes): bar.setFormat(task.names[i]+'  %p%')
            self.mock_action.blockSignals(True)
            self.mock_action.clear(); self.mock_action.addItems(task.names)
            self.mock_action.blockSignals(False)
            if self.device: self.guard(lambda:self.device.send('cue',cue=0))
            self.training_result.clear()
            self.train_status.setText('请选择当前实验目标的数据进行训练。')
            self.refresh_data()
        self.update_capture_plan()
        self.update_hand_views()
        self.update_controls()
        self.stack.setCurrentIndex(1)

    def update_hand_views(self):
        if not hasattr(self,'infer_hand_view'): return
        hand=self.task.key=='hand'
        for widget in (self.infer_hand_view,self.infer_hand_feedback):
            widget.setVisible(hand and self.infer_scene.isChecked())

    def hand_scene_status(self,status):
        text=f"3D 模拟 · {self.task.names[status['command']]} · 开合 {status['progress']:.0f}% · 固定 {HAND_RATE} %/s · 拇指保持默认姿态"
        if self.task==HAND5:
            text=f"3D 预设姿态 · {self.task.names[status['command']]} · 平滑切换，停止保持当前位置"
        self.infer_hand_feedback.setText(text)

    def connect_hand(self):
        if self.task != HAND: raise ValueError('本版真机仅支持已接入的基础开合任务。')
        if self.hand_output: return
        from .hand.output import HandOutput
        output=self.hand_output=HandOutput(self)
        output.changed.connect(self.hand_status.setText)
        output.changed.connect(self.update_controls)
        output.failed.connect(self.hand_failed)
        output.sample.connect(lambda sample:self.hand_feedback.setText(f"四指位置回读（0–1000）：{sample['positions'][2:]}"))
        try:
            output.connect_hand()
        except Exception:
            self.disconnect_hand()
            raise
        self.update_controls()

    def disconnect_hand(self):
        if self.session.inference and self.hand_output and self.hand_output.enabled:
            self.stop_inference()
        output,self.hand_output=self.hand_output,None
        error=''
        if output:
            error=output.close(notify=False)
            output.deleteLater()
        self.hand_status.setText('连接已关闭；'+error if error else '灵巧手未连接。可先连接，再开始推理。')
        self.hand_feedback.setText('连接后显示四指位置回读。')
        if error: self.message(error,True)
        self.update_controls()

    def hand_failed(self,message):
        self.stop_inference()
        self.disconnect_hand()
        self.hand_status.setText('灵巧手连接异常：'+message)
        self.message(message,True)


    def back_home(self):
        if self.session.capture or self.session.inference or self.training or self.scene_pending:
            raise ValueError('请先结束当前实验，再切换目标。')
        self.stack.setCurrentIndex(0)

    def connect_device(self, action='connect'):
        if self.device or self.session.inference or self.session.capture or self.scene_pending:
            raise ValueError('请先停止任务并断开当前设备。')
        channels = sorted(set(int(x.strip()) for x in self.channels.text().replace('，',',').split(',') if x.strip()))
        if not channels or min(channels)<1 or max(channels)>16:
            raise ValueError('传感器编号应为 1–16，以逗号分隔。')
        device = self.device_combo.currentData()
        if action!='connect' and device!='Delsys':
            raise ValueError('请先将设备切换为 Delsys。')
        self.connecting = True
        self.device_status.setText('正在连接…' if action=='connect' else '正在扫描/配对，请按设备要求操作传感器…')
        self.device = DeviceProcess(dict(device=device,channel_ids=channels,action=action,pair_number=self.pair_number.value()),self.device_message)
        self.update_controls()

    def device_message(self, event):
        try:
            if event['type']=='connected':
                self.session.set_profile(event['profile'])
            elif event['type']=='frame':
                self.session.feed(event['samples'])
                with self.session.lock:
                    capture = self.session.capture
                    cue = capture.status().get('command',0) if capture else None
                if cue is not None and cue!=self._last_cue and self.device:
                    self.device.send('cue',cue=cue)
                    self._last_cue = cue
                return
            self.bridge.device_event.emit(event)
        except Exception as exc:
            self.bridge.device_event.emit(dict(type='error',message=str(exc),process_id=event.get('process_id')))

    def on_device(self, event):
        if not self.device or event.get('process_id') != self.device.process.pid:
            return
        kind = event['type']
        if kind=='connected':
            self.connecting = False
            self.device_ready = True
            p = event['profile']
            self.device_status.setText(f"{device_name(p['device'])} 已连接  ·  传感器 {p['channel_ids']}")
            self.device_status.setToolTip(f"采样率 {p['sampling_rate']:g} Hz；信号单位 {p['unit']}")
            self.waveform.set_profile(p)
            self.capture_waveform.set_profile(p)
            self.message('设备已连接。确认波形后，进入数据采集。')
        elif kind=='sensors':
            values = event['sensors']
            self.device_status.setText('扫描结果：'+'；'.join(f"#{s['pair_number']} {s['name']} [{s['mode']}]" for s in values))
            if values:
                self.channels.setText(','.join(str(s['pair_number']) for s in values))
        elif kind=='error':
            self.disconnect_device()
            self.message(event['message'],True)
        elif kind=='exited':
            if self.device_ready:
                self.disconnect_device()
                self.message('设备进程已退出。当前任务已停止。',True)
            else:
                self.device = None
                self.connecting = False
        self.update_controls()

    def disconnect_device(self):
        self.stop_capture()
        self.stop_inference()
        device,self.device = self.device,None
        if device:
            device.close()
        self.device_ready = self.connecting = False
        self.session.profile = None
        self.device_status.setText('设备未连接')
        self.update_controls()

    def apply_filters(self):
        self.session.set_filter(SignalConfig(bandpass=self.bandpass.isChecked(),notch=self.notch.isChecked()))

    def start_capture(self):
        if not self.device_ready:
            raise ValueError('请先连接设备。')
        if self.scene_check.isChecked():
            self.prepare_scene('sample', self.begin_capture)
        else:
            self.begin_capture()

    def prepare_scene(self, mode, action):
        if self.scene_pending or self.session.capture or self.session.inference:
            raise ValueError('请先结束当前实验。')
        self.scene_pending = (mode, action)
        self.message('正在载入灵巧手 3D 模型，完成后自动开始。' if self.task.key=='hand' else '正在准备机器人，站稳后自动开始。')
        self.update_controls()
        try:
            if self.task.key=='robot':
                self.scene.source = self.source.currentData()
            self.scene.start(mode)
        except Exception:
            self.scene_pending = None
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
        self.message(message + ' 已采集的数据会保存；可重新开始，或取消显示 3D 画面。', True)

    def on_scene_closed(self):
        self.stop_capture()
        self.stop_inference()
        self.scene.stop()

    def edit_collection_notes(self):
        group=self.group.text().strip()
        safe_name(group)
        dialog=CollectionNotesDialog(load_notes(self.session.root,group,self.task),self.task,self)
        if dialog.exec()==W.QDialog.Accepted:
            save_notes(self.session.root,group,self.task,dialog.notes())
            self.message('采集记录已保存；本组、当前采集方案下次会沿用。换人或重新佩戴后请更新。')

    def reject_current_trial(self):
        capture=self.session.capture
        if not capture or capture.completed:return
        trial=capture.status()['trial']
        reason,ok=W.QInputDialog.getItem(self,f'标记第 {trial} 组无效','原因（原始数据保留，稍后补采一组）',
                                      ['动作做错或没跟上','信号异常或传感器问题','疲劳 / 其他'],0,False)
        if ok:
            self.session.reject_capture_trial(capture,trial,reason)
            self.message(f'第 {trial} 组已标记无效，训练和基础评估会跳过。采集继续，结束后补采一组。')

    def begin_capture(self):
        try:
            self.session.start_capture(self.group.text(),self.experiment.text(),self.trial_count.value(),self.action_seconds.value(),random_order=self.random_order.isChecked(),collection_notes=load_notes(self.session.root,self.group.text().strip(),self.task))
        except Exception:
            self.scene.stop()
            raise
        self._last_cue = None
        self.message('采集中，请跟随动作提示；结束后会自动保存。')
        self.update_controls()
        self.reveal_activity('02  采集数据',self.cue)

    def stop_capture(self):
        if self.scene_pending and self.scene_pending[0] == 'sample':
            self.scene_pending = None
            self.scene.stop()
            self.message('已取消采集，尚未开始记录数据。')
            self.update_controls()
        if not self.session.capture:
            return
        capture = self.session.capture
        completed = capture.completed
        self.session.stop_capture()
        self.scene.stop()
        count = capture.writer.meta.get('usable_trials',capture.writer.meta['completed_trials'])
        rejected=len(capture.writer.meta.get('rejected_trials',[]))
        self.cue.setText('本次采集已完成' if completed else '本次采集已结束')
        self.capture_status.setText(f'已保存 1 个数据文件，可用 {count} 组动作。'+(f' 标记无效 {rejected} 组，请补采。' if rejected else ''))
        if self.device:
            self.guard(lambda:self.device.send('cue',cue=0))
        self.refresh_data()
        self.select_latest()
        self.message('数据已保存并选中，下一步进入“训练模型”。' if count else '数据已保存，但还没有完整的一组动作。请重新采集后再训练。')
        self.update_controls()

    def refresh_data(self):
        checked = {self.records.item(i).data(QtCore.Qt.UserRole) for i in range(self.records.count()) if self.records.item(i).checkState()==QtCore.Qt.Checked}
        current_record = self.replay_records.currentData()
        current_model = self.models.currentData()
        self.records.clear()
        self.replay_records.clear()
        all_records = dict(self.imported_records)
        all_records.update({str(p):m for p,m in list_recordings(self.session.root)})
        for path,meta in sorted(all_records.items(),key=lambda pair:pair[1].get('created_at',''),reverse=True):
            try: require_task(meta,self.task)
            except ValueError: continue
            self.add_record(path,meta,str(path) in checked)
            self.replay_records.addItem(record_label(meta),str(path))
        self.models.clear()
        all_models = dict(self.imported_models)
        all_models.update({str(p):m for p,m in list_models(self.session.root)})
        for path,meta in sorted(all_models.items(),key=lambda pair:pair[1].get('created_at',''),reverse=True):
            try: require_task(meta,self.task)
            except ValueError: continue
            self.models.addItem(f"{meta['name']} · {meta['group']} · {device_name(meta['device'])} · {meta['created_at'][:19].replace('T',' ')}",str(path))
        for combo,value in ((self.models,current_model),(self.replay_records,current_record)):
            i = combo.findData(value)
            if i>=0:
                combo.setCurrentIndex(i)
        self.model_details()
        self.update_record_summary()
        if hasattr(self,'library'):
            self.library.refresh()

    def add_record(self, path, meta, checked=False):
        item = W.QListWidgetItem(record_label(meta))
        item.setData(QtCore.Qt.UserRole,str(path))
        item.setToolTip(str(path))
        item.setFlags(item.flags()|QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked if checked and usable_record(meta) else QtCore.Qt.Unchecked)
        if not usable_record(meta):
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
        self.records.addItem(item)

    def select_latest(self):
        selected = None
        for i in range(self.records.count()):
            item = self.records.item(i)
            if selected is None and item.flags() & QtCore.Qt.ItemIsEnabled:
                selected = i
            item.setCheckState(QtCore.Qt.Checked if i==selected else QtCore.Qt.Unchecked)

    def choose_data(self):
        path,_ = W.QFileDialog.getOpenFileName(self,'选择采集的数据文件',str(self.session.root),'肌电数据 (*.emg);;旧版肌电数据 (emg.bin)')
        if path:
            return str(Path(path).parent) if Path(path).name=='emg.bin' else str(Path(path))
        return None

    def open_help(self, tab=0):
        if self.help_dialog is None:
            from .help import HelpDialog
            self.help_dialog = HelpDialog(self)
        self.help_dialog.tabs.setCurrentIndex(tab)
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def require_transfer_idle(self):
        if self.session.capture or self.session.inference or self.training or self.scene_pending:
            raise ValueError('请先结束采集、训练或推理，再导入或导出文件。')

    def show_transfer_result(self, title, paths, errors=(), *, exported=False, reused=0):
        text = f'{title}：成功 {len(paths)} 项'
        if reused:
            text += f'（其中 {reused} 项已存在，已重新选中）'
        if errors:
            text += f'；失败 {len(errors)} 项'
        if exported and paths:
            text += f'\n保存到：{Path(paths[0]).parent}'
        elif paths:
            text += '\n已保存在本机数据目录，重启后仍可使用。'
        self.message(text, error=bool(errors))
        if exported or errors:
            box = W.QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(W.QMessageBox.Warning if errors else W.QMessageBox.Information)
            box.setText(text)
            box.setDetailedText('\n'.join([*[str(p) for p in paths], *errors]))
            box.addButton(W.QMessageBox.Ok)
            open_button = box.addButton('打开导出文件夹',W.QMessageBox.ActionRole) if exported and paths else None
            box.exec()
            if open_button is not None and box.clickedButton() == open_button:
                self.open_folder(Path(paths[0]).parent)

    def choose_export_folder(self):
        selected = W.QFileDialog.getExistingDirectory(self,'选择导出到哪个文件夹',self.last_transfer_folder)
        if selected:
            self.last_transfer_folder = selected
        return selected

    def import_record(self):
        self.require_transfer_idle()
        selected,_ = W.QFileDialog.getOpenFileNames(self,'导入数据（可多选）',self.last_transfer_folder,
                                                    '肌电数据 (*.emg);;旧版肌电数据 (emg.bin)')
        if not selected:
            return
        paths, errors, reused = [], [], 0
        for source in selected:
            try:
                result = transfer.import_recording(source,self.session.root,self.task)
                paths.append(result.path)
                reused += result.reused
            except Exception as exc:
                errors.append(f'{Path(source).name}：{exc}')
        if paths:
            self.last_transfer_folder = str(Path(selected[0]).parent)
            self.refresh_data()
            for i in range(self.records.count()):
                item = self.records.item(i)
                checked = Path(item.data(QtCore.Qt.UserRole)) in paths and bool(item.flags() & QtCore.Qt.ItemIsEnabled)
                item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
            self.replay_records.setCurrentIndex(self.replay_records.findData(str(paths[-1])))
        self.show_transfer_result('导入数据',paths,errors,reused=reused)

    def export_records(self):
        self.require_transfer_idle()
        paths = [self.records.item(i).data(QtCore.Qt.UserRole) for i in range(self.records.count())
                 if self.records.item(i).checkState()==QtCore.Qt.Checked]
        if not paths:
            raise ValueError('请先勾选要导出的数据。')
        self.export_record_paths(paths)

    def export_record_paths(self, paths):
        destination = self.choose_export_folder()
        if not destination:
            return
        exported, errors = [], []
        for path in paths:
            try:
                exported.append(transfer.export_recording(path,destination,self.task))
            except Exception as exc:
                errors.append(f'{Path(path).name}：{exc}')
        self.show_transfer_result('导出数据',exported,errors,exported=True)

    def export_replay(self):
        self.require_transfer_idle()
        path = self.replay_records.currentData()
        if not path:
            raise ValueError('请先选择要导出的回放数据。')
        self.export_record_paths([path])

    def start_training(self):
        paths = [self.records.item(i).data(QtCore.Qt.UserRole) for i in range(self.records.count()) if self.records.item(i).checkState()==QtCore.Qt.Checked]
        if not paths:
            raise ValueError('请勾选要使用的数据，或点击“选择最近一次采集”。')
        safe_name(self.model_name.text())
        request = ROOT/'local'/f'train-{uuid.uuid4().hex}.json'
        write_json(request,dict(recordings=paths,name=self.model_name.text(),epochs=self.epochs.value(),data_root=str(self.session.root)))
        self.train_progress.setValue(0)
        self.training_result.clear()
        self.training = JsonProcess('emg_lab.train_worker',str(request),self.bridge.train_event.emit)
        self.update_controls()
        self.reveal_activity('03  训练模型',self.train_progress.parentWidget())

    def on_train(self, event):
        if not self.training or event.get('process_id') != self.training.process.pid:
            return
        if event['type']=='progress':
            self.train_progress.setValue(round(event['progress']*1000))
            self.train_status.setText(event['stage']+(f" · 验证窗口分类 {event['val_accuracy']:.1%}" if event.get('val_accuracy') is not None else ''))
        elif event['type']=='complete':
            self.train_progress.setValue(1000)
            m = event['metadata']
            self.training_result.setPlainText(f"模型“{m['name']}”已保存。\n{evaluation_details(m)}\n下一步：进入“使用模型”，这个模型已为你选好。")
            self.train_status.setText('训练完成。')
            self.refresh_data()
            self.models.setCurrentIndex(self.models.findData(event['path']))
            self.message('模型已保存，下一步进入“使用模型”。')
        elif event['type']=='error':
            self.train_status.setText('训练失败，详情见下方提示。')
            self.message(event['message'],True)
        elif event['type']=='exited':
            self.training = None
        self.update_controls()

    def stop_training(self):
        training,self.training = self.training,None
        if training:
            training.close()
            self.train_status.setText('训练已停止；不完整模型不会出现在推理列表。')
        self.update_controls()

    def model_details(self):
        path = self.models.currentData()
        if path:
            try:
                m = read_json(Path(path)/'metadata.json')
                self.model_summary.setText(f"{device_name(m['device'])} · 传感器 {m['channel_ids']} · {m.get('name', '已选择模型')}")
                self.model_info.setText(f"适用设备：{device_name(m['device'])} · 传感器 {m['channel_ids']}\n{evaluation_details(m)}")
            except (OSError,ValueError,KeyError):
                self.model_info.setText('模型信息不完整，请重新选择。')
                self.model_summary.setText('模型信息不完整，请重新选择。')
        else:
            self.model_info.setText('尚无模型，请先完成训练。')
            self.model_summary.setText('尚无模型，请先训练或导入。')

    def import_model(self):
        self.require_transfer_idle()
        selected,_ = W.QFileDialog.getOpenFileName(self,'导入模型包或 model.onnx',self.last_transfer_folder,
                                                  '模型包或 ONNX (*.emgmodel *.onnx);;模型包 (*.emgmodel);;原模型文件 (model.onnx)')
        if selected:
            result = transfer.import_model(selected,self.session.root,self.task)
            self.last_transfer_folder = str(Path(selected).parent)
            self.refresh_data()
            self.models.setCurrentIndex(self.models.findData(str(result.path)))
            self.show_transfer_result('导入模型',[result.path],reused=int(result.reused))

    def export_model(self):
        self.require_transfer_idle()
        path = self.models.currentData()
        if not path:
            raise ValueError('请先训练或选择一个模型。')
        destination = self.choose_export_folder()
        if destination:
            output = transfer.export_model(path,destination,self.task)
            self.show_transfer_result('导出模型',[output],exported=True)

    def import_replay(self):
        self.require_transfer_idle()
        path = self.choose_data()
        if path:
            result = transfer.import_recording(path,self.session.root,self.task)
            self.refresh_data()
            self.replay_records.setCurrentIndex(self.replay_records.findData(str(result.path)))
            self.source.setCurrentIndex(1)
            self.show_transfer_result('导入回放数据',[result.path],reused=int(result.reused))

    def start_inference(self):
        model = self.models.currentData()
        if not model:
            raise ValueError('请先选择模型。')
        source = self.source.currentData()
        if source=='replay' and self.device:
            raise ValueError('请先在“设备连接”页断开设备，再开始数据回放。')
        if source=='live' and not self.device_ready:
            raise ValueError('请先连接实时设备。')
        recording = self.replay_records.currentData()
        if source=='replay' and not recording:
            raise ValueError('请选择要回放的数据文件。')
        if self.task.key=='robot':
            self.scene.competition = None
        if self.practice_mode.currentData()=='coins':
            if self.task.key!='robot':
                raise ValueError('金币任务仅用于机器人。')
            if self.dds_check.isChecked():
                raise ValueError('金币比赛使用统一仿真，请关闭真机输出。')
            config=RaceConfig(seed=self.race_seed.value(),count=self.race_count.value(),limit_s=self.race_seconds.value(),
                              official=self.race_official.isChecked(),group=self.race_group.text())
            baseline=check_entry(config,source,self.session.profile)
            self.competition_token=uuid.uuid4().hex
            meta=read_json(Path(model)/'metadata.json')
            self.scene.competition=dict(config=config,data_root=self.session.root,context=dict(
                run_token=self.competition_token,model=str(Path(model).resolve()),model_id=meta['model_id'],
                model_hashes={name:file_hash(Path(model)/name) for name in ('model.onnx','metadata.json')},
                baseline_sha256=baseline,source=source,profile=self.session.profile if source=='live' else recording_metadata(recording),
                task_type=self.task.task_type,recording=str(recording) if source=='replay' else None))
            self.infer_scene.setChecked(True)
        self.check_real_output(source)
        if self.infer_scene.isChecked():
            self.prepare_scene('open', lambda: self.begin_inference(model, source, recording))
        else:
            self.begin_inference(model, source, recording)

    def begin_inference(self, model, source, recording):
        try:
            self.check_real_output(source)
            if self.practice_mode.currentData()=='assessment':
                self.session.start_inference(model,source,recording,assessment=True)
            else:
                self.session.start_inference(model,source,recording)
            if self.practice_mode.currentData()=='coins':
                self.scene.arm_competition()
            if self.task.key=='hand' and self.hand_check.isChecked():
                self.hand_output.enable(source,self.session.profile['device'])
            elif self.task.key=='robot' and self.dds_check.isChecked():
                self.dds_output.enable(source,self.session.profile['device'])
                with self.session.lock: self.session.dds=self.dds_output
                self.dds_status.setText('正在发送控制指令；请由助教确认机器人响应。')
        except Exception:
            self.stop_inference()
            self.scene.stop()
            raise
        self.assessment_report.setEnabled(False)
        self._last_result_end = None
        self.infer_context.setText('当前模型：'+self.models.currentText()+' · '+self.source.currentText())
        self.infer_context.hide()
        self.message('推理已开始，请观察当前指令和动作反馈。')
        self.update_controls()
        self.reveal_activity('04  使用模型',self.assessment_panel if self.practice_mode.currentData()=='assessment'
                             else self.prediction.parentWidget().parentWidget())

    def stop_inference(self, reason='aborted'):
        if not isinstance(reason,str): reason='aborted'  # QPushButton.clicked may supply a bool.
        if self.task.key=='robot':
            self.scene.end_competition(reason)
        if self.hand_output: self.hand_output.disable()
        with self.session.lock: self.session.dds=None
        if self.dds_output:
            try:
                self.dds_output.disable()
                self.dds_status.setText('DDS 已连接 · 待机，停止指令已发送。')
            except Exception as exc:
                self.dds_status.setText('停止发送未确认：'+str(exc))
                self.message(str(exc),True)
        if self.scene_pending and self.scene_pending[0] == 'open':
            self.scene_pending = None
            self.scene.stop()
            self.message('已取消推理。')
        active = self.session.inference is not None
        self.session.stop_inference()
        self.assessment_report.setEnabled(self.session.last_assessment_path is not None)
        if active:
            self.infer_context.hide()
            self.scene.stop()
            self.prediction.setText('推理已停止')
            self.message('推理已结束，预测结果已保存。')
        self.update_controls()

    def configure_competition(self):
        rules=load_rules()
        if self.race_official.isChecked():
            self.race_count.setValue(rules['count'])
            self.race_seconds.setValue(rules['limit_s'])
        self.race_rules_hint.setText('固定分类：'+speed_summary()+'。所有模型统一榜单。\n教师规定种子：'+ '、'.join(map(str,rules['official_seeds']))+'。正式比赛的模型与代码必须提前审核并固定。')
        self.update_controls()

    def on_competition_finished(self, path):
        self.last_competition_path=Path(path)
        report=read_json(self.last_competition_path.with_name('result.json'))
        if report['context'].get('run_token')==self.competition_token:
            self.stop_inference()
            self.competition_token=None
        self.race_report.setEnabled(True)
        result=f"{report['count']} / {report['config']['count']} 枚 · 计分用时 {report['scored_seconds']:.2f} 秒 · {REASONS.get(report['reason'],report['reason'])}"
        self.race_result.setText(result+'\n'+str(self.last_competition_path.parent))
        self.message('金币任务已保存：'+result)
        if self.task.key=='robot' and self.practice_mode.currentData()=='coins':
            self.reveal_activity('04  使用模型',self.competition_panel)

    def open_competition_report(self):
        if self.last_competition_path:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.last_competition_path.resolve())))

    def open_assessment_report(self):
        if self.session.last_assessment_path:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.session.last_assessment_path.resolve())))

    def check_real_output(self,source):
        selected=self.hand_check.isChecked() if self.task.key=='hand' else self.dds_check.isChecked()
        if not selected: return
        if self.task in (ROBOT7,HAND5):
            raise ValueError('扩展任务本版用于仿真与评估；新增动作尚未接机验证。请取消真机输出。')
        if source!='live' or not self.device_ready or self.session.profile['device'] not in ('Cometa','Delsys'):
            raise ValueError('真机输出需要真实肌电设备的实时信号；模拟和回放时请取消使用真机。')
        output=self.hand_output if self.task.key=='hand' else self.dds_output
        if not output or not output.connected:
            raise ValueError('请先连接输出设备，等待连接成功，再开始推理。')

    def connect_dds(self):
        if self.task != ROBOT: raise ValueError('本版 DDS 仅支持基础四类；七类请使用 MuJoCo。')
        if self.dds_output: return
        interface=self.interface.text().strip()
        identity=(self.domain.value(),interface)
        if self._dds_interface is not None and identity!=self._dds_interface:
            raise ValueError('DDS 参数已在本次运行中确定，修改后请重新启动应用。')
        output=DdsBroadcast(*identity)
        try:
            output.connect()
        except Exception:
            output.close()
            raise
        self.dds_output=output
        self._dds_interface=identity
        self.dds_status.setText('DDS 发布端已连接 · 待机；请由助教确认机器人端就绪。')
        self.update_controls()

    def disconnect_dds(self):
        if self.session.dds: self.stop_inference()
        output,self.dds_output=self.dds_output,None
        try:
            if output: output.close()
            self.dds_status.setText('机器人未连接。可先连接，再开始推理。')
        except Exception as exc:
            self.dds_status.setText('断开时发生异常：'+str(exc))
            self.message(str(exc),True)
        self.update_controls()


    def update_controls(self):
        if not hasattr(self,'infer_start'):
            return
        capture = self.session.capture is not None
        inference = self.session.inference is not None
        training = self.training is not None
        pending = self.scene_pending[0] if self.scene_pending else None
        task = capture or inference or training or pending is not None
        coin_index=self.practice_mode.findData('coins')
        self.practice_mode.model().item(coin_index).setEnabled(self.task.key=='robot')
        if self.task.key!='robot' and self.practice_mode.currentData()=='coins':
            self.practice_mode.setCurrentIndex(0)
        coins=self.practice_mode.currentData()=='coins'
        self.hardware_output_panel.setVisible(not coins)
        self.competition_panel.setVisible(coins)
        for widget in (self.race_group,self.race_seed,self.race_official):
            widget.setEnabled(not task)
        for widget in (self.race_count,self.race_seconds):
            widget.setEnabled(not task and not self.race_official.isChecked())
        replay = self.source.currentData()=='replay'
        for widget in (self.device_combo,self.channels,self.scan_button,self.pair_button,self.pair_number):
            widget.setEnabled(not self.device and not task)
        self.connect_button.setEnabled(not self.device and not task)
        self.disconnect_button.setEnabled(self.device is not None)
        for widget in (self.bandpass,self.notch):
            widget.setEnabled(not task)
        for widget in (self.group,self.experiment,self.trial_count,self.action_seconds,self.scene_check,self.random_order,self.task_choice,self.training_task_choice,self.inference_task_choice,self.collection_notes_button):
            widget.setEnabled(not task)
        self.capture_start.setEnabled(self.device_ready and not task)
        self.capture_stop.setEnabled(capture or pending == 'sample')
        self.reject_trial_button.setEnabled(bool(capture))
        for widget in (self.records,self.model_name,self.epochs,self.record_refresh,self.record_latest):
            widget.setEnabled(not task)
        self.train_start.setEnabled(not task)
        self.train_stop.setEnabled(training)
        for widget in (self.source,self.models,self.infer_scene,self.model_refresh,self.practice_mode):
            widget.setEnabled(not task)
        if coins:
            self.infer_scene.setChecked(True)
            self.infer_scene.setEnabled(False)
            self.dds_check.setChecked(False)
        self.assessment_panel.setVisible(self.practice_mode.currentData()=='assessment')
        self.practice_hint.setText(
            '金币任务：相同种子生成相同完整路线。练习支持实时与回放；正式成绩只接受真实肌电实时控制。'
            if coins else
            '基础评估：实时随机提示共 2 轮，每次准备 3 秒、动作 3 秒；回放按文件原标签对照。先另采一轮数据再评估。'
            if self.practice_mode.currentData()=='assessment' else
            '自由练习：张开 → 停止保持 → 握拳 → 食指指向 → 双指伸展；中途放松，检查是否立即停止。'
            if self.task==HAND5 else
            '自由练习：张开 → 停止保持 → 握合 → 停止保持，试着停在不同开合位置。'
            if self.task.key=='hand' else
            '自由练习：前进 → 停止 → 左转 → 前进 → 停止；七类还可练习后退和左右侧移。')
        self.replay_records.setEnabled(not task and replay)
        self.replay_field.setVisible(replay)
        self.replay_actions.setVisible(replay)
        self.live_source_info.setVisible(not replay)
        self.source_explanation.setText('离线回放：原始肌电重新经过模型解码，标签只用于评估；与实时推理共用同一模拟场景。'
                                       if replay else '实时推理：设备肌电经过模型解码后驱动模拟场景；可选择自由练习、基础评估或金币任务。'
                                       if self.task.key=='robot' else '实时推理：设备肌电经过模型解码，控制当前任务的手部动作或姿态。')
        if hasattr(self,'library'):
            self.library.set_idle(not task)
        if self.device_ready and self.session.profile:
            p = self.session.profile
            self.live_source_info.setText(f"当前设备：{device_name(p['device'])} · 传感器 {p['channel_ids']}")
        else:
            self.live_source_info.setText('请先在设备连接页选择设备和传感器。')
        self.infer_start.setEnabled(not task)
        self.infer_stop.setEnabled(inference or pending == 'open')
        hand=self.task.key=='hand'
        self.hand_panel.setVisible(hand)
        self.hand_status.setVisible(hand)
        self.hand_details.setVisible(hand)
        self.dds_panel.setVisible(not hand and not coins)
        self.dds_status.setVisible(not hand and not coins)
        self.dds_settings.setVisible(not hand and not coins)
        self.hand_check.setEnabled(not task and self.task==HAND)
        self.dds_check.setEnabled(not task and self.task==ROBOT and not coins)
        self.hand_connect.setEnabled(hand and self.hand_check.isChecked() and self.hand_output is None and not task)
        self.hand_disconnect.setEnabled(self.hand_output is not None and not task)
        self.dds_connect.setEnabled(not hand and self.dds_check.isChecked() and self.dds_output is None and not task)
        self.dds_disconnect.setEnabled(self.dds_output is not None and not task)
        self.domain.setEnabled(self.dds_output is None and not task)
        self.interface.setEnabled(self.dds_output is None and not task)
        self.mock_action.setEnabled(inference and self.device_ready and self.session.profile['device']=='模拟练习')
        simulated = self.device_ready and self.session.profile and self.session.profile['device']=='模拟练习'
        self.mock_panel.setVisible(bool(simulated and not replay))
        self.delsys_panel.setVisible(self.device_combo.currentData()=='Delsys')
        self.device_status.setProperty('connected',self.device_ready)
        self.device_status.style().unpolish(self.device_status)
        self.device_status.style().polish(self.device_status)
        self.update_record_summary()
        self.infer_run_status.setText('推理中' if inference else '准备场景…' if pending=='open' else '等待开始')
        self.hand_check.setToolTip('五类姿态目前只做 3D 验证；基础三类可连接真机。' if self.task==HAND5 else '可在推理前连接；只有真实肌电的实时推理才会启用动作。')
        self.dds_check.setToolTip('七类目前用于 MuJoCo，DDS 仍使用原有四类协议。' if self.task==ROBOT7 else '可在推理前连接；只有真实肌电的实时推理才会发送控制指令。')

    def tick(self):
        snapshot = self.session.snapshot()
        if self.device_ready and snapshot['profile'] and self.tabs.currentIndex() in (0,1):
            preview=self.waveform if self.tabs.currentIndex()==0 else self.capture_waveform
            preview.update_data(snapshot['raw'], snapshot['filtered'], snapshot['profile']['sampling_rate'])
        if time.monotonic()-self._health_checked>=1.:
            self._health_checked=time.monotonic()
            text,warning=('未连接设备。',False)
            if self.device_ready and snapshot['profile']:
                p=snapshot['profile']
                text,warning=signal_check(snapshot['raw'],p['sampling_rate'],p['channel_ids'],time.monotonic()-snapshot['last_frame'])
            for widget in (self.device_health,self.capture_health):
                widget.setText(text)
                widget.setStyleSheet('color:#a33b21;font-weight:600;' if warning else '')
        status = snapshot['capture']
        self.reject_trial_button.setEnabled(bool(status and not status['done'] and not status.get('rejected')))
        if status:
            self.scene.sample(status)
            self.capture_progress.setValue(round(status['progress']*1000))
            if status['done']:
                self.stop_capture()
            else:
                action = self.task.names[status['cue']]
                if status['phase'] == '准备':
                    name = '休息' if status['cue'] == 0 else action
                    self.cue.setText(f'准备：{name}  {preparation_countdown(status)}')
                elif status['phase'] == '动作':
                    self.cue.setText(('停止 · 放松肌肉' if status['cue']==0 else action) if self.task.key=='hand' else action)
                else:
                    self.cue.setText('休息，放松肌肉')
                self.capture_status.setText(f"第 {status['trial']} / {status['trial_count']} 组 · 第 {status['action_index']} / {len(self.task.classes)} 个动作 · 剩余 {status['remaining']:.1f} 秒" + (' · 保持动作直到倒计时结束' if status['phase']=='动作' and status['cue'] else ' · 放松肌肉')+(' · 本组已标记无效' if status.get('rejected') else ''))
        assessment=snapshot.get('assessment')
        if assessment:
            target=assessment['target']
            cue='评估结束' if target is None else f"{assessment['phase']}：{self.task.names[target]}  {assessment['remaining']:.1f} 秒"
            self.assessment_cue.setText(cue)
            score='等待完整动作窗口' if assessment['accuracy'] is None else f"最终指令正确率 {assessment['accuracy']:.1%} · {assessment['correct']} / {assessment['total']} 个有效窗口"
            self.assessment_stats.setText(score+'；提示仅作对照，不驱动动作。')
            if assessment['done']:
                self.stop_inference()
                self.message('基础评估完成，点击“打开完整评估报告”查看各类别结果与混淆矩阵。')
                return
        result = snapshot['result']
        if snapshot['inferencing'] and result:
            self.prediction.setText(f"当前指令：{self.task.names[result['filtered_class']]}")
            for bar,p in zip(self.probabilities,result['probabilities']):
                bar.setValue(round(p*100))
            if result['sample_end'] != self._last_result_end:
                self.scene.command(result['filtered_class'])
                if self.hand_output: self.hand_output.update(result)
                self._last_result_end = result['sample_end']
        if snapshot['inferencing'] and snapshot['source']=='replay' and snapshot['replay_done']:
            self.stop_inference('replay_finished')
            self.message(self.session.error or '数据回放完成，预测结果已保存。',bool(self.session.error))
        elif (status or snapshot['inferencing']) and time.monotonic()-snapshot['last_frame']>1.:
            self.stop_capture()
            self.stop_inference('signal_lost')
            self.message('肌电信号已中断，实验已停止。请检查设备连接后重新开始。',True)
        if self.session.dds and self.session.dds.error:
            error = self.session.dds.error
            self.stop_inference()
            self.disconnect_dds()
            self.message(error,True)

    def open_folder(self,path):
        Path(path).mkdir(parents=True,exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def closeEvent(self,event):
        self.timer.stop()
        self.stop_training()
        self.disconnect_device()
        self.disconnect_hand()
        self.disconnect_dds()
        self.scene.stop()
        self.session.close()
        event.accept()


def configure_app(app):
    apply_theme(app)


def main():
    app = W.QApplication(sys.argv)
    configure_app(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__=='__main__':
    sys.exit(main())
