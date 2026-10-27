"""Create this copy's environment; prefer the bundled wheels, never copy a venv."""
from pathlib import Path
import hashlib,json,os,platform,subprocess,sys,venv
ROOT=Path(__file__).resolve().parents[1]
WIN,DARWIN='win32','darwin'

def run(args):
    subprocess.run([str(v) for v in args],cwd=ROOT,check=True,env=dict(os.environ,PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONIOENCODING='utf-8'))

def gate():
    """放行 win32（学生全功能档）与 darwin/arm64（教师模拟开发档，ADR 0002），均需 Python 3.13。"""
    platform_name,machine,version=sys.platform,platform.machine(),sys.version_info[:2]
    if platform_name==WIN:
        if version!=(3,13):raise RuntimeError('本发行包适用于 Windows x64 / Python 3.13。请使用随包 install.cmd。')
        return
    if platform_name==DARWIN:
        if version!=(3,13):raise RuntimeError('macOS 开发档需要自装 Python 3.13（如 brew install python@3.13 或从 python.org 下载），再运行 python3 scripts/bootstrap.py。')
        if machine!='arm64':raise RuntimeError('macOS 仅支持 arm64（Apple Silicon）开发档；Intel 与 Rosetta 解释器不支持。')
        return
    raise RuntimeError('本包面向 Windows x64（学生全功能档）与 macOS arm64（教师模拟开发档），不支持当前平台：'+platform_name)

def offline_install(platform_name,wheelhouse_present):
    """离线 wheelhouse 只随 Windows 学生包分发；darwin 一律在线安装。"""
    return platform_name==WIN and wheelhouse_present

def venv_python(target,platform_name):
    return target/('Scripts/python.exe' if platform_name==WIN else 'bin/python')

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    gate()
    wheels=ROOT/'wheelhouse'
    offline=offline_install(sys.platform,wheels.is_dir())
    if offline:
        manifest=json.loads((wheels/'SHA256.json').read_text(encoding='utf-8'))
        for name,expected in manifest.items():
            if Path(name).name!=name or hashlib.sha256((wheels/name).read_bytes()).hexdigest()!=expected:
                raise RuntimeError('离线依赖包校验失败，请重新解压完整发行包：'+name)
        print('离线依赖校验通过。正在建立本机运行环境…',flush=True)
    target=ROOT/'.venv';python=venv_python(target,sys.platform)
    if not python.exists():venv.EnvBuilder(with_pip=False).create(target)
    # Recover cleanly if a previous installation stopped during pip setup.
    if subprocess.run([str(python),'-m','pip','--version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        run([python,'-m','ensurepip','--upgrade','--default-pip'])
    source=['--no-index','--find-links',wheels] if offline else ['--index-url','https://pypi.tuna.tsinghua.edu.cn/simple']
    run([python,'-m','pip','install',*source,'-r','requirements-dev.txt','-c','constraints.txt'])
    run([python,'-m','pip','check'])
    run([python,'scripts/download_robot_assets.py','--check'])
    run([python,'scripts/check_hand_assets.py'])
    finish='安装完成。双击 start.cmd 开始使用；无需连接设备。' if sys.platform==WIN else '安装完成。运行 .venv/bin/python main.py 开始使用；无需连接设备。'
    print(finish,flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('安装未完成：'+str(error),flush=True);raise SystemExit(1)
