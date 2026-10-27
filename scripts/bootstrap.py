"""Create this copy's environment; prefer the bundled wheels, never copy a venv."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,venv
ROOT=Path(__file__).resolve().parents[1]

def run(args):
    subprocess.run([str(v) for v in args],cwd=ROOT,check=True,env=dict(os.environ,PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONIOENCODING='utf-8'))

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if sys.platform!='win32' or sys.version_info[:2]!=(3,13):
        raise RuntimeError('本发行包适用于 Windows x64 / Python 3.13。请使用随包 install.cmd。')
    wheels=ROOT/'wheelhouse'
    offline=wheels.is_dir()
    if offline:
        manifest=json.loads((wheels/'SHA256.json').read_text(encoding='utf-8'))
        for name,expected in manifest.items():
            if Path(name).name!=name or hashlib.sha256((wheels/name).read_bytes()).hexdigest()!=expected:
                raise RuntimeError('离线依赖包校验失败，请重新解压完整发行包：'+name)
        print('离线依赖校验通过。正在建立本机运行环境…',flush=True)
    target=ROOT/'.venv';python=target/'Scripts/python.exe'
    if not python.exists():venv.EnvBuilder(with_pip=False).create(target)
    # Recover cleanly if a previous installation stopped during pip setup.
    if subprocess.run([str(python),'-m','pip','--version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        run([python,'-m','ensurepip','--upgrade','--default-pip'])
    source=['--no-index','--find-links',wheels] if offline else ['--index-url','https://pypi.tuna.tsinghua.edu.cn/simple']
    run([python,'-m','pip','install',*source,'-r','requirements-dev.txt','-c','constraints.txt'])
    run([python,'-m','pip','check'])
    run([python,'scripts/download_robot_assets.py','--check'])
    run([python,'scripts/check_hand_assets.py'])
    print('安装完成。双击 start.cmd 开始使用；无需连接设备。',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print('安装未完成：'+str(error),flush=True);raise SystemExit(1)
