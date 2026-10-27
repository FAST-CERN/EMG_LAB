"""安装链平台契约：win32 全功能档、darwin 模拟开发档（ADR 0002）、win 专属依赖行环境标记。"""
from pathlib import Path
import importlib.util,platform,sys
import pytest
from packaging.markers import Marker

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def bootstrap():
    spec=importlib.util.spec_from_file_location('bootstrap',ROOT/'scripts/bootstrap.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def become(monkeypatch,name,machine='arm64',version=(3,13,5,'final',0)):
    monkeypatch.setattr(sys,'platform',name)
    monkeypatch.setattr(platform,'machine',lambda:machine)
    monkeypatch.setattr(sys,'version_info',version)

def test_gate_allows_win32_python_313(bootstrap,monkeypatch):
    become(monkeypatch,'win32',machine='AMD64')
    bootstrap.gate()

def test_gate_allows_darwin_arm64_python_313(bootstrap,monkeypatch):
    become(monkeypatch,'darwin')
    bootstrap.gate()

def test_gate_rejects_other_platforms(bootstrap,monkeypatch):
    become(monkeypatch,'linux')
    with pytest.raises(RuntimeError,match='Windows x64'):
        bootstrap.gate()

def test_gate_rejects_darwin_intel(bootstrap,monkeypatch):
    become(monkeypatch,'darwin',machine='x86_64')
    with pytest.raises(RuntimeError,match='arm64'):
        bootstrap.gate()

def test_gate_wrong_python_guides_per_platform(bootstrap,monkeypatch):
    become(monkeypatch,'win32',machine='AMD64',version=(3,14,0,'final',0))
    with pytest.raises(RuntimeError,match='install.cmd'):
        bootstrap.gate()
    become(monkeypatch,'darwin',version=(3,12,0,'final',0))
    with pytest.raises(RuntimeError,match='Python 3.13'):
        bootstrap.gate()

def test_offline_install_stays_win32_only(bootstrap):
    assert bootstrap.offline_install('win32',True)
    assert not bootstrap.offline_install('win32',False)
    assert not bootstrap.offline_install('darwin',True),'darwin 必须永远在线安装'

def test_venv_python_differs_by_platform(bootstrap):
    assert bootstrap.venv_python(Path('v'),'win32').as_posix()=='v/Scripts/python.exe'
    assert bootstrap.venv_python(Path('v'),'darwin').as_posix()=='v/bin/python'

def requirement_lines():
    """沿 -r 展开全部依赖文件，产出 (文件, 条目, 标记) 三元组。"""
    def walk(name,seen):
        if name in seen:return
        seen=seen|{name}
        for raw in (ROOT/name).read_text(encoding='utf-8').splitlines():
            line=raw.strip()
            if not line or line.startswith('#'):continue
            if line.startswith('-r'):
                yield from walk(line.split(None,1)[1],seen)
            else:
                requirement,_,marker=line.partition(';')
                yield name,requirement.strip(),marker.strip() or None
    yield from walk('requirements-dev.txt',frozenset())

WIN_ONLY={
    ('requirements.txt','pythonnet>=3.0,<4'),
    ('requirements-robot.txt','./vendor/wheels/bsi_pykit_base-0.4.1-py3-none-any.whl'),
    ('requirements-robot.txt','./vendor/wheels/bsi_robot_base-0.1.2-py3-none-any.whl'),
    ('requirements-robot.txt','./vendor/dds/bsi_dds-0.1.1-py3-none-any.whl'),
    ('requirements-robot.txt','./vendor/dds/cyclonedds-11.0.1-cp313-cp313-win_amd64.whl'),
}

def test_win_only_entries_are_exactly_the_marked_set():
    marked={(file,requirement) for file,requirement,marker in requirement_lines() if marker}
    assert marked==WIN_ONLY,'真机链条目必须且只能带 win32 环境标记'

def test_markers_are_pip_parseable_and_decide_by_sys_platform():
    # packaging 是 pip 解析与求值环境标记的同一引擎：这里通过即 pip 语义通过。
    # pip 无法对境外平台求值需求行标记（--platform 只影响 wheel 选择），故用同库模拟 darwin。
    for file,requirement,marker in requirement_lines():
        if marker:
            parsed=Marker(marker)
            assert parsed.evaluate({'sys_platform':'win32'}),file+': '+requirement
            assert not parsed.evaluate({'sys_platform':'darwin'}),file+': '+requirement

def test_darwin_install_set_keeps_simulation_deps_only():
    active={requirement for _,requirement,marker in requirement_lines()
            if marker is None or Marker(marker).evaluate({'sys_platform':'darwin'})}
    assert not any(r.startswith('./vendor/') for r in active),'真机 vendor 轮子不得进入 darwin 安装集'
    for keep in ('PySide6>=6.8,<7','numpy>=2.1,<3','onnxruntime>=1.23,<2','mujoco>=3.3,<4',
                 'torch>=2.6,<3','pillow>=10,<13','pyusb==1.3.1','libusb-package==1.0.30.0','pytest==9.1.1'):
        assert keep in active,keep
