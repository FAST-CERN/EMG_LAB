"""Human-readable, derived index; the .emg metadata remains authoritative."""

import csv
import json
from pathlib import Path

from emg_lab.contracts.acquisition import selected_conditions, validate_plan


def write_capture_index(recording, meta):
    plan = validate_plan(meta["capture_plan"], meta["channel_ids"])
    conditions = selected_conditions(plan)
    rate = meta["sampling_rate"]
    prepare = round(meta["prepare_seconds"] * rate)
    action = round(meta["action_seconds"] * rate)
    rest = round(meta["rest_seconds"] * rate)
    rejected = {r["trial"]: r["reason"] for r in meta.get("rejected_trials", [])}
    path = Path(recording).with_suffix(".index.csv")
    fields = [
        "record_id",
        "recording",
        "session_name",
        "segment_name",
        "trial",
        "condition_id",
        "action",
        "body_part",
        "effort",
        "save_name",
        "notes",
        "start_sample",
        "end_sample",
        "start_seconds",
        "end_seconds",
        "complete_segment",
        "complete_trial",
        "valid",
        "rejection_reason",
        "operator",
        "wearing",
        "session_notes",
        "channel_count",
        "channels",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            count = len(conditions)
            order = meta["actual_order"]
            for segment, cls in enumerate(order):
                start = segment * (prepare + action + rest) + prepare
                if start >= meta["samples"]:
                    continue
                end = min(start + action, meta["samples"])
                trial = segment // count + 1
                trial_end = (
                    ((trial - 1) * count + count - 1) * (prepare + action + rest) + prepare + action
                )
                row = conditions[cls]
                writer.writerow(
                    dict(
                        record_id=meta["record_id"],
                        recording=Path(recording).name,
                        session_name=meta["name"],
                        segment_name=f"{row['save_name']}_R{trial:03d}_S{segment + 1:03d}",
                        trial=trial,
                        condition_id=row["id"],
                        action=row["name"],
                        body_part=row["body_part"],
                        effort=row["effort"],
                        save_name=row["save_name"],
                        notes=row["notes"],
                        start_sample=start,
                        end_sample=end,
                        start_seconds=start / rate,
                        end_seconds=end / rate,
                        complete_segment=end == start + action,
                        complete_trial=meta["samples"] >= trial_end,
                        valid=trial not in rejected,
                        rejection_reason=rejected.get(trial, ""),
                        operator=plan["operator"],
                        wearing=plan["wearing"],
                        session_notes=plan["notes"],
                        channel_count=len(meta["channel_ids"]),
                        channels=json.dumps(plan["channels"], ensure_ascii=False),
                    )
                )
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path
