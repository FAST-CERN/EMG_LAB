"""Build the complete offline Windows ZIP from uv.lock and verified runtime inputs."""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .release_common import checked_path, extract_zip, file_hash, verify_manifest, write_json
except ImportError:
    from release_common import checked_path, extract_zip, file_hash, verify_manifest, write_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("emg_lab", "assets", "docs", "licenses", "vendor", "drivers", "scripts")
SOURCE_FILES = (
    "main.py",
    "start.cmd",
    "install.cmd",
    "acceptance.cmd",
    "README.md",
    "NOTICE.md",
    "CONTEXT.md",
    "SOURCE_PROVENANCE.json",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "competition_rules.json",
    "competition_approvals.json",
    "competition_baseline.json",
)


def windows_requirements(exported):
    """Evaluate target markers explicitly; pip --platform alone evaluates host markers."""
    from packaging.markers import Marker, default_environment
    from packaging.utils import parse_wheel_filename

    environment = default_environment()
    environment.update(
        sys_platform="win32",
        platform_system="Windows",
        platform_machine="AMD64",
        os_name="nt",
        python_version="3.13",
        python_full_version="3.13.5",
        extra="",
    )
    logical = []
    buffer = ""
    for line in exported.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        buffer += " " + line.strip().removesuffix("\\")
        if line.rstrip().endswith("\\"):
            continue
        logical.append(buffer.strip())
        buffer = ""
    if buffer:
        raise ValueError("Truncated uv export.")
    output = []
    for line in logical:
        if line.startswith("-e ") or line.startswith("--"):
            raise ValueError("Unexpected unlocked/editable requirement.")
        hashes = re.findall(r"--hash=sha256:[0-9a-f]{64}", line)
        if not hashes:
            raise ValueError("Every offline requirement must be hash-locked.")
        requirement = re.sub(r"\s*--hash=sha256:[0-9a-f]{64}", "", line).strip()
        base, separator, marker = requirement.partition(";")
        if separator and not Marker(marker.strip()).evaluate(environment):
            continue
        base = base.strip()
        if base.startswith(("./", "../")):
            path = checked_path(ROOT, base)
            name, version, _, _ = parse_wheel_filename(path.name)
            base = f"{name}=={version}"
        output.append(base + " " + " ".join(hashes))
    return "\n".join(output) + "\n"


def copy_source(source, target):
    source, target = Path(source), Path(target)
    ignore = shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*:Zone.Identifier", ".git", ".cache", ".pytest_cache"
    )
    for name in SOURCE_DIRS:
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name, ignore=ignore)
    for name in SOURCE_FILES:
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)


def assemble_payload(source, target, artifacts_folder, artifacts):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    copy_source(source, target)
    for key, item in artifacts.items():
        payload = checked_path(artifacts_folder, item["filename"])
        if file_hash(payload) != item["sha256"]:
            raise ValueError(f"Runtime input changed: {key}")
    extract_zip(
        Path(artifacts_folder) / artifacts["python"]["filename"], target / ".runtime/python313"
    )
    extract_zip(
        Path(artifacts_folder) / artifacts["dotnet"]["filename"], target / ".runtime/dotnet"
    )
    with tempfile.TemporaryDirectory() as temporary:
        extract_zip(Path(artifacts_folder) / artifacts["uv"]["filename"], temporary)
        executables = list(Path(temporary).rglob("uv.exe"))
        if len(executables) != 1:
            raise ValueError("Expected one uv.exe in verified archive.")
        # Retain every upstream archive member, including notices and companion binaries.
        shutil.copytree(temporary, target / ".runtime/uv")
        if not (target / ".runtime/uv/uv.exe").is_file():
            shutil.copy2(executables[0], target / ".runtime/uv/uv.exe")
    for relative in (
        ".runtime/python313/tools/python.exe",
        ".runtime/uv/uv.exe",
        ".runtime/dotnet/dotnet.exe",
    ):
        if not (target / relative).is_file():
            raise ValueError(f"Missing runtime executable: {relative}")


