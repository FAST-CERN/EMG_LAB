"""Capture-only conditions, independent of robot commands and Qt."""

import math
from copy import deepcopy

CUSTOM_CAPTURE = "EMG_CUSTOM_CAPTURE_V1"
MAX_CONDITIONS = 64
CONDITION_FIELDS = ("name", "body_part", "effort", "save_name", "notes")


def is_custom_capture(meta):
    return meta.get("task_type") == CUSTOM_CAPTURE


def validate_plan(value, channel_ids=None):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("采集方案版本不正确。")
    plan = deepcopy(value)
    rows = plan.get("conditions")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CONDITIONS:
        raise ValueError(f"请配置 1–{MAX_CONDITIONS} 个采集条件。")
    ids = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("动作配置格式错误。")
        identity = row.get("id")
        if not isinstance(identity, str) or not identity or len(identity) > 80:
            raise ValueError("动作缺少稳定编号。")
        ids.append(identity)
        for key in CONDITION_FIELDS:
            if not isinstance(row.get(key, ""), str) or len(row.get(key, "")) > 2000:
                raise ValueError("动作名称或备注格式错误。")
            row[key] = row.get(key, "").strip()
        if not row["name"]:
            raise ValueError("每个动作都需要填写名称。")
        row["save_name"] = row["save_name"] or row["name"]
    selected = plan.get("selected_ids", ids)
    if (
        len(ids) != len(set(ids))
        or not isinstance(selected, list)
        or not selected
        or any(not isinstance(i, str) or i not in ids for i in selected)
        or len(selected) != len(set(selected))
    ):
        raise ValueError("请选择不重复的有效动作。")
    plan["selected_ids"] = selected
    for key in ("operator", "wearing", "notes"):
        if not isinstance(plan.get(key, ""), str) or len(plan.get(key, "")) > 2000:
            raise ValueError("采集记录格式错误。")
        plan[key] = plan.get(key, "").strip()
    channels = plan.get("channels", [])
    if not isinstance(channels, list) or any(not isinstance(c, dict) for c in channels):
        raise ValueError("通道记录格式错误。")
    recorded = [c.get("channel_id") for c in channels]
    if any(type(i) is not int for i in recorded) or len(set(recorded)) != len(recorded):
        raise ValueError("通道编号重复或无效。")
    for channel in channels:
        for key in ("muscle", "notes"):
            if not isinstance(channel.get(key, ""), str) or len(channel.get(key, "")) > 2000:
                raise ValueError("通道位置或备注格式错误。")
    if channel_ids is not None and recorded != list(channel_ids):
        raise ValueError("方案中的通道与当前设备不一致，请刷新通道记录。")
    if "timing" in plan:
        timing = plan["timing"]
        if (
            not isinstance(timing, dict)
            or type(timing.get("trial_count")) is not int
            or not 1 <= timing["trial_count"] <= 9999
            or type(timing.get("action_seconds")) not in (int, float)
            or not 1 <= timing["action_seconds"] <= 10
            or type(timing.get("random_order")) is not bool
        ):
            raise ValueError("方案中的重复次数、时长或随机顺序设置无效。")
    return plan


def validate_recording_annotations(meta, labels):
    """Custom labels and the derived index must refer to the same sample intervals."""
    plan = validate_plan(meta["capture_plan"], meta["channel_ids"])
    count = len(plan["selected_ids"])
    trials = meta.get("trial_count")
    if type(trials) is not int or not 1 <= trials <= 9999:
        raise ValueError("自定义采集的重复次数无效。")
    rate = meta["sampling_rate"]
    durations = [meta[key] for key in ("prepare_seconds", "action_seconds", "rest_seconds")]
    if (
        not math.isfinite(rate)
        or rate <= 0
        or any(not math.isfinite(d) or d < 0 for d in durations)
    ):
        raise ValueError("自定义采集时序无效。")
    prepare, action, rest = [round(d * rate) for d in durations]
    order = meta.get("actual_order")
    if (
        action < 1
        or not isinstance(order, list)
        or len(order) != count * trials
        or any(type(i) is not int or not 0 <= i < count for i in order)
        or any(set(order[i : i + count]) != set(range(count)) for i in range(0, len(order), count))
    ):
        raise ValueError("自定义采集的动作顺序与方案不一致。")
    expected = []
    for segment, cls in enumerate(order):
        start = segment * (prepare + action + rest) + prepare
        if start + action <= meta["samples"]:
            expected.append((segment // count + 1, cls, start, start + action))
    actual = [(r["trial"], r["class_id"], r["start_sample"], r["end_sample"]) for r in labels]
    if sorted(expected) != sorted(actual):
        raise ValueError("自定义动作标签与方案时序不一致。")


def selected_conditions(plan):
    lookup = {row["id"]: row for row in plan["conditions"]}
    return [lookup[identity] for identity in plan["selected_ids"]]


def capture_task(plan):
    from .tasks import Task

    rows = selected_conditions(validate_plan(plan))
    return Task(
        "robot",
        CUSTOM_CAPTURE,
        "自定义肌电采集",
        tuple(r["id"] for r in rows),
        tuple(r["name"] for r in rows),
        tuple(range(len(rows))),
    )
