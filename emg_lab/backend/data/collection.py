"""Small reusable notes and conservative signal checks for classroom capture."""

import numpy as np

from emg_lab.backend.data.storage import read_json, write_json
from emg_lab.contracts.notes import clean_notes

NOTE_FIELDS = ("operator", "wearing", "channels", "actions")


def load_notes(root, group, task):
    path = root / ".capture_notes.json"
    try:
        return clean_notes(read_json(path).get(group, {}).get(task.selector, {}))
    except (OSError, ValueError, TypeError):
        return {}


def save_notes(root, group, task, notes):
    path = root / ".capture_notes.json"
    try:
        data = read_json(path)
    except (OSError, ValueError):
        data = {}
    data.setdefault(group, {})[task.selector] = clean_notes(notes)
    write_json(path, data)


def signal_check(raw, rate, channel_ids, age):
    """Detect exact flatlines only; no universal amplitude threshold across devices."""
    if age > 1.0:
        return "信号已中断，请检查设备连接。", True
    needed = max(2, round(rate * 2))
    if len(raw) < needed:
        return "正在检查信号，请先放松，再试做一次动作。", False
    values = np.asarray(raw[-needed:])
    flat = np.flatnonzero(np.ptp(values, axis=0) == 0)
    if len(flat):
        channels = "、".join(str(channel_ids[i]) for i in flat)
        return f"传感器 {channels} 连续 2 秒数据完全不变，请检查传感器状态与波形。", True
    return "各通道数据正在变化；请试做动作并观察波形。此检查不代表标签或佩戴一定正确。", False
