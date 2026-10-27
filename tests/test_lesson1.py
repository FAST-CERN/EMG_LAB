import itertools
import json
import numpy as np
import pytest
from emg_lab.tasks import ROBOT, HAND, ROBOT7, HAND5, TASKS, task_from_metadata, require_task
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.storage import read_recording
from emg_lab.hand.poses import PoseMotion, POSES
from emg_lab.hand.model import HandModel, ACTIVE
from emg_lab.practice import BasicAssessment


def profile():
    return dict(device='模拟练习',sampling_rate=1000.,channel_ids=[1,2,3,4],unit='a.u.')


def test_profiles_do_not_reinterpret_old_data():
    assert task_from_metadata({}) == ROBOT
    assert task_from_metadata(HAND.metadata) == HAND
    for task in TASKS.values():
        assert task_from_metadata(task.metadata) == task
    with pytest.raises(ValueError):
        require_task(ROBOT.metadata,ROBOT7)
    with pytest.raises(ValueError):
        require_task(HAND.metadata,HAND5)


@pytest.mark.parametrize('task',[ROBOT7,HAND5])
def test_new_task_capture_random_order_and_roundtrip(tmp_path,task):
    run=CaptureRun(tmp_path,'G01','test',profile(),SignalConfig(),trial_count=3,task=task,random_order=True)
    run.feed(np.zeros((run.session_length,4),dtype='f4'))
    meta,raw,labels=read_recording(run.run_path)
    assert meta['completed_trials']==3
    assert meta['order_seed'] is not None
    assert len(labels)==3*len(task.classes)
    for trial in (1,2,3):
        assert {r['class_id'] for r in labels if r['trial']==trial}==set(range(len(task.classes)))


def test_all_hand_pose_switches_interrupt_hold_and_joint_limits():
    model=HandModel()
    for old,new in itertools.product(POSES,repeat=2):
        motion=PoseMotion()
        motion.set_command(old)
        motion.advance(5)
        assert np.allclose(motion.angles,POSES[old])
        motion.set_command(new)
        for _ in range(18):
            previous=motion.angles.copy()
            motion.advance(.02)
            model.set_angles(motion.angles)
            assert np.max(abs(motion.angles-previous))<=motion.rate*.02+1e-10
        motion.set_command(0)
        stopped=motion.angles.copy()
        motion.advance(10)
        assert np.array_equal(stopped,motion.angles)
        motion.set_command(new)
        motion.advance(8)
        assert np.allclose(motion.angles,POSES[new])
        motion.set_command(new)
        assert motion.targets==[]
    # All exported poses are valid for the actual bundled URDF.
    for angles in POSES.values():
        model.set_angles(angles)
        for name,angle in zip(ACTIVE,angles):
            lo,hi=model.model.joint(name).range
            assert lo<=angle<=hi


def test_assessment_counts_predictions_not_targets():
    labels=[dict(start_sample=3000,end_sample=6000,class_id=3,trial=1)]
    evaluation=BasicAssessment(ROBOT7,1000,400,labels=labels,source='replay')
    evaluation.feed([dict(sample_end=3500,raw_class=3,filtered_class=0),
                     dict(sample_end=3700,raw_class=3,filtered_class=0),
                     dict(sample_end=3800,raw_class=3,filtered_class=3)],6000)
    report=evaluation.report()
    assert report['command']['total']==2  # first full window crosses the exclusion edge
    assert report['command']['correct']==1
    assert report['command']['confusion_matrix'][3][0]==1
    assert report['segments'][0]['first_correct_seconds']==.8
    assert evaluation.status()['done']


def test_live_assessment_balanced_and_no_stale_output_scoring():
    evaluation=BasicAssessment(HAND5,1000,400)
    assert len(evaluation.segments)==10
    assert all(sum(s['class_id']==i for s in evaluation.segments)==2 for i in range(5))
    evaluation.feed([],60000)
    assert evaluation.report()['command']['total']==0
    assert evaluation.report()['command']['accuracy'] is None


def test_seven_robot_directions_and_switching():
    from emg_lab.physics.simulation import Simulation
    from emg_lab.physics.commands import Command
    sim=Simulation()
    for command,axis,sign in [(Command.FORWARD,0,1),(Command.BACKWARD,0,-1),
                               (Command.STRAFE_LEFT,1,1),(Command.STRAFE_RIGHT,1,-1)]:
        sim.reset()
        for _ in range(50): sim.step()
        start=sim.data.qpos[:3].copy()
        sim.set_command(command)
        for _ in range(150): sim.step()
        assert not sim.fallen
        assert sign*(sim.data.qpos[axis]-start[axis])>.15
    sim.reset()
    for command in [3,0,1,0,4,5,6,2,0]:
        sim.set_command(command)
        for _ in range(100): sim.step()
        assert not sim.fallen
    assert np.linalg.norm(sim.control_velocity)<1e-9


def test_extended_ui_targets_and_hardware_boundaries(tmp_path):
    from PySide6.QtWidgets import QApplication
    from emg_lab.app import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    for key,count in [('robot7',7),('hand5',5),('robot',4),('hand',3)]:
        window.select_task(key)
        assert window.mock_action.count()==count
        assert sum(not p.isHidden() for p in window.probabilities)==count
        assert window.task_choice.currentData()==key
        assert window.capture_settings.isAncestorOf(window.task_choice)
        choices={window.task_choice.itemData(i) for i in range(window.task_choice.count())}
        assert choices==({'robot','robot7'} if key.startswith('robot') else {'hand','hand5'})
        assert window.action_seconds.value()==5
        assert window.hand_check.isEnabled()==(key=='hand')
        assert window.dds_check.isEnabled()==(key=='robot')
    window.select_task('hand5')
    with pytest.raises(ValueError): window.connect_hand()
    window.select_task('robot7')
    with pytest.raises(ValueError): window.connect_dds()
    window.close()
