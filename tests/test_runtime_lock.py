"""运行时锁与取回脚本的契约：钉死工件、哈希校验、优先级链不变。"""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
NUSPEC = ROOT/'.runtime/python313/python.nuspec'


def parse_lock():
    fields = {}
    for line in (ROOT/'scripts/runtime.lock').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            fields.setdefault(key.strip(), []).append(value.strip())
    return fields


def test_lock_pins_artifact():
    lock = parse_lock()
    # 只校验格式与一致性：升级运行时应只改锁，不改测试。
    assert re.fullmatch(r'\d+\.\d+\.\d+', lock['version'][0])
    assert re.fullmatch(r'[0-9a-f]{64}', lock['sha256'][0])
    urls = lock['url']
    assert 2 <= len(urls) <= 3 and len(set(urls)) == len(urls)
    assert all(u.startswith('https://') for u in urls)


@pytest.mark.skipif(not NUSPEC.exists(), reason='本机无随包运行时，跳过一致性检查')
def test_lock_matches_bundled_runtime_when_present():
    version = re.search(r'<version>(.*?)</version>', NUSPEC.read_text(encoding='utf-8')).group(1)
    assert parse_lock()['version'] == [version]


def test_install_cmd_priority_chain():
    text = (ROOT/'install.cmd').read_text(encoding='utf-8')
    positions = [text.find(marker) for marker in
                 ('.runtime\\python313\\tools\\python.exe', 'py -3.13', 'fetch_runtime')]
    assert all(p >= 0 for p in positions), 'install.cmd 缺少优先级链中的环节'
    assert positions == sorted(positions), '取回必须位于本地运行时与系统解释器之后'


def test_fetch_script_contract():
    data = (ROOT/'scripts/fetch_runtime.cmd').read_bytes()
    for marker in (b'runtime.lock', b'SHA256', b'Get-FileHash', '学生离线包'.encode('gbk')):
        assert marker in data, f'取回脚本缺少 {marker}'
    assert data.count(b'\r\n') > 40 and b'\n' not in data.replace(b'\r\n', b''), 'cmd 脚本必须是 CRLF 行尾'
