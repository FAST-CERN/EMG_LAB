"""The same four commands can later be supplied by the EMG classifier."""
from dataclasses import dataclass
from enum import IntEnum
import math

# Fixed classification uses the basic tier; advanced requires teacher review in formal races.
FORWARD_LIMIT = .6
BACKWARD_LIMIT = .4
LATERAL_LIMIT = .4
YAW_LIMIT = 1.0
TRANSLATION_LIMIT = .6
SLEW_LIMITS = (1.5,1.5,2.5)


def velocity_limits(tier='basic'):
    if tier not in ('basic','advanced'):
        raise ValueError('速度档位须为 basic 或 advanced。')
    x,b,y,w,h=(.6,.4,.4,1.,.6) if tier=='basic' else (.8,.6,.6,1.2,.8)
    return dict(forward=x,backward=b,lateral=y,yaw=w,translation_norm=h,
                shape='axis_clip_then_xy_norm',slew_limits=list(SLEW_LIMITS))


def speed_summary(tier='basic'):
    limits=velocity_limits(tier)
    return f"前进 {limits['forward']:g} · 后退/侧移 {limits['lateral']:g} m/s · 转向 {limits['yaw']:g} rad/s"


def clamp_velocity(velocity,tier='basic'):
    """Body-frame commands: axis caps, shared planar-speed cap, independent yaw."""
    limits=velocity_limits(tier)
    values = tuple(float(v) for v in velocity)
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError('连续指令必须是有限数值 [vx, vy, wz]。')
    x=min(limits['forward'],max(-limits['backward'],values[0]))
    y=min(limits['lateral'],max(-limits['lateral'],values[1]))
    yaw=min(limits['yaw'],max(-limits['yaw'],values[2]))
    scale=max(1.,math.hypot(x,y)/limits['translation_norm'])
    return (x/scale,y/scale,yaw)


class Command(IntEnum):
    STOP = 0
    LEFT = 1
    RIGHT = 2
    FORWARD = 3
    BACKWARD = 4
    STRAFE_LEFT = 5
    STRAFE_RIGHT = 6


NAMES = {Command.STOP: '停止', Command.LEFT: '左转', Command.RIGHT: '右转', Command.FORWARD: '前进'}
NAMES.update({Command.BACKWARD:'后退',Command.STRAFE_LEFT:'左移',Command.STRAFE_RIGHT:'右移'})


@dataclass(frozen=True)
class CommandSettings:
    forward_speed: float = FORWARD_LIMIT
    turn_speed: float = YAW_LIMIT

    def __post_init__(self):
        if not math.isfinite(self.forward_speed) or not 0.1 <= self.forward_speed <= FORWARD_LIMIT:
            raise ValueError(f'前进速度须在 0.10–{FORWARD_LIMIT:.2f} m/s 之间。')
        if not math.isfinite(self.turn_speed) or not 0.1 <= self.turn_speed <= YAW_LIMIT:
            raise ValueError(f'转向速度须在 0.10–{YAW_LIMIT:.2f} rad/s 之间。')

    def velocity(self, command):
        command = Command(command)
        return (self.forward_speed if command == Command.FORWARD else -min(self.forward_speed,BACKWARD_LIMIT) if command == Command.BACKWARD else 0.,
                min(self.forward_speed,LATERAL_LIMIT) if command == Command.STRAFE_LEFT else -min(self.forward_speed,LATERAL_LIMIT) if command == Command.STRAFE_RIGHT else 0.,
                self.turn_speed if command == Command.LEFT else -self.turn_speed if command == Command.RIGHT else 0.)
