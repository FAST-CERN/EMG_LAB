"""Compatibility imports; GUI types are loaded only when requested."""

from importlib import import_module


def __getattr__(name):
    module = (
        "emg_lab.frontend.collection"
        if name in {"CollectionNotesDialog"}
        else "emg_lab.backend.data.collection"
    )
    return getattr(import_module(module), name)
