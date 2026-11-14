"""Fetch and verify versioned Windows payloads; record immutable release inputs.

Run on a network-enabled release host. No fabricated/offline substitute lock is generated.
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

try:
    from .release_common import download, file_hash, write_json
except ImportError:
    from release_common import download, file_hash, write_json

ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = "0.11.26"
UV_URL = (
    f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)
DOTNET_METADATA = "https://builds.dotnet.microsoft.com/dotnet/release-metadata/8.0/releases.json"


def read_url(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def prepare(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    lock = {}
    for line in (ROOT / "scripts/runtime.lock").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            lock.setdefault(key, value)
    python_url = lock["url"]
    python_file = destination / f"python-{lock['version']}.nupkg"
    download(python_url, python_file, lock["sha256"])
    checksum = read_url(UV_URL + ".sha256").decode().split()[0].lower()
    if not re.fullmatch("[0-9a-f]{64}", checksum):
        raise ValueError("Invalid upstream uv checksum.")
    uv_file = download(UV_URL, destination / f"uv-{UV_VERSION}-windows.zip", checksum)
    metadata = json.loads(read_url(DOTNET_METADATA))
    version = metadata["latest-runtime"]
    runtime = next(
        release["runtime"]
        for release in metadata["releases"]
        if release.get("runtime", {}).get("version") == version
    )
    native = next(
        item
        for item in runtime["files"]
        if item["rid"] == "win-x64" and item["name"].endswith(".zip")
    )
    dotnet = download(
        native["url"],
        destination / f"dotnet-runtime-{version}-win-x64.zip",
        native["hash"],
        "sha512",
    )
    artifacts = {
        "python": dict(
            filename=python_file.name,
            version=lock["version"],
            url=python_url,
            sha256=file_hash(python_file),
        ),
        "uv": dict(
            filename=uv_file.name,
            version=UV_VERSION,
            url=UV_URL,
            sha256=file_hash(uv_file),
            upstream_checksum=UV_URL + ".sha256",
        ),
        "dotnet": dict(
            filename=dotnet.name,
            version=version,
            url=native["url"],
            sha256=file_hash(dotnet),
            upstream_sha512=native["hash"],
        ),
    }
    write_json(
        destination / "release-artifacts.lock.json", dict(format_version=1, artifacts=artifacts)
    )
    return destination / "release-artifacts.lock.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release-inputs")
    args = parser.parse_args()
    print(prepare(args.output))


if __name__ == "__main__":
    main()
