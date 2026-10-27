"""Validate the bundled offline Revo2 meshes and their source manifest."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    assets=ROOT/'assets/revo2'
    manifest=json.loads((assets/'provenance.json').read_text(encoding='utf-8'))
    for name,digest in manifest['files'].items():
        path=assets/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError(f'Revo2 asset is missing or changed: {name}')
    if not (ROOT/'licenses/Revo2-Apache-2.0.txt').is_file():
        raise ValueError('Revo2 license is missing')
    print(f"PASS: {len(manifest['files'])} Revo2 files, SHA-256 and license")


if __name__=='__main__': main()
