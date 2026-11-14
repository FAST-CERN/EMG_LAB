"""Standard-library-only release primitives, also usable before Python packages install."""

import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path


def file_hash(path, algorithm="sha256"):
    value = hashlib.new(algorithm)
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def checked_path(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    target = (root / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root) or target == root:
        raise ValueError(f"Invalid release member: {relative}")
    return target


def extract_zip(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            if "\\" in entry.filename or entry.filename.startswith("/") or ":" in entry.filename:
                raise ValueError(f"Invalid archive member: {entry.filename}")
            target = checked_path(destination, entry.filename)
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Release archives may not contain symlinks.")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as input_file, target.open("wb") as output:
                    while chunk := input_file.read(1024 * 1024):
                        output.write(chunk)


def download(url, target, expected=None, algorithm="sha256"):
    target = Path(target)
    if target.exists() and expected and file_hash(target, algorithm) == expected.lower():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "EMG-Lab-release-builder"})
        with (
            urllib.request.urlopen(request, timeout=90) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if expected and file_hash(temporary, algorithm) != expected.lower():
            raise ValueError(f"Checksum mismatch: {url}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def verify_manifest(root, manifest):
    seen = set()
    for entry in manifest["files"]:
        path = checked_path(root, entry["path"])
        if path in seen:
            raise ValueError("Duplicate release member.")
        seen.add(path)
        if path.stat().st_size != entry["size"] or file_hash(path) != entry["sha256"]:
            raise ValueError(f"Release file verification failed: {entry['path']}")
