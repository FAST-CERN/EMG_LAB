# EMG Lab structure refactor report

Date: 2026-11-14. Active repository: `EMG_LAB_2026`. Original source snapshot: Git commit `c838231`.

## Requirements and scope

Restructure the editable repository, retain native Windows desktop operation, separate frontend/backend responsibilities, and improve readability for future development. Preserve the existing robot, hand and coin-task application in this repository. The older robot-only extraction in the workspace root is separate and was not rewritten.

Keep the standard acquisition → recording → whole-trial training → ONNX decoding procedure even without usable real EMG data. Allow network replacement and future robot interface changes. Direct body-frame `(vx, vy, yaw_rate)` is an available control interface, with no claim that a continuous EMG decoder has been implemented.

## Implemented structure

| Location | Responsibility |
| --- | --- |
| `emg_lab/bootstrap.py` | Composition and concrete service injection |
| `emg_lab/contracts/` | Task/class definitions, signal configuration, events, snapshots and control contracts |
| `emg_lab/backend/application.py` | Application use cases, Session/process/output ownership, completion and stale-input handling |
| `emg_lab/backend/data/` | Recording/capture, catalogue, transfer, collection notes and reports |
| `emg_lab/backend/learning/` | Dataset preparation, model registry, training/export, decoding and evaluation |
| `emg_lab/backend/runtime/` | Session, process protocol, SDK acquisition and training process entry points |
| `emg_lab/backend/robot/` | Simulation, physics, control, rendering workers and optional DDS |
| `emg_lab/backend/hand/` | Hand models, poses, rendering, optional output and original drivers |
| `emg_lab/frontend/pages/` | Qt page layouts |
| `emg_lab/frontend/presenters/` | User actions and presentation of service state |
| `emg_lab/frontend/bridge.py` | Queued events and bounded RGB display frames → Qt images |
| `emg_lab/frontend/window.py` | Desktop shell, replacing the original 1,600-line application module |

The frontend and backend remain in the same desktop process, with existing acquisition/training subprocesses. There is no web/server deployment requirement. Queued completion events carry run identities so an earlier run cannot cancel a newly prepared scene. The former UI timer completion/stale-input decisions were removed; it renders snapshots while the service owns those decisions. Backend/contracts import no Qt or frontend code; the frontend uses the application service and shared contracts. The backend controls fresh-command dispatch, automatic capture/assessment/replay completion and stale-signal stops. UI refreshes do not renew cached prediction leases. Rendering frame replacement is display-only; acquisition keeps sequence and backlog checks.

Legacy module paths remain compatibility aliases, including executable worker entry points. New code should use the explicit package paths. Existing UI tests now inject deliberate fixture state through the service; operational frontend code does not access its private Session. Scene views require a service-owning host. `window.session` remains a transitional service facade, rather than exposing the mutable original Session.

## Preserved behavior and provenance

Task identifiers and ordered classes, `.emg`/legacy recordings, `.emgmodel` transfer, sample-clock labels, causal filtering, whole-trial splitting and train-only normalization remain. Classification remains the default. The trusted network registry accepts `[B,C,W]` inputs and `[B,K]` logits; architecture/configuration are stored in model metadata and supported by training requests. No regression targets were inferred from class labels.

Physical output retains explicit real-device/live-source gating, task limits, idle connections and stale-command stops. Output cleanup attempts all outputs and Session cleanup even if a stop or report write fails. SDK/DDS imports remain optional in core workflows. Automated checks use fake outputs or simulated input; physical output is never enabled.

Compared directly against `c838231`, **175 asset/vendor/driver/UI-resource files are byte-identical**. Eight icon/help resources moved into `frontend/`; their original licenses and hashes remain. The module mapping is in [structure-migration.json](structure-migration.json). `SOURCE_PROVENANCE.json` records this refactor without rewriting older historical provenance entries. The network-factory API was adapted from the workspace's previous `emg_robot` extraction; the original classifier stays the default.

