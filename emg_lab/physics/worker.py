"""Physics, race clock, command limits and rendering share one worker."""
import threading
import time
import traceback
import numpy as np
import mujoco
from PySide6 import QtCore as C, QtGui as G
from .commands import Command, CommandSettings, clamp_velocity
from .simulation import Simulation, POLICY_DT
from .camera import FollowCamera
from .ground_cue_presenter import GroundCuePresenter
from .coin_presenter import CoinPresenter
from ..capture import preparation_countdown
from ..competition import Race, RaceLog, fixed_velocity, check_speed_access


class SimulationWorker(C.QThread):
    frame = C.Signal(G.QImage)
    telemetry = C.Signal(dict)
    ready = C.Signal()
    failed = C.Signal(str)
    competition_finished = C.Signal(str)

    def __init__(self, competition=None):
        super().__init__()
        self.competition = competition
        self.lock = threading.Lock()
        self.shutdown = threading.Event()
        self.requested = Command.STOP
        self.velocity = (0.,0.,0.)
        self.settings = CommandSettings()
        self.updated = 0.
        self.reset_requested = self.armed = False
        self.paused = False
        self.end_reason = 'aborted'
        self.cue, self.cue_active, self.countdown = None, False, None

    def update_command(self, command, settings):
        if self.competition:
            fixed_velocity(command)  # No float truncation or silent class remapping.
            if self.competition['config'].control_mode != 'fixed_classification':
                raise ValueError('本局声明为连续控制，请提交速度向量。')
            settings = CommandSettings()
        with self.lock:
            self.requested, self.settings = Command(command), settings
            self.cue, self.cue_active, self.countdown = None, False, None
            self.updated = time.monotonic()

    def update_velocity(self, velocity):
        if not self.competition or self.competition['config'].control_mode != 'continuous':
            raise ValueError('速度接口只用于预先声明的连续/混合控制局。')
        checked = tuple(float(v) for v in velocity)
        clamp_velocity(checked,self.competition['config'].speed_tier)
        with self.lock:
            self.velocity = checked
            self.updated = time.monotonic()

    def arm_competition(self):
        with self.lock:
            self.armed = True

    def end_competition(self, reason):
        with self.lock:
            self.end_reason = reason

    def update_capture(self, status, settings):
        with self.lock:
            self.cue_active = not status.get('done') and status['phase'] == '动作'
            self.cue = status.get('cue') if not status.get('done') and status['phase'] in ('准备', '动作') else None
            self.countdown = preparation_countdown(status)
            self.requested = Command(status['command']) if self.cue_active else Command.STOP
            self.settings = settings
            self.updated = time.monotonic()

    def reset_scene(self):
        if self.competition:
            raise ValueError('金币任务不能中途重置；请结束本局并保留记录。')
        with self.lock:
            self.requested = Command.STOP
            self.reset_requested = True
            self.paused = False

    def set_paused(self, paused):
        if self.competition:
            raise ValueError('金币任务不能暂停计时。')
        with self.lock:
            self.paused = paused
            self.requested = Command.STOP

    def run(self):
        renderer = race = log = None
        reported = False
        warmup = 0
        try:
            sim = Simulation(coin=self.competition is not None)
            sim.model.vis.global_.offwidth = 800
            sim.model.vis.global_.offheight = 600
            renderer = mujoco.Renderer(sim.model, height=600, width=800)
            camera = mujoco.MjvCamera()
            camera.type = mujoco.mjtCamera.mjCAMERA_FREE
            follow = FollowCamera()
            cues = GroundCuePresenter(sim.model)
            coin = CoinPresenter(sim.model) if self.competition else None
            scene_options = mujoco.MjvOption()
            scene_options.geomgroup[3:] = 0
            loaded = False
            deadline = next_frame = last_frame = metric_start = time.monotonic()
            steps_since_metric = frames_since_metric = 0
            physics_hz = render_fps = render_ms = 0.
            while not self.shutdown.is_set():
                now = time.monotonic()
                with self.lock:
                    command, settings, paused = self.requested, self.settings, self.paused
                    velocity, armed = self.velocity, self.armed
                    reset = self.reset_requested
                    self.reset_requested = False
                    age = now-self.updated
                    expired = age > .75
                    cue, cue_active, countdown = self.cue, self.cue_active, self.countdown
                if self.competition and armed and race is None:
                    check_speed_access(self.competition['config'],self.competition['context'])
                    race = Race(self.competition['config'])
                    log = RaceLog(race.config, self.competition['context'], self.competition['data_root'])
                    reset = True
                    warmup = 150  # Exactly 3 simulation seconds at STOP for every entrant.
                if reset:
                    sim.reset()
                    follow.reset()
                    command = Command.STOP
                running = race is not None and race.started is not None and not race.reason
                stopped = not loaded or expired or paused or bool(self.competition and not running)
                if self.competition and self.competition['config'].control_mode == 'continuous':
                    sim.set_velocity((0.,0.,0.) if stopped else velocity, self.competition['config'].speed_tier)
                else:
                    actual_command = Command.STOP if stopped else command
                    sim.set_command(actual_command, CommandSettings() if self.competition else settings)
                    if self.competition and not np.allclose(sim.command_velocity, fixed_velocity(int(actual_command)), rtol=0, atol=0):
                        raise ValueError('固定类别速度表运行时校验失败。')
                if not paused and not sim.fallen and not (race and race.reason):
                    status = sim.step()
                    steps_since_metric += 1
                else:
                    status = sim.status()
                if race:
                    if race.started is None and not race.reason:
                        warmup -= 1
                        if sim.fallen:
                            race.finish('startup_error')
                        elif warmup <= 0:
                            race.start(time.monotonic(), status['time'])
                    elif not race.reason:
                        race.update(status, time.monotonic())
                        if age > 1.5 and not race.reason:
                            race.finish('signal_lost', time.monotonic())
                        log.record(race, status, int(command) if race.config.control_mode=='fixed_classification' else None,
                                   expired, submitted=list(velocity) if race.config.control_mode=='continuous' else None)
                    status['race'] = race.snapshot()
                    status['race']['countdown'] = max(0,(warmup+49)//50)
                if now >= next_frame:
                    tick = time.perf_counter()
                    follow.update(camera, sim.data.qpos, now-last_frame)
                    last_frame = now
                    if coin:
                        coin.update(sim.model, sim.data, race.target if running else None, sim.data.time)
                    renderer.update_scene(sim.data, camera=camera, scene_option=scene_options)
                    if not self.competition:
                        cues.update(renderer.scene, camera, sim.data,
                                    cue if loaded and not expired and not paused else None, cue_active, countdown)
                    pixels = renderer.render()
                    picture = G.QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], G.QImage.Format.Format_RGB888).copy()
                    self.frame.emit(picture)
                    render_ms = (time.perf_counter()-tick)*1000
                    frames_since_metric += 1
                    next_frame = max(next_frame+.04,now+.001)
                    if not loaded and status['time'] >= 1. and not status['fallen']:
                        loaded = True
                        self.ready.emit()
                elapsed = now-metric_start
                if elapsed >= 1.:
                    physics_hz = steps_since_metric/elapsed
                    render_fps = frames_since_metric/elapsed
                    steps_since_metric = frames_since_metric = 0
                    metric_start = now
                if sim.steps % 5 == 0 or paused or sim.fallen or (race and race.reason):
                    status.update(paused=paused, expired=expired, physics_hz=physics_hz,
                                  render_fps=render_fps, render_ms=render_ms)
                    self.telemetry.emit(status)
                if race and race.reason:
                    report = log.finish(race)
                    reported = True
                    self.competition_finished.emit(str(report))
                    break
                deadline += POLICY_DT
                # Never enlarge physics dt or skip steps to hide a slow computer.
                if deadline < time.monotonic()-POLICY_DT:
                    deadline = time.monotonic()
                self.shutdown.wait(max(0., deadline-time.monotonic()))
        except Exception as exc:
            traceback.print_exc()
            if race and not race.reason:
                race.finish('startup_error' if race.started is None else 'invalid_physics',time.monotonic())
            self.failed.emit(str(exc))
        finally:
            try:
                if race and log and not reported:
                    race.finish(self.end_reason,time.monotonic())
                    self.competition_finished.emit(str(log.finish(race)))
            except Exception as exc:
                self.failed.emit('成绩写入失败，保留了未完成记录：'+str(exc))
            if renderer is not None:
                renderer.close()

    def close(self):
        self.shutdown.set()
        return self.wait(5000)
