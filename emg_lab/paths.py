"""Project/resource paths shared by source, offline distribution and subprocesses."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FRONTEND = ROOT / "emg_lab" / "frontend"
DOCS = ROOT / "docs"
DATA = ROOT / "data"
LOCAL = ROOT / "local"
