"""Student scene shared by cue-driven collection and classifier-driven practice."""
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from .commands import Command, CommandSettings, NAMES, speed_summary
from .worker import SimulationWorker
from ..competition import REASONS, AREA_LIMIT
import math


class RaceMap(W.QWidget):
    """World overview keeps the next target findable outside the chase camera."""
    def __init__(self):
        super().__init__()
        self.status = None
        self.setFixedSize(174,174)

    def set_status(self, status):
        self.status = status
        self.update()

    def paintEvent(self, event):
        p = G.QPainter(self)
        p.setRenderHint(G.QPainter.Antialiasing)
        p.fillRect(self.rect(),G.QColor('#edf3f8'))
        p.setPen(G.QPen(G.QColor('#c6d2df'),1))
        p.drawRect(9,9,156,156)
        def xy(pos):
            return C.QPointF(87-pos[1]*78/AREA_LIMIT,87-pos[0]*78/AREA_LIMIT)
        p.drawLine(87,9,87,165)
        p.drawLine(9,87,165,87)
        if not self.status or 'race' not in self.status: return
        race=self.status['race']
        p.setPen(C.Qt.NoPen)
        p.setBrush(G.QColor('#94a5b6'))
        for item in race['collected']:
            p.drawEllipse(xy(race['route'][item['index']-1]),3,3)
        if race['target'] is not None:
            p.setBrush(G.QColor('#e9ae21'))
            p.drawEllipse(xy(race['target']),7,7)
        pos=self.status['position']
        origin=xy(pos)
        p.setBrush(G.QColor('#2076c9'))
        p.drawEllipse(origin,5,5)
        yaw=self.status['yaw']
        p.setPen(G.QPen(G.QColor('#2076c9'),3))
        p.drawLine(origin,xy((pos[0]+math.cos(yaw)*1.2,pos[1]+math.sin(yaw)*1.2)))


class SceneView(W.QWidget):
    def __init__(self):
        super().__init__()
        self.picture = None
        self.setMinimumSize(480, 300)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Expanding)

    def set_frame(self, picture):
        self.picture = picture
        self.update()

    def paintEvent(self, event):
        painter = G.QPainter(self)
        painter.fillRect(self.rect(), G.QColor('#152638'))
        if self.picture is None:
            painter.setPen(G.QColor('#d5e0ec'))
            painter.drawText(self.rect(), C.Qt.AlignCenter, '正在载入机器人…')
        else:
            size = self.picture.size().scaled(self.size(), C.Qt.KeepAspectRatio)
            rect = C.QRect((self.width()-size.width())//2, (self.height()-size.height())//2,
                          size.width(), size.height())
            painter.drawImage(rect, self.picture)

