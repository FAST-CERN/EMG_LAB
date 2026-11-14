# Repository cleanup

The uv project is the sole Python dependency authority: edit `pyproject.toml`, resolve `uv.lock`, and install with `uv sync --locked`.

Removed the six legacy `requirements*.txt` files and `constraints.txt`. Dependency-marker tests, source fingerprints, competition protection and Windows source copying now use the uv configuration. `scripts/runtime.lock` remains because it pins the native Windows Python archive and its checksum. The offline release's `requirements-offline.txt` is generated from `uv.lock` for uv installation; it is not an independently maintained dependency file.

Removed the twelve project files with Chinese filenames, including the older PDF/HTML documents, two root shortcuts and the bundled synthetic example files. The example bundle's manifest was also removed because its payloads no longer exist. Documentation and release packaging no longer reference these files. Chinese prose and UI labels are retained; the cleanup concerns filenames.

The competition-rules button now opens the existing `docs/COMPETITION.md` tab in native offline help. Software/render checks use `uv run python scripts/check_classroom.py --render`. Synthetic data and models can be generated explicitly with `uv run python scripts/smoke_pipeline.py --output local/smoke`.

Earlier provenance records, the original package snapshot and the historical competition baseline retain their original paths/hashes as historical evidence. They are not current file inventories; the competition baseline still needs explicit teacher review/refreezing before formal use. User-generated data and environments are outside this cleanup.

Validation: 53 relevant tests passed and one bundled-Windows-runtime check was skipped. The competition-rules button was exercised with offscreen Qt and opened the Markdown rules tab. The uv lock consistency check, relevant Ruff checks and Git whitespace check passed. No remaining tracked project paths contain Chinese characters; no root legacy requirements/constraints files remain.
