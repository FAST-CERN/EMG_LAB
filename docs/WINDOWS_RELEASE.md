# Windows portable release and acceptance

The target is Windows 10 22H2 / Windows 11 x64 with an OpenGL-capable driver. This repository contains source and a genuine uv dependency lock. It does **not** currently contain a complete portable ZIP, runtime payloads or all Windows wheels. Linux Qt and rendering checks are available; they cannot establish Windows compatibility.

## Source development

From this repository, with uv installed:

```powershell
uv sync --locked
uv run --locked python main.py
uv run pytest -q
uv run python scripts/smoke_pipeline.py --output local/smoke
```

`install.cmd` retains the original verified Python 3.13.5 NuGet fallback when neither the bundled interpreter nor system Python 3.13 is available. It then obtains uv if needed and runs `uv sync --locked`. Source installation requires network access. `requirements*.txt` and `constraints.txt` remain historical reference files; active installation uses `pyproject.toml` and `uv.lock`.

On Linux, the core/backend can be developed without importing Qt or Windows SDKs. The full development dependency set includes Qt; use the project environment after installation. macOS arm64 retains the simulated-device UI path. Neither platform substitutes for Windows acceptance.

## Build a complete offline ZIP

Use a network-enabled release host after committing the reviewed source:

```powershell
uv sync --locked
uv run python scripts/prepare_release.py --output dist/release-inputs
uv run python scripts/build_windows.py --inputs dist/release-inputs --output dist
```

Preparation verifies the existing pinned Python SHA256, the upstream pinned uv release checksum, and Microsoft's .NET 8 runtime SHA512. It records the actual versions, URLs and hashes in `dist/release-inputs/release-artifacts.lock.json`. This file is generated only from downloaded payloads. It must be retained with release evidence.

The builder requires a clean Git tree and an up-to-date uv lock. It exports runtime dependencies, explicitly evaluates markers for Windows AMD64 / Python 3.13.5, and downloads hash-locked binary wheels. It checks Windows wheel tags and coverage before producing a ZIP and a `.zip.sha256` file. Release identity contains the source commit. An existing ZIP is never overwritten.

The ZIP contains source, documentation, assets, SDK resources, licenses, bundled Python, uv, .NET 8 and a Windows wheelhouse. It excludes personal `data/`, `local/`, credentials, Git metadata and environments. Every included file is recorded in `OFFLINE_RELEASE.json`. A pre-populated `dist/release-inputs/wheelhouse` can be reused with `--offline-inputs`; coverage and hashes are still checked.

## First launch and repair

Extract the complete ZIP into a writable folder and double-click `start.cmd`. No system Python or uv is required. The bundled interpreter verifies the manifest, creates this copy's `.venv`, installs from the local wheelhouse using uv with networking disabled, and checks dependencies before writing the successful-installation marker. Subsequent starts reuse it. Interrupted setup is retried; `install.cmd` repairs the environment. A setup lock prevents concurrent installers from modifying it together.

Moving the extracted folder invalidates its environment-location signature and rebuilds the environment offline. A folder with an unrecognized `.venv` is preserved and reported for manual renaming. Paths containing spaces and Chinese characters are part of the Windows acceptance procedure.

The bundled .NET 8 runtime is application-local. USB drivers, Cometa's system .NET Framework requirements, device licenses and physical hardware are separate prerequisites documented under `drivers/`. Launch and acceptance never install USB drivers or enable physical output automatically.

## Windows acceptance

Disconnect networking, extract the actual ZIP on each target OS, then run:

```bat
acceptance.cmd --relocation-test
```

The script initializes/reuses the offline environment, runs synthetic training/replay, both renderers, robot/hand UI workflows, extended task schemes, actual offline WebEngine help rendering and coin route reachability. Help fallback is reported as incomplete acceptance. It then tests rebuilding in a relocated path containing spaces and Chinese characters. Results go to `local/windows-acceptance.json`, with per-check results and `real_hardware: not_run`. These checks can take several minutes and require a desktop/OpenGL session.

Real Cometa/Delsys acquisition, DDS transport, USB hand output, disconnect/stop behavior and latency must be checked separately with the relevant hardware. Synthetic labels and geometric coin-route controllers provide software evidence only.

The existing `competition_baseline.json` is deliberately unchanged. Its old hashes will reject formal entry after the refactor. A teacher must review and explicitly refreeze the finished, Windows-accepted release; historical competition results are not acceptance of this structure.
