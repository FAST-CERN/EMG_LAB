"""Fetch the original NVIDIA G1 model and CPU policies at a fixed revision.

LFS files are verified against the upstream SHA-256 pointer, not accepted by name.
No model training, remote code execution, or robot communication is involved.
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from urllib.parse import quote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REVISION = '45c03facbf848e0c743091b7d9c17952096ff908'
PREFIX = 'decoupled_wbc/sim2mujoco/resources/robots/g1/'
RAW = f'https://raw.githubusercontent.com/NVlabs/GR00T-WholeBodyControl/{REVISION}/'
MEDIA = f'https://media.githubusercontent.com/media/NVlabs/GR00T-WholeBodyControl/{REVISION}/'


def read_url(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                return response.read()
        except OSError:
            if attempt == 2:
                raise


def fetch(path, relative):
    target = ROOT / relative
    original = read_url(RAW + quote(path))
    expected = hashlib.sha256(original).hexdigest()
    size = len(original)
    is_lfs = original.startswith(b'version https://git-lfs.github.com/spec/v1')
    if is_lfs:
        fields = dict(line.split(' ', 1) for line in original.decode().splitlines())
        expected = fields['oid'].split(':')[1]
        size = int(fields['size'])
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        data = None
    else:
        data = read_url(MEDIA + quote(path)) if is_lfs else original
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'Asset hash mismatch: {path}')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.part')
        temporary.write_bytes(data)
        temporary.replace(target)
    return dict(path=relative, upstream_path=path, sha256=expected, size=size)


def verify_local():
    manifest = json.loads((ROOT/'assets/manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        path = ROOT/entry['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f"Asset missing or changed: {entry['path']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Verify bundled assets without network access.')
    if parser.parse_args().check:
        verify_local()
        print('All local assets verified.')
        return
    entries = [fetch(PREFIX + 'g1_gear_wbc.xml', 'assets/g1/g1.xml')]
    xml = ET.parse(ROOT / 'assets/g1/g1.xml')
    jobs = [(PREFIX+'meshes/'+m.attrib['file'], 'assets/g1/meshes/'+m.attrib['file'])
            for m in xml.findall('.//asset/mesh')]
    jobs += [(PREFIX+'policy/'+name, 'assets/policies/'+name) for name in
             ('GR00T-WholeBodyControl-Balance.onnx', 'GR00T-WholeBodyControl-Walk.onnx')]
    jobs += [('LICENSE', 'licenses/NVIDIA-LICENSE.txt'),
             (PREFIX+'policy/NVIDIA Open Model License', 'licenses/NVIDIA-Open-Model-License.txt'),
             (PREFIX+'README.md', 'licenses/G1-upstream-README.md')]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for entry in pool.map(lambda args: fetch(*args), jobs):
            entries.append(entry)
            print(f"Verified {entry['path']} ({entry['size']} bytes)", flush=True)
    manifest = dict(repository='https://github.com/NVlabs/GR00T-WholeBodyControl',
                    revision=REVISION, files=entries)
    (ROOT/'assets/manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('All assets ready.', flush=True)


if __name__ == '__main__':
    main()
