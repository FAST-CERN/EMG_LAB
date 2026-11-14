"""EMG training with whole-trial splits, including training without holdout data."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from emg_lab.backend.data.storage import (
    excluded_trials,
    read_recording,
    recording_metadata,
    usable_record,
)
from emg_lab.backend.learning.signal import (
    SignalConfig,
    SignalFilter,
    compatible_profile,
    window_samples,
)
from emg_lab.contracts.tasks import require_task, task_from_metadata


def prepare_dataset(recordings):
    if not recordings:
        raise ValueError("请先勾选要训练的数据。")
    units, ids, hashes = [], set(), set()
    profile = None
    ordered = [(recording_metadata(p).get("created_at", ""), str(p), Path(p)) for p in recordings]
    for _, _, folder in sorted(ordered):
        meta, raw, labels = read_recording(folder)
        if not usable_record(meta):
            raise ValueError(f"“{meta['name']}”没有可用的完整动作组，请检查无效标记或补采。")
        digest = hashlib.sha256(raw.tobytes()).hexdigest()
        if meta["record_id"] in ids or digest in hashes:
            raise ValueError("同一份数据被选择了两次，请取消重复项。")
        ids.add(meta["record_id"])
        hashes.add(digest)
        if profile is None:
            profile = meta
        task = task_from_metadata(profile)
        require_task(meta, task)
        class_count = len(task.classes)
        required = set(range(class_count))
        compatible_profile(profile, meta)
        if meta["group"] != profile["group"] or meta["preprocessing"] != profile["preprocessing"]:
            raise ValueError("一次训练请选同一实验组、相同滤波设置的数据。")
        config = SignalConfig(**meta["preprocessing"])
        window, step = window_samples(meta["sampling_rate"], config)
        filtered = SignalFilter(meta["sampling_rate"], len(meta["channel_ids"]), config).process(
            raw
        )
        # Legacy files label each action with a trial ID; keep that entire file together.
        modern = meta.get("schema_version", 1) >= 2
        trial_labels = (
            [[r for r in labels if r["trial"] == t] for t in sorted({r["trial"] for r in labels})]
            if modern
            else [labels]
        )
        for segments in trial_labels:
            if any(r["trial"] in excluded_trials(meta) for r in segments):
                continue
            if {r["class_id"] for r in segments} != required:
                continue  # Ignore the unfinished trial when a session was ended early.
            if modern and len(segments) != class_count:
                raise ValueError("数据中的动作标签重复，请重新选择数据。")
            x, y, windows = [], [], []
            for label in segments:
                start = label["start_sample"] + round(0.2 * meta["sampling_rate"])
                for offset in range(start, label["end_sample"] - window + 1, step):
                    x.append(filtered[offset : offset + window].T)
                    y.append(label["class_id"])
                    windows.append([offset, offset + window])
            if set(y) != required:
                raise ValueError("动作持续时间太短，请将每个动作设为至少 1 秒后重新采集。")
            units.append(
                (
                    np.stack(x),
                    np.array(y, dtype=np.int64),
                    dict(
                        path=str(folder.resolve()),
                        record_id=meta["record_id"],
                        name=meta["name"],
                        trial=segments[0]["trial"] if modern else None,
                        collection_notes=meta.get("collection_notes", {}),
                        unit="trial" if modern else "legacy_session",
                        sha256=digest,
                        windows=len(y),
                        sample_ranges=windows,
                        class_counts=np.bincount(y, minlength=class_count).tolist(),
                    ),
                )
            )
    if not units:
        raise ValueError("数据中还没有完整的一组动作，请按当前实验目标采全所有类别后再训练。")
    # Never randomly divide overlapping windows. One trial is still enough to train.
    n = len(units)
    n_val = max(1, round(n * 0.15)) if n >= 2 else 0
    n_test = max(1, round(n * 0.15)) if n >= 3 else 0
    n_train = n - n_val - n_test
    return profile, dict(
        train=units[:n_train],
        validation=units[n_train : n_train + n_val],
        test=units[n_train + n_val :],
    )
