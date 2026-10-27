"""Scene changes must preserve physical control and the source cue transitions."""
from types import SimpleNamespace
import math
import numpy as np
import mujoco
from emg_lab.physics.camera import FollowCamera
from emg_lab.physics.environment import load_scene
from emg_lab.physics.simulation import ROOT
from emg_lab.physics.ground_cue_presenter import GroundCuePresenter


def test_background_preserves_robot_dynamics_and_contact_floor():
    original = mujoco.MjModel.from_xml_path(str(ROOT/'assets/g1/g1.xml'))
    scene = load_scene(ROOT/'assets')
    assert (scene.nq, scene.nv, scene.nu) == (original.nq, original.nv, original.nu)
    for field in ('body_mass', 'body_inertia', 'body_ipos', 'body_iquat'):
        np.testing.assert_array_equal(getattr(scene, field)[:original.nbody], getattr(original, field))
    for field in ('dof_armature', 'dof_damping', 'dof_frictionloss', 'actuator_trnid', 'jnt_range'):
        np.testing.assert_array_equal(getattr(scene, field), getattr(original, field))
    for field in ('friction', 'solref', 'solimp', 'condim', 'pos'):
        np.testing.assert_array_equal(getattr(scene.geom('floor'), field), getattr(original.geom('floor'), field))
    # Decorative scenery never collides with the robot.
    for i in range(scene.ngeom):
        if (scene.geom(i).name or '').startswith('outdoor_'):
            assert scene.geom_contype[i] == scene.geom_conaffinity[i] == 0


def test_original_follow_camera_and_heading_wrap():
    camera = SimpleNamespace(lookat=np.zeros(3))
    follow = FollowCamera()
    qpos = np.array([1., 2., .79, 1., 0., 0., 0.])
    follow.update(camera, qpos, .04)
    np.testing.assert_allclose(camera.lookat, [1., 2., .75])
    assert (camera.distance, camera.elevation, camera.azimuth) == (2.5, -20., 0.)
    qpos[0] = 2.
    yaw = math.radians(179.)
    qpos[3:7] = [math.cos(yaw/2), 0., 0., math.sin(yaw/2)]
    follow.reset()
    follow.update(camera, qpos, .04)
    yaw = math.radians(-179.)
    qpos[3:7] = [math.cos(yaw/2), 0., 0., math.sin(yaw/2)]
    qpos[0] = 3.
    follow.update(camera, qpos, .04)
    assert 179. < camera.azimuth < 181.  # never rotates the long way around
    assert 2. < camera.lookat[0] < 3.  # smoothed translation


def test_preparation_to_active_cues_append_without_erasing_world_or_moving_robot():
    model = load_scene(ROOT/'assets')
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    presenter = GroundCuePresenter(model)
    scene = mujoco.MjvScene(model, maxgeom=1000)
    camera = mujoco.MjvCamera()
    options = mujoco.MjvOption()
    before = data.qpos.copy()
    for command in range(7):
        for active, countdown, additional in [(False, 3, 2), (False, 0, 2), (True, None, 2)]:
            mujoco.mjv_updateScene(model, data, options, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene)
            world_geoms = scene.ngeom
            presenter.update(scene, camera, data, command, active, countdown)
            assert scene.ngeom == world_geoms+additional
            cue = scene.geoms[world_geoms]
            assert cue.type == (mujoco.mjtGeom.mjGEOM_MESH if active else mujoco.mjtGeom.mjGEOM_PLANE)
            if not active:
                assert scene.geoms[world_geoms+1].matid == model.mat(f'countdown_{countdown}_mat').id
    mujoco.mjv_updateScene(model, data, options, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene)
    count = scene.ngeom
    presenter.update(scene, camera, data, None, False)
    assert scene.ngeom == count  # no experimental cue in open mode
    np.testing.assert_array_equal(data.qpos, before)
