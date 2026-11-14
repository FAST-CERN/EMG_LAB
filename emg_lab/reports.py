"""Compatibility imports; GUI types are loaded only when requested."""

from importlib import import_module


def __getattr__(name):
    module = (
        "emg_lab.frontend.reports" if name in {"ReportsDialog"} else "emg_lab.backend.data.reports"
    )
    return getattr(import_module(module), name)
