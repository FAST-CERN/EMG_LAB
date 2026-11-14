"""Create this copy's environment; prefer the bundled wheels, never copy a venv."""

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN, DARWIN = "win32", "darwin"


def run(args):
    subprocess.run(
        [str(v) for v in args],
        cwd=ROOT,
        check=True,
        env=dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONIOENCODING="utf-8"),
    )


def gate():
    """放行 win32（学生全功能档）与 darwin/arm64（教师模拟开发档，ADR 0002），均需 Python 3.13。"""
    platform_name, machine, version = sys.platform, platform.machine(), sys.version_info[:2]
    if platform_name == WIN:
        if version != (3, 13):
            raise RuntimeError("本发行包适用于 Windows x64 / Python 3.13。请使用随包 install.cmd。")
        return
    if platform_name == DARWIN:
        if version != (3, 13):
            raise RuntimeError(
                "macOS 开发档需要自装 Python 3.13（如 brew install python@3.13 或从 python.org 下载），再运行 python3 scripts/bootstrap.py。"
            )
        if machine != "arm64":
            raise RuntimeError(
                "macOS 仅支持 arm64（Apple Silicon）开发档；Intel 与 Rosetta 解释器不支持。"
            )
        return
    raise RuntimeError(
        "本包面向 Windows x64（学生全功能档）与 macOS arm64（教师模拟开发档），不支持当前平台："
        + platform_name
    )


def offline_install(platform_name, wheelhouse_present):
    """离线 wheelhouse 只随 Windows 学生包分发；darwin 一律在线安装。"""
    return platform_name == WIN and wheelhouse_present


def venv_python(target, platform_name):
    return target / ("Scripts/python.exe" if platform_name == WIN else "bin/python")


def find_uv():
    """Use installed uv, or fetch the verified pinned Windows executable locally."""
    import shutil

    installed = shutil.which("uv")
    if installed:
        return Path(installed)
    bundled = ROOT / ".runtime/uv/uv.exe"
    if bundled.is_file():
        return bundled
    if sys.platform != WIN:
        raise RuntimeError("Install uv, then run uv sync --locked from this repository.")
    import re
    import tempfile

    from prepare_release import UV_URL, UV_VERSION, read_url
    from release_common import download, extract_zip

    checksum = read_url(UV_URL + ".sha256").decode().split()[0].lower()
    if not re.fullmatch("[0-9a-f]{64}", checksum):
        raise ValueError("Invalid upstream uv checksum.")
    archive = download(UV_URL, ROOT / ".runtime" / f"uv-{UV_VERSION}.zip", checksum)
    with tempfile.TemporaryDirectory(dir=ROOT / ".runtime") as temporary:
        extract_zip(archive, temporary)
        candidates = list(Path(temporary).rglob("uv.exe"))
        if len(candidates) != 1:
            raise ValueError("Expected exactly one uv.exe.")
        bundled.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], bundled)
    return bundled


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    gate()
    if (ROOT / "OFFLINE_RELEASE.json").is_file():
        from offline_bootstrap import ensure_environment

        python = ensure_environment(ROOT, repair=True)
    else:
        if not (ROOT / "uv.lock").is_file():
            raise RuntimeError("Missing uv.lock. Restore the complete source repository.")
        # Both source installation and the portable package use uv, never pip into a reference runtime.
        run([find_uv(), "sync", "--locked", "--python", sys.executable])
        python = venv_python(ROOT / ".venv", sys.platform)
    run([python, "scripts/download_robot_assets.py", "--check"])
    run([python, "scripts/check_hand_assets.py"])
    print(
        "安装完成。双击 start.cmd 开始使用；无需连接设备。"
        if sys.platform == WIN
        else "安装完成。运行 uv run --locked python main.py 开始使用。",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("安装未完成：" + str(error), flush=True)
        raise SystemExit(1)
