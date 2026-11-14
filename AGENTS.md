# EMG Lab development

This repository is the active, editable full application. Robot, hand and coin-task features are in scope. This overrides the older robot-only/reference-preservation conventions in the parent workspace for this directory.

- Use this repository's uv project/environment for development. Bundled Windows runtimes are distribution artifacts, not development interpreters.
- Keep backend and contracts independent of Qt/frontend imports. The Qt frontend uses application contracts; bootstrap wires concrete services.
- Preserve task IDs, artifact formats, causal filtering, whole-trial splits, normalization, scoring and hardware gates. Do not activate physical devices in automated checks.
- Keep assets, vendor notices and licensing intact. Do not commit environments, wheelhouses, credentials or personal results.
- Tests and synthetic smoke runs are software evidence; report Windows and real-hardware checks separately.
- Changes may be committed in this repository. Existing competition baselines require explicit teacher refreezing after structural changes; never silently regenerate them.
