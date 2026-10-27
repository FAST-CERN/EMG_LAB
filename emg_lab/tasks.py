"""Experiment definitions shared by labels, models, evaluation and UI."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    key: str
    task_type: str
    title: str
    classes: tuple[str, ...]
    names: tuple[str, ...]
    order: tuple[int, ...]

    @property
    def selector(self):
        return next(k for k, v in TASKS.items() if v == self)

    @property
    def metadata(self):
        value=dict(target=self.key, task_type=self.task_type, classes=list(self.classes))
        if self == HAND:
            value['control_profile']=dict(version='revo2_four_finger_v1',speed_percent_per_second=HAND_RATE,
                controlled_axes=[2,3,4,5],thumb_default_degrees=[24,30],stop_behavior='hold_current_progress')
        return value


ROBOT = Task('robot', 'ROBOT_DIRECTION_4CLASS', '机器人控制',
             ('rest','left','right','forward'), ('停止','左转','右转','前进'), (3,0,1,2))
HAND = Task('hand', 'HAND_COMMAND_3CLASS', '灵巧手控制',
            ('rest','open','close'), ('停止','张开','握合'), (1,2,0))
ROBOT7 = Task('robot', 'ROBOT_DIRECTION_7CLASS', '机器人七类',
              ('rest','left','right','forward','backward','strafe_left','strafe_right'),
              ('停止','左转','右转','前进','后退','左移','右移'), (3,4,5,6,1,2,0))
HAND5 = Task('hand', 'HAND_POSE_5CLASS', '灵巧手五类姿态',
             ('rest','open','fist','point','victory'),
             ('停止保持','张开','握拳','食指指向','双指伸展'), (1,2,3,4,0))
TASKS = {'robot':ROBOT, 'hand':HAND, 'robot7':ROBOT7, 'hand5':HAND5}
HAND_RATE = 75  # percent of full finger travel per second, NOT percent of max speed


def task_from_metadata(meta):
    """Legacy files without a task identifier are robot recordings/models."""
    kind = meta.get('task_type', ROBOT.task_type)
    task = next((t for t in TASKS.values() if t.task_type == kind), None)
    if task is None or meta.get('target',task.key) != task.key:
        raise ValueError('无法识别数据或模型的实验目标。')
    if 'classes' in meta and meta['classes'] != list(task.classes):
        raise ValueError('类别顺序与实验目标不一致，请重新选择数据或模型。')
    return task


def require_task(meta, task):
    if task_from_metadata(meta) != task:
        raise ValueError(f'当前是{task.title}，不能使用另一实验目标的数据或模型。')
