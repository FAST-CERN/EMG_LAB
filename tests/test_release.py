"""Release behavior with tiny fixtures; these fixtures are never distribution artifacts."""

import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.build_windows import copy_source, verify_wheel_coverage, windows_requirements
from scripts.offline_bootstrap import ensure_environment
from scripts.release_common import extract_zip, file_hash, verify_manifest, write_json


def bundle(root):
    for name in (
        ".runtime/python313/tools/python.exe",
        ".runtime/uv/uv.exe",
        "wheelhouse/example.whl",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture only")
    (root / "requirements-offline.txt").write_text("example==1 --hash=sha256:" + "0" * 64 + "\n")
    manifest = dict(
        format="emg-lab-offline-release",
        format_version=1,
        files=[
            dict(path=p.relative_to(root).as_posix(), size=p.stat().st_size, sha256=file_hash(p))
            for p in root.rglob("*")
            if p.is_file()
        ],
    )
    write_json(root / "OFFLINE_RELEASE.json", manifest)
    return manifest


def fake_installer(calls, fail_sync=False):
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["env"]["UV_OFFLINE"] == "1"
        assert kwargs["env"]["UV_PYTHON_DOWNLOADS"] == "never"
        if command[1] == "venv":
            target = Path(command[-1])
            (target / "Scripts").mkdir(parents=True)
            (target / "Scripts/python.exe").write_bytes(b"created here")
            (target / "pyvenv.cfg").write_text("home = bundled runtime")
        elif command[1:3] == ["pip", "sync"]:
            assert "--no-index" in command and "--require-hashes" in command
            if fail_sync:
                raise RuntimeError("interrupted fixture installation")

    return run


def test_first_launch_repeat_launch_and_relocation(tmp_path):
    root = tmp_path / "EMG Lab 中文"
    root.mkdir()
    bundle(root)
    calls = []
    ensure_environment(root, runner=fake_installer(calls))
    assert len(calls) == 3
    ensure_environment(root, runner=fake_installer(calls))
    assert len(calls) == 3  # repeat launch does not reinstall
    moved = tmp_path / "Moved copy"
    shutil.copytree(root, moved)
    ensure_environment(moved, runner=fake_installer(calls))
    assert len(calls) == 6
    assert str(moved) in calls[-3][0][-1]


def test_failed_setup_is_recoverable_and_never_marked_complete(tmp_path):
    bundle(tmp_path)
    with pytest.raises(RuntimeError):
        ensure_environment(tmp_path, runner=fake_installer([], fail_sync=True))
    assert not (tmp_path / ".venv/emg-lab-environment.json").exists()
    ensure_environment(tmp_path, runner=fake_installer([]))
    assert (tmp_path / ".venv/emg-lab-environment.json").is_file()


def test_tampered_payload_is_rejected_before_installation(tmp_path):
    manifest = bundle(tmp_path)
    (tmp_path / "wheelhouse/example.whl").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_manifest(tmp_path, manifest)
    calls = []
    with pytest.raises(ValueError):
        ensure_environment(tmp_path, runner=fake_installer(calls))
    assert not calls


def test_archive_members_cannot_escape_staging(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside", b"no")
    with pytest.raises(ValueError):
        extract_zip(archive, tmp_path / "extract")
    assert not (tmp_path / "outside").exists()


def test_windows_markers_are_evaluated_for_the_target_not_build_host():
    hashes = " --hash=sha256:" + "1" * 64
    exported = (
        "linux-only==1 ; sys_platform == 'linux'"
        + hashes
        + "\n"
        + "windows-only==1 ; sys_platform == 'win32' and platform_machine == 'AMD64'"
        + hashes
        + "\n"
    )
    result = windows_requirements(exported)
    assert "linux-only" not in result and "windows-only==1" in result and ";" not in result


def test_wrong_cpython_abi_is_not_accepted_for_windows(tmp_path):
    wheel = tmp_path / "example-1.0-cp312-cp312-win_amd64.whl"
    wheel.write_bytes(b"fixture")
    requirement = "example==1.0 --hash=sha256:" + file_hash(wheel) + "\n"
    with pytest.raises(ValueError):
        verify_wheel_coverage(requirement, tmp_path)
    replacement = tmp_path / "example-1.0-cp39-abi3-win_amd64.whl"
    replacement.write_bytes(b"fixture")
    verify_wheel_coverage(requirement, tmp_path)


def test_source_copy_excludes_personal_results_but_keeps_backend_data(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in (
        "data/private.emg",
        "local/delsys.json",
        ".venv/private",
        "emg_lab/backend/data/storage.py",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    target = tmp_path / "target"
    target.mkdir()
    copy_source(source, target)
    assert (target / "emg_lab/backend/data/storage.py").exists()
    assert (
        not (target / "data").exists()
        and not (target / "local").exists()
        and not (target / ".venv").exists()
    )


def test_payload_assembly_retains_upstream_runtime_notices(tmp_path):
    from scripts.build_windows import assemble_payload

    source, inputs, target = (tmp_path / name for name in ("source", "inputs", "release"))
    source.mkdir()
    inputs.mkdir()
    artifacts = {}
    for key, executable in (
        ("python", "tools/python.exe"),
        ("uv", "uv.exe"),
        ("dotnet", "dotnet.exe"),
    ):
        archive = inputs / (key + ".zip")
        with zipfile.ZipFile(archive, "w") as payload:
            payload.writestr(executable, b"fixture only")
            payload.writestr("LICENSE.txt", key + " fixture notice")
        artifacts[key] = dict(filename=archive.name, sha256=file_hash(archive))
    assemble_payload(source, target, inputs, artifacts)
    for folder in ("python313", "uv", "dotnet"):
        assert (target / ".runtime" / folder / "LICENSE.txt").is_file()
