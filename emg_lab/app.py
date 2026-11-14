"""Compatibility entrypoint; implementation: emg_lab.frontend.window."""

import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emg_lab.frontend.window", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("emg_lab.frontend.window")
