"""Shared Qt presentation components and explicit page-builder imports."""

from __future__ import annotations

import sys as sys
import time as time
from pathlib import Path as Path

from PySide6 import QtCore as QtCore
from PySide6 import QtGui as QtGui
from PySide6 import QtWidgets as W

from emg_lab.contracts.artifacts import record_label as record_label
from emg_lab.contracts.artifacts import safe_name as safe_name
from emg_lab.contracts.artifacts import usable_record as usable_record
from emg_lab.contracts.competition import REASONS as REASONS
from emg_lab.contracts.competition import RaceConfig as RaceConfig
from emg_lab.contracts.config import SignalConfig as SignalConfig
from emg_lab.contracts.control import speed_summary as speed_summary
from emg_lab.contracts.events import DeviceConfig as DeviceConfig
from emg_lab.contracts.events import TrainingRequest as TrainingRequest
from emg_lab.contracts.presentation import evaluation_details as evaluation_details
from emg_lab.contracts.tasks import HAND as HAND
from emg_lab.contracts.tasks import HAND5 as HAND5
from emg_lab.contracts.tasks import HAND_RATE as HAND_RATE
from emg_lab.contracts.tasks import ROBOT as ROBOT
from emg_lab.contracts.tasks import ROBOT7 as ROBOT7
from emg_lab.contracts.tasks import TASKS as TASKS
from emg_lab.contracts.tasks import require_task as require_task
from emg_lab.contracts.timing import ACTION_SECONDS as ACTION_SECONDS
from emg_lab.contracts.timing import PREPARE_SECONDS as PREPARE_SECONDS
from emg_lab.contracts.timing import REST_SECONDS as REST_SECONDS
from emg_lab.contracts.timing import preparation_countdown as preparation_countdown
from emg_lab.contracts.version import VERSION as VERSION
from emg_lab.frontend.collection import CollectionNotesDialog as CollectionNotesDialog
from emg_lab.frontend.hand_scene import HandScene as HandScene
from emg_lab.frontend.hand_scene import HandView as HandView
from emg_lab.frontend.library import LibraryWidget as LibraryWidget
from emg_lab.frontend.robot import RobotScene as RobotScene
from emg_lab.frontend.theme import apply_theme as apply_theme
from emg_lab.frontend.waveform import WaveformPreview as WaveformPreview
from emg_lab.frontend.widgets import card as card
from emg_lab.frontend.widgets import field as field
from emg_lab.frontend.widgets import fields as fields
from emg_lab.frontend.widgets import text_label as text_label
from emg_lab.paths import DATA as DATA_ROOT
from emg_lab.paths import ROOT as ROOT

CLASS_NAMES = list(ROBOT.names)


class Bridge(QtCore.QObject):
    device_event = QtCore.Signal(dict)
    train_event = QtCore.Signal(dict)
    application_event = QtCore.Signal(object)


def label(text, title=False):
    item = W.QLabel(text)
    item.setWordWrap(True)
    if title:
        item.setObjectName("heading")
    return item


def button(text, action, primary=False):
    item = W.QPushButton(text)
    item.clicked.connect(action)
    item.setMinimumHeight(24)
    item.setCursor(QtCore.Qt.PointingHandCursor)
    if text.startswith(("停止", "提前结束")):
        item.setObjectName("danger")
    if primary:
        item.setObjectName("primary")
    return item


def row(*items):
    layout = W.QHBoxLayout()
    layout.setSpacing(10)
    for item in items:
        if isinstance(item, str):
            text = label(item)
            text.setSizePolicy(W.QSizePolicy.Maximum, W.QSizePolicy.Preferred)
            layout.addWidget(text)
        elif isinstance(item, W.QWidget):
            layout.addWidget(item)
        else:
            layout.addStretch(item)
    return layout


def details(title):
    section = W.QWidget()
    layout = W.QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    toggle = W.QToolButton()
    toggle.setText(title)
    toggle.setCheckable(True)
    toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    toggle.setArrowType(QtCore.Qt.RightArrow)
    content = W.QWidget()
    content.setVisible(False)
    toggle.toggled.connect(content.setVisible)
    toggle.toggled.connect(
        lambda checked: toggle.setArrowType(
            QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow
        )
    )
    layout.addWidget(toggle)
    layout.addWidget(content)
    section.toggle = toggle
    return section, W.QVBoxLayout(content)


def device_name(value):
    return "模拟设备" if value == "模拟练习" else value


def available_devices(platform_name=None):
    """真机设备仅 Windows 全功能档可见（ADR 0002）；其余平台只提供模拟练习。"""
    devices = [("Cometa", "Cometa"), ("Delsys", "Delsys"), ("模拟设备（无需硬件）", "模拟练习")]
    return devices if (platform_name or sys.platform) == "win32" else [devices[-1]]


__all__ = [
    "ACTION_SECONDS",
    "Bridge",
    "CLASS_NAMES",
    "CollectionNotesDialog",
    "DATA_ROOT",
    "DeviceConfig",
    "HAND",
    "HAND5",
    "HAND_RATE",
    "HandScene",
    "HandView",
    "LibraryWidget",
    "PREPARE_SECONDS",
    "Path",
    "QtCore",
    "QtGui",
    "REASONS",
    "REST_SECONDS",
    "ROBOT",
    "ROBOT7",
    "ROOT",
    "RaceConfig",
    "RobotScene",
    "SignalConfig",
    "TASKS",
    "TrainingRequest",
    "VERSION",
    "W",
    "WaveformPreview",
    "apply_theme",
    "available_devices",
    "button",
    "card",
    "details",
    "device_name",
    "evaluation_details",
    "field",
    "fields",
    "label",
    "preparation_countdown",
    "record_label",
    "require_task",
    "row",
    "safe_name",
    "speed_summary",
    "sys",
    "text_label",
    "time",
    "usable_record",
]
