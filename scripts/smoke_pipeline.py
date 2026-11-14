"""Explicit synthetic-only capture/train/export/replay check. Never opens hardware."""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from emg_lab.backend.application import ApplicationService
from emg_lab.backend.data.storage import read_json, read_recording, write_json
from emg_lab.backend.learning.inference import InferencePipeline
from emg_lab.backend.learning.training import train
from emg_lab.contracts.tasks import TASKS


def smoke(output):
    output = Path(output).resolve()
    # Each run has an explicit fresh output folder, preserving earlier evidence.
    run = output / ("synthetic-" + uuid.uuid4().hex[:12])
    results = []
    rng = np.random.default_rng(73)
    for selector in ("robot", "robot7", "hand", "hand5"):
        events = []
        service = ApplicationService(run / selector, local_root=run / "logs", background=False)
        service.events.connect(events.append)
        try:
            service.select_task(selector)
            service.accept_device_event(
                dict(
                    type="connected",
                    profile=dict(
                        device="模拟练习",
                        sampling_rate=1000.0,
                        channel_ids=[1, 2, 3, 4],
                        unit="a.u.",
                    ),
                )
            )
            service.feed(np.zeros((20, 4), dtype="f4"))
            recording = service.start_capture(
                "SYNTHETIC", "software-check", trial_count=3, action_s=1.2
            )
            while service.capture:
                cue = service.capture.status()["command"]
                gain = np.full(4, 0.03)
                if cue:
                    gain[(cue - 1) % 4] = 1.0
                service.feed((rng.normal(size=(20, 4)) * gain).astype("f4"))
                service.poll()
            assert any(event.kind == "capture_finished" for event in events)
            model = train(
                dict(
                    recordings=[str(recording)],
                    data_root=str(run / selector),
                    name="synthetic-model",
                    epochs=2,
                )
            )
            profile, raw, labels = read_recording(recording)
            predictions = InferencePipeline(model, profile).feed(raw)
            chunked = []
            stream = InferencePipeline(model, profile)
            for block in np.array_split(raw, 97):
                chunked.extend(stream.feed(block))
            np.testing.assert_allclose(
                [r["probabilities"] for r in predictions],
                [r["probabilities"] for r in chunked],
                atol=1e-6,
            )
            assert predictions and labels
            metadata = read_json(model / "metadata.json")
            assert metadata["classes"] == list(TASKS[selector].classes)
            assert metadata["online_evaluation"]["split"] == "test"
            results.append(
                dict(
                    task=selector,
                    recording=str(recording),
                    model=str(model),
                    windows=len(predictions),
                    passed=True,
                )
            )
        finally:
            service.close()
    report = dict(
        synthetic_only=True, real_emg_accuracy="not_measured", checks=results, passed=True
    )
    write_json(run / "report.json", report)
    print(json.dumps(dict(report=str(run / "report.json"), **report), ensure_ascii=False, indent=2))
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="Root for all generated fixtures/models/reports."
    )
    args = parser.parse_args()
    smoke(args.output)


if __name__ == "__main__":
    main()
