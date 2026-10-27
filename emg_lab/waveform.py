"""Two-column EMG plots, following the research host's waveform debug page."""
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore as C, QtWidgets as W
from .widgets import field


class ChannelPlot(pg.PlotWidget):
    def sizeHint(self):
        # Keep four channels visible on a classroom laptop; more rows scroll normally.
        return C.QSize(360, self.minimumHeight() or 168)


class AmplitudeLimit(W.QDoubleSpinBox):
    def textFromValue(self, value):
        return f'{value:.9f}'.rstrip('0').rstrip('.')


class WaveformPreview(W.QWidget):
    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.profile = None
        self.snapshot = None
        self.paused = False
        self.auto_limit = 1.
        self.plot_height = 128 if compact else 168
        self.plots, self.raw_curves, self.filtered_curves = [], [], []
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        controls = W.QHBoxLayout()
        self.time_window = W.QComboBox()
        for seconds in (1, 3, 5, 10):
            self.time_window.addItem(f'{seconds} 秒', seconds)
        self.time_window.setCurrentIndex(1)
        self.display = W.QComboBox()
        for text, value in [('滤波后', 'filtered'), ('原始信号', 'raw'), ('原始 + 滤波', 'both')]:
            self.display.addItem(text, value)
        self.scale = W.QComboBox()
        for text, value in [('统一自动', 'shared'), ('各通道自动', 'individual'), ('固定范围', 'fixed')]:
            self.scale.addItem(text, value)
        self.scale.setCurrentIndex(self.scale.findData('fixed'))
        self.fixed_limit = AmplitudeLimit()
        self.fixed_limit.setDecimals(9)
        self.fixed_limit.setRange(1e-9, 1e9)
        self.fixed_limit.setValue(1.)
        self.fixed_limit.setPrefix('± ')
        self.fixed_limit.setKeyboardTracking(False)
        self.fixed_limit.setToolTip('所有通道共用的纵轴上下限，单位与图中一致。')
        self.pause = W.QPushButton('暂停画面')
        self.pause.setCheckable(True)
        self.pause.setToolTip('只暂停画面，设备收数和数据保存继续进行。')

        for title, control in (('时间窗口',self.time_window),('显示内容',self.display),('纵轴范围',self.scale),('固定幅值',self.fixed_limit)):
            if control is self.fixed_limit:
                self.limit_field = field(title,control)
                controls.addWidget(self.limit_field,1)
            else:
                controls.addWidget(field(title,control),1)
        controls.setSpacing(12)
        controls.addWidget(self.pause,0,C.Qt.AlignBottom)
        layout.addLayout(controls)
        self.grid = W.QGridLayout()
        self.grid.setSpacing(10)
        layout.addLayout(self.grid, 1)
        self.hint = W.QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName('muted')
        layout.addWidget(self.hint)
        self.empty = W.QLabel('等待设备信号\n\n连接设备后，实时波形将在这里显示。')
        self.empty.setMinimumHeight(180)
        self.empty.setObjectName('emptyState')
        self.empty.setAlignment(C.Qt.AlignCenter)
        self.grid.addWidget(self.empty, 0, 0)
        self.time_window.currentIndexChanged.connect(self.render)
        self.display.currentIndexChanged.connect(self.render)
        self.scale.currentIndexChanged.connect(self._scale_changed)
        self.fixed_limit.valueChanged.connect(self.render)
        self.pause.toggled.connect(self._pause_changed)
        self.render()

    def set_profile(self, profile):
        self.profile = dict(profile)
        self.snapshot = None
        self.pause.setChecked(False)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.plots, self.raw_curves, self.filtered_curves = [], [], []
        unit = profile.get('unit', 'SDK raw')
        unit_label = {'a.u.': '模拟单位', 'SDK raw': '设备原始单位'}.get(unit, unit)
        for index, channel in enumerate(profile['channel_ids']):
            plot = ChannelPlot(background='white')
            plot.setMinimumHeight(self.plot_height)
            plot.setTitle(f'CH {channel}', color='#223443', size='11pt')
            plot.setLabel('left', f'幅值（{unit_label}）')
            plot.setLabel('bottom', '时间', units='s')
            plot.getAxis('left').enableAutoSIPrefix(False)
            for name in ('left', 'bottom'):
                plot.getAxis(name).setPen('#97a8b2')
                plot.getAxis(name).setTextPen('#55636f')
            plot.showGrid(x=True, y=True, alpha=.12)
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.setMouseEnabled(x=False, y=False)
            plot.enableAutoRange(x=False, y=False)
            raw = plot.plot(pen=pg.mkPen('#aab5bf', width=1))
            filtered = plot.plot(pen=pg.mkPen('#3563e9', width=1))
            for curve in (raw, filtered):
                # Peak downsampling preserves spikes; it only changes drawing, not saved EMG.
                curve.setDownsampling(auto=True, method='peak')
                curve.setClipToView(True)
            self.grid.addWidget(plot, index // 2, index % 2)
            self.plots.append(plot)
            self.raw_curves.append(raw)
            self.filtered_curves.append(filtered)
        self.render()

    def update_data(self, raw, filtered, rate):
        if not self.paused:
            self.snapshot = (raw, filtered, rate)
            self.render()

    def _pause_changed(self, paused):
        self.paused = paused
        self.pause.setText('继续画面' if paused else '暂停画面')
        self.render()

    def _scale_changed(self):
        fixed = self.scale.currentData() == 'fixed'
        self.limit_field.setEnabled(fixed)
        self.render()

    def render(self):
        seconds = self.time_window.currentData()
        display, scale = self.display.currentData(), self.scale.currentData()
        labels = {'filtered': '蓝色：滤波后信号。', 'raw': '灰色：原始信号。',
                  'both': '灰色：原始信号；蓝色：滤波后信号。'}
        self.hint.setText(('画面已暂停，设备仍在收数。' if self.paused else '') + labels[display] +
                         ('各通道纵轴独立缩放，请结合刻度判断幅值。' if scale == 'individual'
                          else '各通道共用纵轴范围，可观察信号强弱差异。'))
        for plot, a, b in zip(self.plots, self.raw_curves, self.filtered_curves):
            plot.setXRange(-seconds, 0., padding=0)
            a.setVisible(display != 'filtered')
            b.setVisible(display != 'raw')
        if scale == 'fixed':
            for plot in self.plots:
                plot.setYRange(-self.fixed_limit.value(), self.fixed_limit.value(), padding=0)
        if self.snapshot is None:
            return
        raw, filtered, rate = self.snapshot
        count = min(len(raw), round(seconds*rate))
        if count == 0:
            for curve in (*self.raw_curves, *self.filtered_curves):
                curve.setData([], [])
            return
        raw, filtered = raw[-count:], filtered[-count:]
        t = np.arange(1-count, 1)/rate
        values = [raw] if display == 'raw' else [filtered] if display == 'filtered' else [raw, filtered]
        limits = np.maximum.reduce([np.max(np.abs(x), axis=0) for x in values])*1.1
        limits = np.maximum(limits, 1e-9)
        self.auto_limit = float(limits.max())
        for i, (plot, a, b) in enumerate(zip(self.plots, self.raw_curves, self.filtered_curves)):
            a.setData(t, raw[:, i])
            b.setData(t, filtered[:, i])
            limit = self.fixed_limit.value() if scale == 'fixed' else float(limits[i]) if scale == 'individual' else self.auto_limit
            plot.setYRange(-limit, limit, padding=0)