class SceneWindow(W.QWidget):
    ready = C.Signal()
    failed = C.Signal(str)
    dismissed = C.Signal()
    competition_finished = C.Signal(str)

    def __init__(self, mode, parent=None, *, source='live', competition=None):
        super().__init__(parent, C.Qt.Window)
        self.setAttribute(C.Qt.WA_DeleteOnClose)
        self.mode = mode
        self.source = source
        self.competition = competition
        self.scene_id = 'g1_outdoor_15m_v1'
        self.settings = CommandSettings()
        self.latest_status = {}
        self.controlled_close = self.reported_failure = False
        self.setWindowTitle('采集示范 · 按标签做动作' if mode == 'sample' else '机器人练习场 · '+('离线回放' if source=='replay' else '实时推理'))
        if competition:
            config=competition['config']
            self.setWindowTitle('机器人金币任务 · '+('正式比赛' if config.official else '练习'))
        self.resize(980, 760)
        self.setMinimumSize(680, 600)
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        heading = W.QHBoxLayout()
        title = W.QLabel(self.windowTitle())
        title.setObjectName('heading')
        heading.addWidget(title, 1)
        finish = W.QPushButton('结束并保存' if mode == 'sample' else '结束推理')
        finish.clicked.connect(self.close)
        heading.addWidget(finish)
        layout.addLayout(heading)
        self.cue = W.QLabel('正在准备机器人，请稍候…')
        self.cue.setAlignment(C.Qt.AlignCenter)
        self.cue.setWordWrap(True)
        self.cue.setObjectName('cueBanner')
        layout.addWidget(self.cue)
        self.detail = W.QLabel('机器人站稳后自动开始。')
        self.detail.setAlignment(C.Qt.AlignCenter)
        layout.addWidget(self.detail)
        self.race_panel = W.QWidget()
        race_layout = W.QVBoxLayout(self.race_panel)
        race_layout.setContentsMargins(0,0,0,0)
        self.race_panel.setFixedWidth(180)
        self.race_info = W.QLabel('等待模型与信号准备就绪…')
        self.race_info.setWordWrap(True)
        self.race_info.setStyleSheet('font-size:20px;font-weight:600;color:#17446d;')
        race_layout.addWidget(self.race_info)
        self.race_map = RaceMap()
        race_layout.addWidget(self.race_map)
        race_layout.addStretch(1)
        self.race_panel.setVisible(bool(competition))
        self.view = SceneView()
        view_row = W.QHBoxLayout()
        view_row.addWidget(self.view,1)
        view_row.addWidget(self.race_panel)
        layout.addLayout(view_row,1)
        self.feedback = W.QLabel('')
        self.feedback.setAlignment(C.Qt.AlignCenter)
        layout.addWidget(self.feedback)
        self.hint = W.QLabel('准备时放松；文字和倒计时消失后，按脚下符号做动作。“休息”和停止符号都表示放松。' if mode == 'sample'
                             else '离线回放：已录制的原始肌电重新经过模型解码；机器人跟随预测结果，标签不直接控制机器人。' if source=='replay'
                             else '实时推理：肌电经模型解码后控制机器人；放松肌肉使它停止。')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        footer = W.QLabel(f'前进 {self.settings.forward_speed:.1f} m/s · 转向 {self.settings.turn_speed:.1f} rad/s   |   视角自动跟随机器人\n场景：{self.scene_id} · 实时与离线共用 · 自由练习（无金币任务）')
        footer.setWordWrap(True)
        footer.setStyleSheet('color:#657687;font-size:12px;')
        if competition:
            footer.setText(f'种子 {config.seed} · {config.count} 枚 · 限时 {config.limit_s:g} 秒 · 所有模型统一排名\n{'进阶' if config.speed_tier=='advanced' else '基础'}档：{speed_summary(config.speed_tier)}；比赛中不能暂停或重置。')
            finish.setText('结束本局并保存')
            self.hint.setText('靠近金币即可收集，再前往下一枚。小地图：蓝点为机器人，短线表示朝向，金点为当前目标；上方为场地 +X。')
        layout.addWidget(footer)
        self.worker = SimulationWorker(competition)
        self.worker.setParent(self)
        self.worker.frame.connect(self.view.set_frame)
        self.worker.telemetry.connect(self._status)
        self.worker.ready.connect(self._ready)
        self.worker.failed.connect(self._fail)
        self.worker.competition_finished.connect(self.competition_finished)
        self.load_timeout = C.QTimer(self)
        self.load_timeout.setSingleShot(True)
        self.load_timeout.timeout.connect(lambda: self._fail('机器人准备超时，请检查安装和显卡驱动后重试。'))

    def start(self):
        self.show()
        self.load_timeout.start(30000)
        self.worker.start()

    def _ready(self):
        self.load_timeout.stop()
        self.cue.setText('等待动作提示' if self.mode == 'sample' else '等待推理结果')
        self.cue.setVisible(self.mode != 'sample')
        self.detail.setText('')
        self.ready.emit()

    def show_capture(self, status):
        self.worker.update_capture(status, self.settings)
        if status.get('done'):
            self.cue.show()
            self.cue.setText('本次采集已结束')
            return
        # The scene owns the action cue; avoid a duplicate persistent text prompt.
        self.cue.show()
        name=NAMES[Command(status['cue'])]
        self.cue.setText(f"{status['phase']}：{name}  {status['remaining']:.1f} 秒")
        self.detail.setText(f"第 {status['trial']} / {status['trial_count']} 组 · 组内第 {status['action_index']} / {status.get('action_count',4)} 个动作")

    def show_command(self, command):
        command = Command(command)
        self.worker.update_command(command, self.settings)
        self.cue.setText(f'推理结果：{NAMES[command]}')

    def show_velocity(self, velocity):
        self.worker.update_velocity(velocity)
        self.cue.setText('连续/混合控制 · 统一限幅')

    def arm_competition(self):
        self.worker.arm_competition()

    def _status(self, status):
        self.latest_status = status
        self.feedback.setText(f"实际速度：前后 {status['forward_actual']:+.2f} m/s · 左右 {status.get('lateral_actual',0):+.2f} m/s · 转向 {status['yaw_actual']:+.2f} rad/s")
        if self.competition:
            race=status.get('race')
            if race:
                self.race_map.set_status(status)
                self.race_info.setText(f"已收集\n{race['count']} / {race['config']['count']} 枚\n\n剩余时间\n{race['remaining']:.1f} 秒")
                if race['countdown']:
                    self.detail.setText(f"准备 {race['countdown']} 秒 · 机器人站稳后开始计时")
                elif race['reason']:
                    self.detail.setText(REASONS.get(race['reason'],race['reason']))
                elif race['target']:
                    dx,dy=[a-b for a,b in zip(race['target'],status['position'])]
                    angle=math.atan2(math.sin(math.atan2(dy,dx)-status['yaw']),math.cos(math.atan2(dy,dx)-status['yaw']))
                    direction='正前方' if abs(angle)<.15 else ('左侧' if angle>0 else '右侧')+f' {abs(math.degrees(angle)):.0f}°'
                    self.detail.setText(f'下一枚距离 {math.hypot(dx,dy):.2f} m · {direction}'+(' · 信号过期，已停止' if status['expired'] else ''))
            return
        if status['fallen']:
            self._fail('机器人已跌倒，本次实验已结束。请重新开始。')
        elif status['physics_hz'] and status['physics_hz'] < 40:
            self.hint.setText('当前电脑画面运行较慢，机器人动作可能滞后；采集时请以文字提示为准。')
        elif self.mode == 'open' and status['expired']:
            self.detail.setText('等待新的推理结果，机器人保持停止。')
        elif self.mode == 'open':
            self.detail.setText('观察机器人动作是否与你的意图一致。')

    def _fail(self, message):
        if not self.reported_failure and not self.controlled_close:
            self.reported_failure = True
            self.load_timeout.stop()
            self.failed.emit(message)

    def shutdown(self):
        self.controlled_close = True
        self.close()

    def closeEvent(self, event):
        self.load_timeout.stop()
        if not self.competition:
            self.worker.update_command(Command.STOP, self.settings)
        if not self.worker.close():
            event.ignore()
            self.cue.setText('正在关闭机器人画面…')
            C.QTimer.singleShot(500, self.close)
            return
        event.accept()
        if not self.controlled_close:
            self.dismissed.emit()
