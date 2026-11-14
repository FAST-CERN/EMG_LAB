"""Compatibility imports; GUI types are loaded only when requested."""

from importlib import import_module


def __getattr__(name):
    module = "emg_lab.frontend.robot" if name in {"RobotScene"} else "emg_lab.backend.robot.dds"
    return getattr(import_module(module), name)
