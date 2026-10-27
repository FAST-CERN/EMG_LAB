"""Classroom poses from BrainCo's official ROS2 Gazebo examples.

Source order is metacarpal, proximal, index, middle, ring, pinky; our ACTIVE
order is proximal, metacarpal, index, middle, ring, pinky. Units: radians.
These are visual/kinematic examples, not physical collision certification.
"""
import numpy as np

SOURCE_URL = "https://github.com/BrainCoTech/brainco_hand_ros2/blob/master/brainco_gazebo/README.md"
POSES = {
    1: np.array([.1,0.,0.,0.,0.,0.]),
    2: np.array([.8,.3,1.2,1.2,1.2,1.2]),
    3: np.array([.8,.3,0.,1.2,1.2,1.2]),
    4: np.array([.8,.3,0.,0.,1.2,1.2]),
}
MAX_RADIANS = np.deg2rad([60,89,81,81,81,81])


class PoseMotion:
    """One pose owner: latest target wins, repeats do not restart, STOP holds.

    Pose changes first extend the four fingers, then reposition the thumb,
    then flex fingers into the final pose. Motion starts from the current
    interpolated state, so interruption never teleports or queues old actions.
    """
    def __init__(self):
        self.angles = POSES[1].copy()
        self.command = 0
        self.targets = []
        self.rate = .9  # rad/s, bounded visual motion

    def set_command(self, command):
        if command not in (0,1,2,3,4):
            raise ValueError("未知的手部预设姿态。")
        if command == self.command:
            return
        self.command = int(command)
        self.targets = []
        if command == 0:
            return
        final = POSES[command].copy()
        extend = self.angles.copy()
        extend[2:] = 0
        thumb = final.copy()
        thumb[2:] = 0
        self.targets = [extend, thumb, final]

    def advance(self, dt):
        remaining = max(0., float(dt))
        while self.targets and remaining > 0:
            target = self.targets[0]
            delta = target-self.angles
            duration = float(np.max(np.abs(delta)))/self.rate
            if duration <= remaining:
                self.angles = self.targets.pop(0).copy()
                remaining -= duration
            else:
                self.angles += delta*(remaining/duration)
                break
        return self.progress

    @property
    def progress(self):
        return float(np.mean(self.angles[2:]/MAX_RADIANS[2:]))

    @progress.setter
    def progress(self, value):
        self.angles = POSES[1].copy()
        self.angles[2:] = MAX_RADIANS[2:]*np.clip(value,0,1)
        self.targets = []
        self.command = 0

    @property
    def positions(self):
        return np.rint(self.angles/MAX_RADIANS*1000).astype(int).tolist()