The original parent `EMG_LAB-runtime` folder was replaced before this task. Running the old parent preservation checker returns failure because that reference directory no longer exists; it cannot assess this editable repository. This refactor uses the nested Git snapshot and the direct 175-file content comparison above as provenance evidence.

The existing competition baseline and historical results were retained without refreezing. They are not verification of the new structure. Formal competition entry requires teacher review and an explicit new freeze after acceptance.

## Environment and distribution

`pyproject.toml` and `uv.lock` are the active dependency authority. The lock resolves Linux x64, Windows AMD64 and macOS arm64 environments; exporting for Windows selects 50 runtime packages. Private Windows wheels remain local sources. Root-only output ignore rules preserve the new `backend/data` source package. Old requirements/constraints files remain historical reference material.

Windows launchers retain native desktop startup. Release tooling prepares verified Python/uv/.NET inputs, collects hash-locked Windows wheels and builds a manifest-backed offline ZIP. First launch initializes `.venv` offline; interrupted setup, repeat launch, repair, relocation and setup locking are covered by packaging fixture tests. Fixture executables are tests only and are never shipped as runtimes.

The repository's actual local uv environment is now available, including PySide6 6.10.0, NumPy 2.5.4, SciPy 1.18.1, PyTorch 2.15.0+cpu, ONNX Runtime 1.32.0 and MuJoCo 3.17.0 on Python 3.13.5/Linux. Early headless checks used the already installed parent uv environment while installation was deferred; subsequent desktop checks use this repository's environment.

## Verification

The final full Linux suite passed: **173 tests passed, 3 skipped** (Windows Cometa, Windows DDS adapter and absent bundled Windows runtime). This includes regressions for stale completions and backend-owned capture completion followed by UI refresh. The retained TorchScript ONNX exporter produces deprecation/tracer warnings; export and streaming equivalence checks pass. The suite ran with `QT_QPA_PLATFORM=offscreen MUJOCO_GL=egl uv run --no-sync pytest -q -rs`. All generated data, models, logs and screenshots are under the chosen `local/` output roots or temporary test directories.

- The explicit synthetic smoke check passed for robot four/seven classes and hand three/five classes: capture, whole-trial split, two-epoch training, ONNX export, held-out replay evaluation and batch/chunked inference equivalence. These results do not measure real EMG accuracy.
- Linux EGL robot and hand rendering passed (`scripts/check_classroom.py --render`).
- Actual robot Qt workflow passed: simulated acquisition, recording, training without holdout, live inference, physics scene, file replay and shutdown.
- Actual basic-hand Qt workflow passed: five-trial capture with 3D cues, three-class training, decoded open/close/stop-hold behavior, replay and shutdown.
- Both extended Qt workflows (robot seven classes and hand five classes) passed: capture, training, every decoded class, 3D, live assessment, complete replay assessment and reports. These are simulated-input software checks.
- Packaging/architecture checks passed again after retaining complete upstream runtime archive contents: **12 tests passed**.
- Source syntax, architecture/import boundaries, relevant Ruff checks and `uv lock --check --offline` passed.

## Remaining acceptance

The Windows runtime payloads and complete Windows wheelhouse have not been downloaded in this workspace; no ready-to-distribute ZIP is claimed. Windows 10/11 launch, first-launch offline installation, .NET/SDK loading, path relocation and native desktop acceptance must run against the actual built ZIP. Offline WebEngine diagrams still require desktop acceptance: the Linux Xvfb check could not start the Qt xcb platform because system libxcb-cursor0 is absent. Offscreen text-fallback/template tests passed, but they do not establish WebEngine rendering.

Real Cometa/Delsys acquisition, robot DDS and hand USB output/stop/latency checks remain unrun. No historical competition evidence substitutes for them. Build and acceptance commands are in [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md); the architecture decision is [ADR 0003](adr/0003-desktop-service-and-portable-distribution.md).
