"""Animated mocap-backed coin presentation for open mode."""

from __future__ import annotations

import math

import mujoco
import numpy as np


OPEN_COIN_BODY = "open_coin"
OPEN_COIN_GEOM = "open_coin_geom"
COIN_BASE_Z_M = 0.58
COIN_BOB_AMPLITUDE_M = 0.08
COIN_BOB_HZ = 0.7
COIN_SPIN_HZ = 0.35


class CoinPresenter:
    def __init__(self, model: mujoco.MjModel) -> None:
        try:
            body_id = model.body(OPEN_COIN_BODY).id
            self.geom_id = model.geom(OPEN_COIN_GEOM).id
        except KeyError as error:
            raise ValueError("scene is missing the open-mode coin asset") from error
        self._mocap_id = int(model.body_mocapid[body_id])
        if self._mocap_id < 0:
            raise ValueError(f"coin body {OPEN_COIN_BODY} must be a mocap body")

    @property
    def mocap_id(self) -> int:
        return self._mocap_id

    def update(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        coin_xy: np.ndarray | None,
        session_time_s: float,
    ) -> None:
        if coin_xy is None:
            self.reset(model, data)
            return
        bob = COIN_BOB_AMPLITUDE_M * math.sin(
            2.0 * math.pi * COIN_BOB_HZ * session_time_s
        )
        spin = 2.0 * math.pi * COIN_SPIN_HZ * session_time_s
        data.mocap_pos[self._mocap_id] = (coin_xy[0], coin_xy[1], COIN_BASE_Z_M + bob)
        data.mocap_quat[self._mocap_id] = _multiply_quat(
            _axis_angle_quat((0.0, 0.0, 1.0), spin),
            _axis_angle_quat((0.0, 1.0, 0.0), math.pi / 2.0),
        )
        mujoco.mj_forward(model, data)

    def reset(self, model: mujoco.MjModel, data: mujoco.MjData) -> None:
        data.mocap_pos[self._mocap_id] = (0.0, 0.0, -2.0)
        data.mocap_quat[self._mocap_id] = (1.0, 0.0, 0.0, 0.0)
        mujoco.mj_forward(model, data)


def _axis_angle_quat(axis: tuple[float, float, float], angle: float) -> np.ndarray:
    half = angle / 2.0
    scale = math.sin(half)
    return np.array(
        [math.cos(half), axis[0] * scale, axis[1] * scale, axis[2] * scale],
        dtype=np.float64,
    )


def _multiply_quat(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return np.array(
        [
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ],
        dtype=np.float64,
    )
