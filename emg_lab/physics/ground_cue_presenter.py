"""Demo-compatible arrow/pause marker drawn below the virtual robot."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .commands import Command as DirectionCommand


GROUND_COLORS = {
    DirectionCommand.FORWARD: np.array([0.12, 0.90, 1.00, 0.98], np.float32),
    DirectionCommand.STOP: np.array([1.00, 0.18, 0.30, 0.98], np.float32),
    DirectionCommand.RIGHT: np.array([0.75, 0.30, 1.00, 0.98], np.float32),
    DirectionCommand.LEFT: np.array([1.00, 0.55, 0.12, 0.98], np.float32),
    DirectionCommand.BACKWARD: np.array([0.98, 0.78, 0.12, 0.98], np.float32),
    DirectionCommand.STRAFE_LEFT: np.array([0.12, 0.94, 0.65, 0.98], np.float32),
    DirectionCommand.STRAFE_RIGHT: np.array([0.25, 0.65, 1.00, 0.98], np.float32),
}
GROUND_MESHES = {
    DirectionCommand.FORWARD: "ground_cue_forward",
    DirectionCommand.STOP: "ground_cue_idle",
    DirectionCommand.RIGHT: "ground_cue_right",
    DirectionCommand.LEFT: "ground_cue_left",
    DirectionCommand.BACKWARD: "ground_cue_forward",
    DirectionCommand.STRAFE_LEFT: "ground_cue_forward",
    DirectionCommand.STRAFE_RIGHT: "ground_cue_forward",
}
FORWARD_CENTER_OFFSET_M = 0.45
GROUND_Z_M = 0.026
TURN_PLACEMENT_ANGLE_RAD = math.radians(35.0)

# 准备阶段文字提示纹理：与 assets/model/cue_*.png 对应（scene_direction_labelling.xml 里声明）。
TEXT_TEXTURES = {
    DirectionCommand.FORWARD: "cue_forward",
    DirectionCommand.STOP: "cue_rest",
    DirectionCommand.RIGHT: "cue_right",
    DirectionCommand.LEFT: "cue_left",
    DirectionCommand.BACKWARD: "cue_backward",
    DirectionCommand.STRAFE_LEFT: "cue_strafe_left",
    DirectionCommand.STRAFE_RIGHT: "cue_strafe_right",
}
TEXT_ABOVE_GROUND_M = 1.5   # 文字平面悬浮高度（机器人头顶上方）
TEXT_HALF_WIDTH_M = 0.45    # 文字平面半宽（全宽 0.9m）

# 倒计时数字平面：位于提示文字右侧并排、紧贴无间隔，高度与文字徽章完全一致。
# 数字材质名约定 = "countdown_" + 数字 + "_mat"（countdown_textures.py 注入临时 XML）。


@dataclass(frozen=True, slots=True)
class MeshVisual:
    dataid: int
    size: np.ndarray
    offset: np.ndarray
    rotation: np.ndarray


class GroundCuePresenter:
    """Append the source trial cue to an offscreen renderer scene.

    Preparation shows a Chinese text badge and countdown. Active intervals show
    both the action name and a body-relative ground marker for all seven classes.
    Complete and open phases draw nothing.
    """

    def __init__(self, model: object) -> None:
        self._model = model
        self._mujoco = _mujoco()
        self._meshes = {
            cue: _mesh_visual(self._mujoco, model, mesh_name)
            for cue, mesh_name in GROUND_MESHES.items()
        }
        self._material_ids: dict[DirectionCommand, int] = {}
        self._texture_sizes: dict[DirectionCommand, tuple[int, int]] = {}
        self._action_material_ids = {}
        self._action_sizes = {}
        for cue, tex_name in TEXT_TEXTURES.items():
            mat_id = model.mat(f"{tex_name}_mat").id  # 材质名约定 = 纹理名 + "_mat"
            self._material_ids[cue] = mat_id
            tex_id = model.tex(tex_name).id
            self._texture_sizes[cue] = (int(model.tex_width[tex_id]), int(model.tex_height[tex_id]))
            action_name = tex_name.replace('cue_', 'action_')
            self._action_material_ids[cue] = model.mat(action_name+'_mat').id
            tex_id = model.tex(action_name).id
            self._action_sizes[cue] = (int(model.tex_width[tex_id]), int(model.tex_height[tex_id]))
        # 倒计时数字材质按需解析（只有注入过数字贴图的模型才有；缺失时静默跳过）。
        self._countdown_materials: dict[int, int | None] = {}
        self._countdown_sizes: dict[int, tuple[int, int]] = {}

    def update(
        self,
        scene: object,
        cam: object,
        data: object,
        cue: DirectionCommand | int | None,
        active: bool,
        countdown: int | None = None,
    ) -> None:
        # renderer.update_scene already populated the world; append, never erase it.
        if cue is None:
            return
        command = DirectionCommand(cue)
        if active:
            self._draw_ground(scene, data, command)
        self._draw_text(scene, cam, data, command, active=active)
        if countdown is not None:
            # 数字徽章高度精确等于当前提示文字的徽章高度（取文字纹理宽高比）
            tex_w, tex_h = self._texture_sizes[command]
            text_half_h = TEXT_HALF_WIDTH_M * (tex_h / tex_w) if tex_w else TEXT_HALF_WIDTH_M
            self._draw_countdown(scene, cam, data, countdown, text_half_h)

    def _draw_ground(self, scene: object, data: object, cue: DirectionCommand) -> None:
        yaw_rotation = _rotation_z(_yaw_from_quat(data.qpos[3:7]))
        cue_angle = {
            DirectionCommand.LEFT: TURN_PLACEMENT_ANGLE_RAD,
            DirectionCommand.RIGHT: -TURN_PLACEMENT_ANGLE_RAD,
            DirectionCommand.BACKWARD: math.pi,
            DirectionCommand.STRAFE_LEFT: math.pi / 2,
            DirectionCommand.STRAFE_RIGHT: -math.pi / 2,
        }.get(cue, 0.0)
        cue_rotation = yaw_rotation @ _rotation_z(cue_angle)
        ground_rotation = cue_rotation @ _rotation_x(-math.pi / 2.0)
        local_offset = np.array({
            DirectionCommand.FORWARD: (FORWARD_CENTER_OFFSET_M,0.,0.),
            DirectionCommand.BACKWARD: (-.05,0.,0.),
            DirectionCommand.STRAFE_LEFT: (0.,.65,0.),
            DirectionCommand.STRAFE_RIGHT: (0.,-.65,0.),
        }.get(cue,(0.,0.,0.)))
        origin = np.array([data.qpos[0], data.qpos[1], GROUND_Z_M])
        origin += yaw_rotation @ local_offset
        mesh = self._meshes[cue]
        position = origin + ground_rotation @ mesh.offset
        rotation = ground_rotation @ mesh.rotation
        self._add_mesh(scene, mesh, position, rotation, GROUND_COLORS[cue])

    def _add_mesh(self, scene: object, mesh: MeshVisual, position: np.ndarray, rotation: np.ndarray, color: np.ndarray) -> None:
        if scene.ngeom >= len(scene.geoms):
            return
        geom = scene.geoms[scene.ngeom]
        self._mujoco.mjv_initGeom(
            geom,
            self._mujoco.mjtGeom.mjGEOM_MESH,
            mesh.size,
            position,
            np.ascontiguousarray(rotation, dtype=np.float64).reshape(9),
            color,
        )
        geom.dataid = mesh.dataid
        geom.category = self._mujoco.mjtCatBit.mjCAT_DECOR
        geom.emission = 0.20
        geom.specular = 0.0
        scene.ngeom += 1

    def _draw_text(self, scene: object, cam: object, data: object, cue: DirectionCommand, *, active=False) -> None:
        """Keep the action readable even when the ground marker is occluded."""
        mat_id = (self._action_material_ids if active else self._material_ids)[cue]
        tex_w, tex_h = (self._action_sizes if active else self._texture_sizes)[cue]
        half_w = TEXT_HALF_WIDTH_M
        half_h = half_w * (tex_h / tex_w) if tex_w else half_w
        position = np.array([data.qpos[0], data.qpos[1], TEXT_ABOVE_GROUND_M], dtype=np.float64)
        self._add_plane(scene, mat_id, half_w, half_h, position, _billboard_rotation(cam))

    def _draw_countdown(
        self,
        scene: object,
        cam: object,
        data: object,
        digit: int,
        text_half_h: float,
    ) -> None:
        """画倒计时数字平面：提示文字右侧并排、紧贴无间隔，高度与文字一致。

        数字材质可能不存在（倒计时贴图未注入/生成失败），此时静默跳过，
        不影响提示文字本身的显示。
        """
        mat_id = self._countdown_material(scene, digit)
        if mat_id is None:
            return
        tex_w, tex_h = self._countdown_sizes[digit]
        half_h = text_half_h
        half_w = half_h * (tex_w / tex_h) if tex_h else half_h
        rotation = _billboard_rotation(cam)
        # 偏移量 = 文字半宽 + 数字半宽：两个徽章背景紧贴（无间隔）。
        # 方向取 -rotation[:,0]：实测中该方向才是镜头所见"右侧"
        # （MuJoCo 的 user_scn 平面左右镜像渲染使 rotation[:,0] 指向屏幕左侧）。
        offset = TEXT_HALF_WIDTH_M + half_w
        position = np.array([data.qpos[0], data.qpos[1], TEXT_ABOVE_GROUND_M], dtype=np.float64)
        position -= rotation[:, 0] * offset
        self._add_plane(scene, mat_id, half_w, half_h, position, rotation)

    def _countdown_material(self, scene: object, digit: int) -> int | None:
        if digit in self._countdown_materials:
            return self._countdown_materials[digit]
        model = self._model
        try:
            mat_id = model.mat(f"countdown_{digit}_mat").id
            tex_id = model.tex(f"countdown_{digit}").id
            self._countdown_sizes[digit] = (int(model.tex_width[tex_id]), int(model.tex_height[tex_id]))
        except KeyError:
            mat_id = None
        self._countdown_materials[digit] = mat_id
        return mat_id

    def _add_plane(
        self,
        scene: object,
        mat_id: int,
        half_w: float,
        half_h: float,
        position: np.ndarray,
        rotation: np.ndarray,
    ) -> None:
        if scene.ngeom >= len(scene.geoms):
            return
        geom = scene.geoms[scene.ngeom]
        self._mujoco.mjv_initGeom(
            geom,
            self._mujoco.mjtGeom.mjGEOM_PLANE,
            np.array([half_w, half_h, 0.01], dtype=np.float64),
            position,
            np.ascontiguousarray(rotation, dtype=np.float64).reshape(9),
            np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32),
        )
        geom.matid = mat_id
        geom.emission = 1.0
        geom.specular = 0.0
        geom.category = self._mujoco.mjtCatBit.mjCAT_DECOR
        scene.ngeom += 1


def _mesh_visual(mujoco: object, model: object, mesh_name: str) -> MeshVisual:
    try:
        mesh_id = model.mesh(mesh_name).id
    except KeyError as error:
        raise ValueError(f"scene is missing ground cue mesh: {mesh_name}") from error
    address = int(model.mesh_vertadr[mesh_id])
    count = int(model.mesh_vertnum[mesh_id])
    vertices = np.asarray(model.mesh_vert[address : address + count], dtype=np.float64)
    matrix = np.empty(9, dtype=np.float64)
    mujoco.mju_quat2Mat(matrix, np.asarray(model.mesh_quat[mesh_id], dtype=np.float64))
    return MeshVisual(
        dataid=2 * int(mesh_id),
        size=np.max(np.abs(vertices), axis=0),
        offset=np.asarray(model.mesh_pos[mesh_id], dtype=np.float64).copy(),
        rotation=matrix.reshape(3, 3),
    )


def _mujoco() -> object:
    import mujoco
    return mujoco


def _rotation_x(angle: float) -> np.ndarray:
    return np.array([[1.0, 0.0, 0.0], [0.0, math.cos(angle), -math.sin(angle)], [0.0, math.sin(angle), math.cos(angle)]], np.float64)


def _rotation_z(angle: float) -> np.ndarray:
    return np.array([[math.cos(angle), -math.sin(angle), 0.0], [math.sin(angle), math.cos(angle), 0.0], [0.0, 0.0, 1.0]], np.float64)


def _billboard_rotation(cam: object) -> np.ndarray:
    """让竖直平面始终面向自由相机（绕 Z 的圆柱 billboard）。

    用相机 azimuth 算出朝向相机的水平法线；平面保持竖直，文字不倒。
    若文字上下颠倒，把 up 取反；若左右镜像，把 right 取反。
    """
    az = math.radians(float(cam.azimuth))
    right = np.array([-math.sin(az), math.cos(az), 0.0])
    up = np.array([0.0, 0.0, 1.0])
    normal = np.array([math.cos(az), math.sin(az), 0.0])
    return np.column_stack([right, up, normal])


def _yaw_from_quat(quaternion: np.ndarray) -> float:
    w, x, y, z = quaternion
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
