"""Compatibility entrypoint; implementation: emg_lab.frontend.help."""

import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("emg_lab.frontend.help", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("emg_lab.frontend.help")
