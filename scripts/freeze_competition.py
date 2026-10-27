"""Teacher only: create a reviewed baseline explicitly, never on app startup."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from emg_lab.storage import ROOT,write_json
from emg_lab.competition import VERSION,BASELINE_FILE,load_rules,load_approvals,protected_files,runtime_versions,file_hash


def main():
    parser=argparse.ArgumentParser(description='教师审核后冻结比赛程序。修改代码、场景、规则或依赖后须重新测试，再显式重新冻结。')
    parser.add_argument('--confirm-reviewed',action='store_true',required=True)
    parser.add_argument('--replace',action='store_true',help='允许替换已有基准；先把旧基准保存在教师控制的位置。')
    args=parser.parse_args()
    path=ROOT/BASELINE_FILE
    if path.exists() and not args.replace:
        parser.error('已有基准；如确需更新，先备份并添加 --replace。')
    load_rules()
    load_approvals()
    write_json(path,dict(version=VERSION,created_utc=datetime.now(timezone.utc).isoformat(),
                         runtime=runtime_versions(),files=protected_files(ROOT)))
    print(str(path))
    print('SHA256: '+file_hash(path))
    print('请将文件与这个 SHA256 留存在学生不能修改的位置。校验只能发现与可信基准的差异。')


if __name__=='__main__': main()
