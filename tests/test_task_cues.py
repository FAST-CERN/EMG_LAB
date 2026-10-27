import math
import numpy as np
import pytest
from emg_lab.physics.commands import Command
from emg_lab.physics.ground_cue_presenter import GroundCuePresenter
from emg_lab.physics.simulation import Simulation

def test_all_seven_cues_render_in_preparation_and_action():
    import mujoco
    sim=Simulation();presenter=GroundCuePresenter(sim.model)
    scene=mujoco.MjvScene(sim.model,maxgeom=100);camera=mujoco.MjvCamera()
    for command in Command:
        for active in (False,True):
            scene.ngeom=0;presenter.update(scene,camera,sim.data,command,active,None if active else 3)
            assert scene.ngeom==2
            assert scene.geoms[0].matid>=0 if not active else scene.geoms[1].matid>=0
            if active:assert scene.geoms[0].type==mujoco.mjtGeom.mjGEOM_MESH

@pytest.mark.parametrize('yaw',[0.,math.pi/2])
def test_translation_arrows_follow_body_frame_and_point_in_command_direction(yaw):
    import mujoco
    sim=Simulation();sim.data.qpos[3:7]=[math.cos(yaw/2),0,0,math.sin(yaw/2)]
    scene=mujoco.MjvScene(sim.model,maxgeom=10);presenter=GroundCuePresenter(sim.model)
    rotation=np.array([[math.cos(yaw),-math.sin(yaw)],[math.sin(yaw),math.cos(yaw)]])
    for command,direction in [(Command.FORWARD,[1,0]),(Command.BACKWARD,[-1,0]),(Command.STRAFE_LEFT,[0,1]),(Command.STRAFE_RIGHT,[0,-1])]:
        scene.ngeom=0;presenter._draw_ground(scene,sim.data,command)
        geom=scene.geoms[0];mesh=presenter._meshes[command]
        world_rotation=np.asarray(geom.mat).reshape(3,3)@mesh.rotation.T
        np.testing.assert_allclose(world_rotation[:2,0],rotation@direction,atol=1e-6)
        assert np.dot(geom.pos[:2]-sim.data.qpos[:2],rotation@direction)>0

def test_task_selectors_sync_filter_models_and_accept_registered_new_scheme(tmp_path,monkeypatch):
    from PySide6 import QtWidgets as W
    from emg_lab.app import MainWindow,configure_app
    from emg_lab.tasks import TASKS,Task,ROBOT,ROBOT7
    from emg_lab.storage import write_json
    app=W.QApplication.instance() or W.QApplication([]);configure_app(app)
    for task in (ROBOT,ROBOT7):
        folder=tmp_path/'G01/models'/task.selector;folder.mkdir(parents=True)
        (folder/'model.onnx').write_bytes(b'test catalogue placeholder')
        write_json(folder/'metadata.json',dict(task.metadata,group='G01',name=task.selector,model_id=task.selector,complete=True,signal_type='emg',created_at='2026-10-26T12:00:00',device='模拟练习',channel_ids=[1,2,3,4]))
    window=MainWindow(tmp_path);window.timer.stop()
    try:
        window.training_task_choice.setCurrentIndex(window.training_task_choice.findData('robot7'))
        assert window.task==ROBOT7
        assert all(c.currentData()=='robot7' for c in (window.task_choice,window.training_task_choice,window.inference_task_choice))
        assert window.models.count()==1 and 'robot7' in window.models.currentText()
        window.inference_task_choice.setCurrentIndex(window.inference_task_choice.findData('robot'))
        assert window.task==ROBOT and window.models.count()==1 and 'robot7' not in window.models.currentText()
        custom=Task('robot','TEST_ROBOT_8','学生八类',ROBOT7.classes+('custom',),ROBOT7.names+('自定义',),tuple(range(8)))
        monkeypatch.setitem(TASKS,'student8',custom)
        window.select_task('student8')
        assert all(c.currentData()=='student8' for c in (window.task_choice,window.training_task_choice,window.inference_task_choice))
        assert window.mock_action.count()==8 and len(window.probabilities)>=8
        assert window.probabilities[7].format()=='自定义  %p%'
        window.training=object();window.update_controls()
        assert not window.training_task_choice.isEnabled() and not window.inference_task_choice.isEnabled()
    finally:
        window.training=None;window.close()
