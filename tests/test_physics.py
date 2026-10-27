import math
import unittest
import numpy as np
from emg_lab.physics.commands import Command, CommandSettings
from emg_lab.physics.policy import DEFAULT
from emg_lab.physics.simulation import Simulation


class CommandTests(unittest.TestCase):
    def test_four_commands_and_invalid_settings(self):
        self.assertEqual(CommandSettings().velocity(Command.FORWARD),(.6,0.,0.))
        self.assertEqual(CommandSettings().velocity(Command.LEFT),(0.,0.,1.))
        settings = CommandSettings(.4,.6)
        self.assertEqual(settings.velocity(Command.FORWARD),(.4,0.,0.))
        self.assertEqual(settings.velocity(Command.LEFT),(0.,0.,.6))
        self.assertEqual(settings.velocity(Command.RIGHT),(0.,0.,-.6))
        self.assertEqual(settings.velocity(Command.STOP),(0.,0.,0.))
        for value in (float('nan'),float('inf'),-1.,1.):
            with self.assertRaises(ValueError):
                CommandSettings(value,.5)
        with self.assertRaises(ValueError):
            settings.velocity(10)


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation()

    def advance(self, seconds):
        statuses = []
        for _ in range(round(seconds/.02)):
            status = self.sim.step()
            self.assertFalse(status['fallen'])
            self.assertTrue(np.isfinite(self.sim.data.qpos).all())
            statuses.append(status)
        return statuses

    def test_observation_history_layout(self):
        policy = self.sim.policy
        qpos = self.sim.data.qpos.copy()
        qpos[7:] = DEFAULT+.01
        qvel = np.ones(35)*.2
        policy.action[:] = .3
        obs = policy.observation(qpos,qvel,[0,0,-1],[.2,0,.4])[0]
        np.testing.assert_array_equal(obs[:-86],0.)
        np.testing.assert_allclose(obs[-86:-83],[.4,0,.2])
        np.testing.assert_allclose(obs[-86+13:-86+42],.01)
        np.testing.assert_allclose(obs[-86+42:-86+71],.01)
        np.testing.assert_allclose(obs[-15:],.3)

    def test_standing_then_four_commands_then_stop(self):
        self.advance(3)
        start = self.sim.data.qpos[:2].copy()
        self.sim.set_command(Command.FORWARD)
        self.advance(5)
        self.assertGreater(self.sim.data.qpos[0]-start[0],.7)
        self.assertLess(abs(self.sim.data.qpos[1]-start[1]),.15)
        self.sim.set_command(Command.STOP)
        stationary = self.advance(3)
        self.assertEqual(self.sim.policy.last_policy,'Balance')
        self.assertLess(abs(np.mean([s['forward_actual'] for s in stationary[-50:]])),.03)
        for command,sign in [(Command.LEFT,1),(Command.RIGHT,-1)]:
            self.sim.set_command(command)
            turning = self.advance(4)
            self.assertGreater(sign*np.mean([s['yaw_actual'] for s in turning[-100:]]),.15)
            self.sim.set_command(Command.STOP)
            stopped = self.advance(2)
            self.assertLess(abs(np.mean([s['yaw_actual'] for s in stopped[-50:]])),.06)

    def test_slider_limits_and_live_changes(self):
        self.advance(2)
        for settings in (CommandSettings(.1,.1),CommandSettings(.6,.8)):
            for command in (Command.FORWARD,Command.LEFT,Command.RIGHT,Command.STOP):
                self.sim.set_command(command,settings)
                self.advance(3)

    def test_reset_clears_history_motion_and_time(self):
        self.advance(1)
        self.sim.set_command(Command.FORWARD)
        self.advance(2)
        self.sim.reset()
        self.assertEqual(self.sim.command,Command.STOP)
        self.assertEqual(self.sim.data.time,0.)
        np.testing.assert_array_equal(self.sim.policy.action,0.)
        np.testing.assert_array_equal(self.sim.data.qvel,0.)
        self.advance(3)

    def test_fall_does_not_teleport_or_continue_walking(self):
        # An injected bad state checks the guard; runtime movement never uses qpos writes.
        self.sim.data.qpos[2] = .3
        status = self.sim.step()
        self.assertTrue(status['fallen'])
        self.assertEqual(self.sim.command,Command.STOP)
        t = self.sim.data.time
        self.sim.step()
        self.assertEqual(self.sim.data.time,t)


if __name__=='__main__':
    unittest.main()
