# 0003: Separate the native desktop frontend from application services

Status: implemented in source; Windows GUI and portable-binary acceptance pending.

The original application combined Qt layout, task orchestration, device/training process ownership and physical-output lifecycle in a large `app.py`. Moving or replacing its interface therefore risked changing acquisition and decoding behavior.

Keep the existing PySide6 desktop interface. Introduce a Qt-independent `backend.ApplicationService` and shared `contracts` package, with explicit composition in `bootstrap.py`. Pages and presenters own widgets and presentation; the service owns Session, subprocesses, output gates, fresh-command dispatch and completion/stale-signal handling. Device and training subprocess boundaries remain. There is no HTTP server or separate frontend deployment requirement.

Backend renderers emit RGB arrays. A bounded mailbox and queued Qt bridge produce UI images without making the backend depend on Qt. Acquisition remains ordered and loss-detecting; display mailbox dropping does not apply to EMG samples. Immutable/copy snapshots isolate frontend reads from Session state. Existing import paths remain aliases so external scripts and subprocess module entry points can migrate gradually.

Data and model formats, ordered classes, causal preprocessing, whole-trial splitting, train-only normalization and existing scoring are retained. Network replacement uses a trusted model factory registry. Body-frame velocity is an available control contract; this decision does not introduce EMG regression or continuous training targets.

Use `pyproject.toml` and `uv.lock` for active dependency management. Distribute Windows as a complete portable ZIP containing verified Python, uv, .NET and hash-locked wheels; create `.venv` offline on first launch. Retain the verified source-installation Python fallback. Do not commit binary environments or silently refresh competition baselines.

The cost is a compatibility layer during migration and separate Linux software versus Windows/device acceptance. Source provenance, migration mapping and actual validation are recorded in `RESTRUCTURE_REPORT.md` and `WINDOWS_RELEASE.md`.
