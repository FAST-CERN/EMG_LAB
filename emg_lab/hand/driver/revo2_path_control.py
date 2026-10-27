"""A reversible straight path for index, middle, ring and little fingers only.

The thumb is initialized to the factory OPEN resting pose once if necessary.
Subsequent open/close motion and stops operate on the four fingers only.
"""
from __future__ import annotations
import math
import time

from .revo2_control import HANDS
from .revo2_gesture_control import GestureController, GestureUsbHand

CONTROLLED_AXES = (2, 3, 4, 5)
DEFAULT_MAX_RATE = 160
# Exported from this hand's factory OPEN final pose (revo2_builtin_sequences.json).
THUMB_DEFAULT_DEG = (24, 30)
THUMB_INITIAL_SPEED = 20


def thumb_default(limits):
    result = []
    for i, angle in enumerate(THUMB_DEFAULT_DEG):
        lo, hi = limits['minimum'][i], limits['maximum'][i]
        if not lo <= angle <= hi or hi <= lo:
            raise ValueError('默认拇指姿态超出设备量程')
        result.append(round(1000*(angle-lo)/(hi-lo)))
    return result


class PathUsbHand(GestureUsbHand):
    def write(self, register, words):
        thumb_init = (getattr(self, '_thumb_initializing', False) and words and words[0] in (0, 1))
        if register not in (1055, 1058) or not words or (words[0] not in CONTROLLED_AXES and not thumb_init):
            raise ValueError('四指模式只允许向食指、中指、无名指和小指发送指令')
        return super().write(register, words)

    def _group_write(self, register, words):
        raise ValueError('四指模式不发送六路群控指令')

    def initialize_thumb(self):
        targets = thumb_default(self.limits)
        self._thumb_initializing = True  # Retain until feedback settles or STOP completes.
        for i in (0, 1):
            speed = max(1, min(1000, round(THUMB_INITIAL_SPEED/self.limits['speed'][i]*1000)))
            self.move(i, targets[i], speed)

    def finish_thumb_initialization(self):
        self._thumb_initializing = False

    def move_all(self, positions, rate, weights):
        # Single-axis 1055 is the interface verified on this hand.
        for i in CONTROLLED_AXES:
            physical = rate * weights[i]
            speed = max(1, min(1000, round(physical / self.limits['speed'][i] * 1000)))
            self.move(i, int(positions[i]), speed)

    def stop_all(self):
        """Include the thumb only while its explicit initialization is underway."""
        errors = []
        axes = ((0, 1) if getattr(self, '_thumb_initializing', False) else ()) + CONTROLLED_AXES
        for i in axes:
            try:
                self.stop(i)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError(' / '.join(errors))
        self._thumb_initializing = False


class PathSimHand:
    def __init__(self, side='left'):
        self.info = dict(side=side, serial=HANDS[side]['serial'], firmware='SIMULATION', unit_mode=0)
        self.limits = dict(minimum=[0]*6, maximum=[60,89,81,81,81,81], speed=[145,160,130,130,130,130])
        self.positions = [400.,337.,0.,0.,0.,0.]
        self.targets = self.positions.copy()
        self.velocities = [0.]*6
        self.last = time.monotonic()
        self.writes = []
        self.closed = False

    def status(self):
        now = time.monotonic()
        dt, self.last = now-self.last, now
        states, speeds = [0]*6, [0]*6
        for i in range(6):
            delta = self.targets[i]-self.positions[i]
            step = self.velocities[i]*1000/(self.limits['maximum'][i]-self.limits['minimum'][i])*dt
            self.positions[i] += max(-step, min(step, delta))
            moving = abs(self.targets[i]-self.positions[i]) > .5
            states[i] = int(moving)
            speeds[i] = round((1 if delta>0 else -1)*self.velocities[i]/self.limits['speed'][i]*1000) if moving else 0
        return dict(positions=[round(p) for p in self.positions], speeds=speeds,
                    motor_states=states, currents_raw=[80 if s else 0 for s in states])

    def move_all(self, positions, rate, weights):
        self.status()
        for i in CONTROLLED_AXES:
            self.targets[i] = positions[i]
            self.velocities[i] = rate*weights[i]
        self.writes.append(dict(kind='move', axes=list(CONTROLLED_AXES), positions=list(positions),
                                rate=rate, velocities=self.velocities.copy()))

    def initialize_thumb(self):
        self.status()
        self._thumb_initializing = True
        self.targets[:2] = thumb_default(self.limits)
        self.velocities[:2] = [THUMB_INITIAL_SPEED]*2
        self.writes.append(dict(kind='thumb_init', axes=[0,1], positions=self.targets[:2]))

    def finish_thumb_initialization(self):
        self._thumb_initializing = False

    def stop_all(self):
        self.status()
        axes = ((0,1) if getattr(self, '_thumb_initializing', False) else ()) + CONTROLLED_AXES
        for i in axes:
            self.targets[i] = self.positions[i]
        self.writes.append(dict(kind='stop', axes=list(axes)))
        self._thumb_initializing = False

    def close(self):
        self.closed = True