def build(output, inputs, *, download_wheels=True):
    if not (ROOT / "uv.lock").is_file():
        raise RuntimeError("uv.lock is missing. Run uv sync on a network-enabled host first.")
    subprocess.run(["uv", "lock", "--check", "--offline"], cwd=ROOT, check=True)
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty.strip():
        raise RuntimeError("Commit the reviewed source before building an identified release.")
    inputs = Path(inputs)
    artifacts = json.loads((inputs / "release-artifacts.lock.json").read_text())["artifacts"]
    exported = subprocess.check_output(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-header"],
        cwd=ROOT,
        text=True,
    )
    flat = windows_requirements(exported)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
    ).strip()
    name = f"EMG_LAB_2026-windows-x64-{commit}"
    archive = output / (name + ".zip")
    if archive.exists():
        raise FileExistsError(f"Release output already exists: {archive}")
    with tempfile.TemporaryDirectory(prefix="emg-release-", dir=output) as temporary:
        target = Path(temporary) / name
        assemble_payload(ROOT, target, inputs, artifacts)
        (target / "requirements-offline.txt").write_text(flat, encoding="utf-8")
        wheelhouse = target / "wheelhouse"
        wheelhouse.mkdir()
        for folder in ("vendor/wheels", "vendor/dds"):
            for wheel in (ROOT / folder).glob("*.whl"):
                shutil.copy2(wheel, wheelhouse / wheel.name)
        if download_wheels:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--only-binary=:all:",
                    "--no-deps",
                    "--require-hashes",
                    "--platform",
                    "win_amd64",
                    "--python-version",
                    "313",
                    "--implementation",
                    "cp",
                    "--abi",
                    "cp313",
                    "--extra-index-url",
                    "https://download.pytorch.org/whl/cpu",
                    "--dest",
                    str(wheelhouse),
                    "-r",
                    str(target / "requirements-offline.txt"),
                ],
                cwd=ROOT,
                check=True,
            )
        else:
            for wheel in (inputs / "wheelhouse").glob("*.whl"):
                shutil.copy2(wheel, wheelhouse / wheel.name)
        verify_wheel_coverage(flat, wheelhouse)
        write_json(
            wheelhouse / "SHA256.json",
            {p.name: file_hash(p) for p in sorted(wheelhouse.glob("*.whl"))},
        )
        entries = [
            dict(path=p.relative_to(target).as_posix(), size=p.stat().st_size, sha256=file_hash(p))
            for p in sorted(target.rglob("*"))
            if p.is_file()
        ]
        manifest = dict(
            format="emg-lab-offline-release",
            format_version=1,
            target="Windows 10/11 x64",
            created_at=datetime.now(timezone.utc).isoformat(),
            source_commit=commit,
            dependency_lock_sha256=file_hash(ROOT / "uv.lock"),
            artifacts=artifacts,
            files=entries,
        )
        write_json(target / "OFFLINE_RELEASE.json", manifest)
        verify_manifest(target, manifest)
        partial = archive.with_suffix(".zip.partial")
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as release:
                for p in sorted(target.rglob("*")):
                    if p.is_file():
                        release.write(p, p.relative_to(target.parent).as_posix())
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    archive.with_suffix(".zip.sha256").write_text(file_hash(archive) + "  " + archive.name + "\n")
    return archive


def verify_wheel_coverage(requirements, wheelhouse):
    from packaging.requirements import Requirement
    from packaging.tags import compatible_tags, cpython_tags
    from packaging.utils import canonicalize_name, parse_wheel_filename

    allowed = set(
        cpython_tags(
            python_version=(3, 13), abis=["cp313", "abi3", "none"], platforms=["win_amd64"]
        )
    )
    allowed.update(
        compatible_tags(python_version=(3, 13), interpreter="cp313", platforms=["win_amd64"])
    )
    candidates = {}
    for path in Path(wheelhouse).glob("*.whl"):
        name, version, _, tags = parse_wheel_filename(path.name)
        if not tags & allowed:
            continue
        candidates.setdefault(canonicalize_name(name), []).append((version, file_hash(path)))
    for line in requirements.splitlines():
        requirement = Requirement(line.split(" --hash=")[0])
        hashes = set(re.findall("--hash=sha256:([0-9a-f]{64})", line))
        matching = [
            h
            for version, h in candidates.get(canonicalize_name(requirement.name), [])
            if version in requirement.specifier and h in hashes
        ]
        if not matching:
            raise ValueError(f"No hash-matching Windows wheel: {requirement}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--inputs", type=Path, default=ROOT / "dist/release-inputs")
    parser.add_argument(
        "--offline-inputs",
        action="store_true",
        help="Use an already prepared inputs/wheelhouse instead of downloading wheels.",
    )
    args = parser.parse_args()
    print(build(args.output, args.inputs, download_wheels=not args.offline_inputs))


if __name__ == "__main__":
    main()
