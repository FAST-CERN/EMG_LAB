"""Compatibility entrypoint; implementation: emg_lab.backend.data.transfer."""

import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emg_lab.backend.data.transfer", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("emg_lab.backend.data.transfer")