class ReversiblePath:
    def __init__(self, limits, serial):
        if serial != HANDS['left']['serial']:
            raise ValueError('当前控制器用于已验证的左手')
        self.limits = limits
        self.thumb_target = thumb_default(limits)
        self.thumb_ready = False
        self.knots = [[None, None]+[0]*4, [None, None]+[1000]*4]
        self.factors = [0.]*6
        for i in CONTROLLED_AXES:
            lo, hi, speed = limits['minimum'][i], limits['maximum'][i], limits['speed'][i]
            if hi <= lo or speed <= 0:
                raise ValueError('设备四指位置或速度量程无效')
            self.factors[i] = (hi-lo)/100  # deg/s per one percent/s of travel
        self.max_rate = math.floor(min(limits['speed'][i]/self.factors[i] for i in CONTROLLED_AXES))
        if self.max_rate < 1:
            raise ValueError('设备速度量程不支持当前进度单位')
        self.tolerances = [0, 0, 5, 5, 5, 5]  # Arrival recognition, not a motion limit.
        self.initialized = False
        self.index = 0
        self.cancel()

    def near(self, positions, target):
        return all(abs(positions[i]-target[i]) <= self.tolerances[i] for i in CONTROLLED_AXES)

    def project(self, positions):
        return max(0, min(1, sum(positions[i] for i in CONTROLLED_AXES)/4000))

    def point_at(self, phase):
        return [None, None]+[round(max(0, min(1, phase))*1000)]*4

    def cancel(self):
        self.intent = None
        self.active = self.homing = self.preparing_thumb = False
        self.targets = None
        self.streak = 0
        self.weights = [0.]*6

    def initialize_from(self, sample):
        self.thumb_ready = self.thumb_settled(sample)
        self.initialized = (self.thumb_ready and self.near(sample['positions'], self.knots[0])
                            and all(sample['motor_states'][i] == 0 and abs(sample['speeds'][i]) <= 5
                                    for i in CONTROLLED_AXES))

    def thumb_settled(self, sample):
        return all(abs(sample['positions'][i]-self.thumb_target[i]) <= 5
                   and sample['motor_states'][i] == 0 and abs(sample['speeds'][i]) <= 5 for i in (0,1))

    def begin(self, intent, positions):
        if intent not in ('open', 'fist'):
            raise ValueError('未知指令')
        if self.intent == intent:
            return None
        if not self.initialized and intent == 'fist':
            raise ValueError('请先点击张开，恢复默认初始姿态')
        self.homing = not self.initialized
        self.intent, self.active, self.streak = intent, True, 0
        self.index = 1 if intent == 'fist' else 0
        if not self.thumb_ready:
            self.preparing_thumb = True
            self.targets = self.thumb_target + [None]*4
            self.weights = [0.]*6
            return self.targets.copy()
        self.targets = self.knots[self.index].copy()
        self.weights = self.factors.copy()
        return self.targets.copy()

    def observe(self, sample):
        if not self.active:
            return None
        if self.preparing_thumb:
            self.streak = self.streak+1 if self.thumb_settled(sample) else 0
            if self.streak < 3:
                return None
            self.thumb_ready, self.preparing_thumb = True, False
            self.streak = 0
            self.targets = self.knots[0].copy()
            self.weights = self.factors.copy()
            return self.targets.copy()
        settled = (self.near(sample['positions'], self.targets)
                   and all(sample['motor_states'][i] == 0 and abs(sample['speeds'][i]) <= 5
                           for i in CONTROLLED_AXES))
        self.streak = self.streak+1 if settled else 0
        if self.streak < 3:
            return None
        self.initialized = True
        self.homing = self.active = False
        return 'done'

    def view(self, positions):
        return dict(intent=self.intent, active=self.active, targets=self.targets, weights=self.weights,
                    stage=1, count=1, progress=100*self.project(positions),
                    initialized=self.initialized, homing=self.homing, preparing_thumb=self.preparing_thumb,
                    stage_label='四指张开初始化' if self.homing else '四指同步 · 张开 0% ↔ 握合 100%')


class PathController(GestureController):
    def __init__(self, factory=PathUsbHand):
        super().__init__(factory)
        self.speed = 15

    def connect_hand(self):
        if self.hand:
            return
        self.hand = self.factory('left')
        self.planner = ReversiblePath(self.hand.limits, self.hand.info['serial'])
        self.set_speed(min(self.speed, self.planner.max_rate))
        sample = self.read()
        self.planner.initialize_from(sample)
        self.emit('connected', info=self.hand.info, limits=self.hand.limits, max_speed=self.planner.max_rate)
        self.emit('sample', sample=sample, view=self.planner.view(sample['positions']))

    def set_speed(self, value):
        value = int(value)
        maximum = self.planner.max_rate if self.planner else DEFAULT_MAX_RATE
        if not 1 <= value <= maximum:
            raise ValueError(f'速度应为 1–{maximum} %/s')
        with self.lock:
            self.speed = value

    def request_intent(self, intent):
        if self.planner and not self.planner.initialized and intent == 'fist':
            self.emit('rejected', message='请先点击张开，恢复默认初始姿态')
            return
        super().request_intent(intent)

    def send_stage(self, message):
        if self.interrupted():
            return
        self.touched = True
        with self.lock:
            speed = self.speed
        if self.planner.preparing_thumb:
            if not getattr(self.hand, '_thumb_initializing', False):
                self.hand.initialize_thumb()
        else:
            self.hand.finish_thumb_initialization()
            self.hand.move_all(self.planner.targets, speed, self.planner.weights)
        self.sent_speed, self.last_send = speed, time.monotonic()
        label = ('拇指恢复默认姿态 24° / 30°' if self.planner.preparing_thumb else
                 '四指张开初始化' if self.planner.homing else ('四指握合' if self.planner.intent == 'fist' else '四指张开'))
        self.emit('motion', message=label, speed=speed, view=self.planner.view(self.last_sample['positions']))
