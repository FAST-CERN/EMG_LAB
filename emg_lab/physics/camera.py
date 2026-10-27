"""The source host's third-person camera, following root position and heading."""
import math
import numpy as np


class FollowCamera:
    def __init__(self):
        self.reset()

    def reset(self):
        self.lookat = self.azimuth = None

    def update(self, camera, qpos, dt):
        w, x, y, z = qpos[3:7]
        yaw = math.degrees(math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z)))
        target = np.array([qpos[0], qpos[1], .75])
        alpha = 1. if self.lookat is None else 1-math.exp(-max(dt, 0.)/.20)
        self.lookat = target if self.lookat is None else self.lookat+alpha*(target-self.lookat)
        self.azimuth = yaw if self.azimuth is None else self.azimuth+alpha*((yaw-self.azimuth+180.)%360.-180.)
        camera.lookat[:] = self.lookat
        camera.azimuth = self.azimuth
        camera.elevation = -20.
        camera.distance = 2.5
