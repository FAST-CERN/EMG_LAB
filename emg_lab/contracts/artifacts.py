import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .tasks import task_from_metadata


def safe_name(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")[:64]
    if not value:
        raise ValueError("名称不能为空，也不能只包含空格或句点。")
    if value.upper().split(".")[0] in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *[f"COM{i}" for i in range(1, 10)],
        *[f"LPT{i}" for i in range(1, 10)],
    }:
        value = "_" + value
    return value


def usable_record(meta):
    if meta.get("schema_version", 1) >= 2:
        return (
            meta.get("finalized", False)
            and meta.get("usable_trials", meta.get("completed_trials", 0)) > 0
        )
    return bool(meta.get("complete"))


def excluded_trials(meta):
    values = meta.get("rejected_trials", [])
    if not isinstance(values, list) or any(
        not isinstance(v, dict)
        or type(v.get("trial")) is not int
        or v["trial"] < 1
        or not isinstance(v.get("reason"), str)
        for v in values
    ):
        raise ValueError("无效动作组记录格式错误。")
    return {v["trial"] for v in values}


def record_label(meta):
    trials = (
        f"{meta.get('completed_trials', 0)} 组动作"
        if meta.get("schema_version", 1) >= 2
        else f"数据 {meta.get('round', 1)}"
    )
    suffix = (
        "" if meta.get("complete") else " [提前结束]" if usable_record(meta) else " [动作未采全]"
    )
    if meta.get("rejected_trials"):
        suffix += f" [标记无效 {len(excluded_trials(meta))} 组]"
    device = "模拟设备" if meta["device"] == "模拟练习" else meta["device"]
    return (
        f"{meta['name']} · {meta['group']} · {trials} · {device} · {meta.get('created_at', '')[:19].replace('T', ' ')}"
        + suffix
    )


@dataclass(frozen=True)
class Entry:
    kind: str
    path: Path
    meta: dict

    @property
    def task(self):
        return task_from_metadata(self.meta)

    @property
    def identity(self):
        return self.meta.get("record_id" if self.kind == "recording" else "model_id", "")

    @property
    def day(self):
        try:
            return date.fromisoformat(self.meta.get("created_at", "")[:10])
        except ValueError:
            return None
