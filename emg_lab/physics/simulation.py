"""Closed-loop rigid-body simulation. Only reset writes qpos directly."""
from pathlib import Path
import math
import time
import numpy as np
import mujoco
from .commands import Command, CommandSettings, SLEW_LIMITS
from .policy import DecoupledPolicy, DEFAULT, KP, KD
from .environment import load_scene

ROOT = Path(__file__).resolve().parents[2]
POLICY_DT = .02


class Simulation:
    def __init__(self, asset_root=ROOT/'assets', *, coin=False):
        self.model = load_scene(asset_root, coin=coin)
        self.model.opt.timestep = .005
        self.data = mujoco.MjData(self.model)
        if (self.model.nq, self.model.nv, self.model.nu) != (36, 35, 29):
            raise ValueError('需要匹配策略的 G1 29 关节模型。')
        # Explicitly verify actuator order rather than silently assuming the XML layout.
        if not np.array_equal(self.model.actuator_trnid[:,0], np.arange(1,30)):
            raise ValueError('机器人关节顺序与策略不匹配。')
        self.pelvis = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, 'pelvis')
        self.policy = DecoupledPolicy(asset_root)
        self.settings = CommandSettings()
        self.reset()

    def reset(self):
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[:3] = [0.,0.,.79]
        self.data.qpos[3:7] = [1.,0.,0.,0.]
        self.data.qpos[7:] = DEFAULT
        mujoco.mj_forward(self.model, self.data)
        self.policy.reset()
        self.command = Command.STOP
        self.velocity_mode = False
        self.command_velocity = np.zeros(3)
        self.control_velocity = np.zeros(3)
        self.effective_velocity = np.zeros(3)
        self.velocity_heading_hold = False
        self.heading_target = 0.
        self.fallen = False
        self.steps = 0
        self.last_policy_ms = self.last_step_ms = 0.
        self.min_height = .79

    @property
    def yaw(self):
        rotation = self.data.xmat[self.pelvis].reshape(3,3)
        return math.atan2(rotation[1,0], rotation[0,0])

    def set_command(self, command, settings=None):
        command = Command(command)
        self.velocity_mode = False
        if settings is not None:
            self.settings = settings
        if command in (Command.FORWARD,Command.BACKWARD,Command.STRAFE_LEFT,Command.STRAFE_RIGHT) and self.command != command:
            self.heading_target = self.yaw
        self.command = command
        self.command_velocity = np.array(self.settings.velocity(command))

    def set_velocity(self, velocity, tier='basic'):
        """Extension boundary for continuous commands; competition owns the envelope."""
        from .commands import clamp_velocity
        velocity = np.asarray(clamp_velocity(velocity,tier), dtype=float)
        hold = bool(np.linalg.norm(velocity[:2]) > 0 and abs(velocity[2]) < 1e-9)
        if hold and (not self.velocity_mode or not self.velocity_heading_hold):
            self.heading_target = self.yaw
        self.velocity_heading_hold = hold
        self.command_velocity = velocity
        self.velocity_mode = True
        self.command = Command.STOP

    def step(self):
        if self.fallen:
            return self.status()
        if not np.isfinite(self.data.qpos).all() or not np.isfinite(self.data.qvel).all():
            raise RuntimeError('物理状态异常，请重置场景。')
        if self.data.qpos[2] < .4:
            self.fallen = True
            self.set_command(Command.STOP)
            self.data.ctrl[:] = 0.
            return self.status()
        started = time.perf_counter()
        # Main command slew only; physical stopping also includes policy response.
        limits = np.array(SLEW_LIMITS)*POLICY_DT
        self.control_velocity += np.clip(self.command_velocity-self.control_velocity, -limits, limits)
        effective = self.control_velocity.copy()
        # The pretrained policy has no heading observation: gently correct straight-walk drift.
        if (self.velocity_mode and self.velocity_heading_hold or not self.velocity_mode and
                self.command in (Command.FORWARD,Command.BACKWARD,Command.STRAFE_LEFT,Command.STRAFE_RIGHT)):
            error = math.atan2(math.sin(self.heading_target-self.yaw), math.cos(self.heading_target-self.yaw))
            effective[2] = np.clip(.8*error, -.15, .15)
        if np.linalg.norm(effective) < .05:
            effective[:] = 0.
        rotation = self.data.xmat[self.pelvis].reshape(3,3)
        gravity = rotation.T @ np.array([0.,0.,-1.])
        before_policy = time.perf_counter()
        target = self.policy.target(self.data.qpos, self.data.qvel, gravity, effective)
        self.last_policy_ms = (time.perf_counter()-before_policy)*1000
        for _ in range(4):
            # Joint force limits are specified by the upstream XML. Apply PD at every physics step.
            self.data.ctrl[:] = KP*(target-self.data.qpos[7:])-KD*self.data.qvel[6:]
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        self.steps += 1
        self.min_height = min(self.min_height, float(self.data.qpos[2]))
        if not np.isfinite(self.data.qpos).all() or not np.isfinite(self.data.qvel).all():
            raise RuntimeError('物理状态异常，请重置场景。')
        if self.data.qpos[2] < .4:
            self.fallen = True
            self.set_command(Command.STOP)
            self.data.ctrl[:] = 0.
        self.last_step_ms = (time.perf_counter()-started)*1000
        self.effective_velocity = effective
        return self.status()

    def status(self):
        rotation = self.data.xmat[self.pelvis].reshape(3,3)
        velocity_body = rotation.T @ self.data.qvel[:3]
        return dict(time=float(self.data.time), command=int(self.command),
                    requested=self.command_velocity.tolist(), applied=self.control_velocity.tolist(),
                    effective=getattr(self,'effective_velocity',self.control_velocity).tolist(),
                    tilt_deg=math.degrees(math.acos(float(np.clip(rotation[2,2],-1,1)))),
                    forward_actual=float(velocity_body[0]), yaw_actual=float(self.data.qvel[5]),
                    lateral_actual=float(velocity_body[1]),
                    height=float(self.data.qpos[2]), position=self.data.qpos[:3].tolist(), yaw=self.yaw,
                    policy=self.policy.last_policy, policy_ms=self.last_policy_ms,
                    step_ms=self.last_step_ms, fallen=self.fallen, steps=self.steps)
