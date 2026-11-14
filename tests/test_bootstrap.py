"""安装链平台契约：win32 全功能档、darwin 模拟开发档（ADR 0002）、win 专属依赖行环境标记。"""

import importlib.util
import json
import platform
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bootstrap():
    return load_script("bootstrap")


def become(monkeypatch, name, machine="arm64", version=(3, 13, 5, "final", 0)):
    monkeypatch.setattr(sys, "platform", name)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(sys, "version_info", version)


def test_gate_allows_win32_python_313(bootstrap, monkeypatch):
    become(monkeypatch, "win32", machine="AMD64")
    bootstrap.gate()


def test_gate_allows_darwin_arm64_python_313(bootstrap, monkeypatch):
    become(monkeypatch, "darwin")
    bootstrap.gate()


def test_gate_rejects_other_platforms(bootstrap, monkeypatch):
    become(monkeypatch, "linux")
    with pytest.raises(RuntimeError, match="Windows x64"):
        bootstrap.gate()


def test_gate_rejects_darwin_intel(bootstrap, monkeypatch):
    become(monkeypatch, "darwin", machine="x86_64")
    with pytest.raises(RuntimeError, match="arm64"):
        bootstrap.gate()


def test_gate_wrong_python_guides_per_platform(bootstrap, monkeypatch):
    become(monkeypatch, "win32", machine="AMD64", version=(3, 14, 0, "final", 0))
    with pytest.raises(RuntimeError, match="install.cmd"):
        bootstrap.gate()
    become(monkeypatch, "darwin", version=(3, 12, 0, "final", 0))
    with pytest.raises(RuntimeError, match="Python 3.13"):
        bootstrap.gate()


def test_offline_install_stays_win32_only(bootstrap):
    assert bootstrap.offline_install("win32", True)
    assert not bootstrap.offline_install("win32", False)
    assert not bootstrap.offline_install("darwin", True), "darwin 必须永远在线安装"


def test_venv_python_differs_by_platform(bootstrap):
    assert bootstrap.venv_python(Path("v"), "win32").as_posix() == "v/Scripts/python.exe"
    assert bootstrap.venv_python(Path("v"), "darwin").as_posix() == "v/bin/python"


def project_config():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def requirements():
    config = project_config()
    return [
        Requirement(spec)
        for spec in config["project"]["dependencies"] + config["dependency-groups"]["dev"]
    ]


WIN_ONLY = {"pythonnet", "bsi-pykit-base", "bsi-robot-base", "bsi-dds", "cyclonedds"}


def test_win_only_entries_are_exactly_the_marked_set():
    marked = {requirement.name for requirement in requirements() if requirement.marker}
    assert marked == WIN_ONLY
    sources = project_config()["tool"]["uv"]["sources"]
    for name in WIN_ONLY - {"pythonnet"}:
        assert (ROOT / sources[name]["path"]).is_file()


def test_markers_decide_windows_sdk_availability_by_target_platform():
    for requirement in requirements():
        if requirement.marker:
            assert requirement.marker.evaluate({"sys_platform": "win32"}), requirement.name
            for other in ("darwin", "linux"):
                assert not requirement.marker.evaluate({"sys_platform": other}), requirement.name


def test_darwin_install_set_keeps_simulation_deps_only():
    active = {
        requirement.name.lower()
        for requirement in requirements()
        if requirement.marker is None or requirement.marker.evaluate({"sys_platform": "darwin"})
    }
    assert not WIN_ONLY & active
    assert {
        "pyside6",
        "numpy",
        "scipy",
        "onnxruntime",
        "onnx",
        "mujoco",
        "torch",
        "pillow",
        "pyusb",
        "libusb-package",
        "pytest",
    } <= active


def test_revo2_manifest_keys_resolve_across_separators():
    # provenance.json 的键由 Windows 写入（\）；POSIX 上必须归一化后与 / 写法定位到同一文件。
    check_hand_assets = load_script("check_hand_assets")
    manifest = json.loads((ROOT / "assets/revo2/provenance.json").read_text(encoding="utf-8"))
    assets = ROOT / "assets/revo2"
    for name in manifest["files"]:
        posix = name.replace("\\", "/")
        assert check_hand_assets.resolve_asset(assets, name) == check_hand_assets.resolve_asset(
            assets, posix
        ), name
        assert check_hand_assets.resolve_asset(assets, posix).is_file(), name
