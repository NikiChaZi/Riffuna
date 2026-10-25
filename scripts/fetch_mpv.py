"""Fetch a pinned first-party LGPL Windows libmpv build; never run executables."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import zipfile

import requests

ASSET = "libmpv-v0.41.0-dev-gbaa3e11d4-40141553607-x86_64-w64-mingw32-lgpl.zip"
URL = "https://github.com/mpv-player/mpv/releases/download/git-release/" + ASSET
SHA256 = "7a256440129b90a760ada9245e98c8f9181d23b4192a44901c913aa74e6a02a8"
SIZE = 56826947
SOURCE_COMMIT = "baa3e11d42"


def fetch(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / ASSET
    temporary = directory / (ASSET + ".part")
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        digest = hashlib.sha256()
        length = 0
        try:
            with requests.get(URL, stream=True, timeout=(15, 90)) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                            digest.update(chunk)
                            length += len(chunk)
            if length != SIZE or digest.hexdigest() != SHA256:
                raise RuntimeError("Official libmpv archive failed its pinned size/SHA256 check")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            destination = (directory / member.filename).resolve()
            if directory not in destination.parents or stat.S_ISLNK(member.external_attr >> 16):
                raise RuntimeError("Unsafe path in libmpv archive")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
    dlls = list(directory.rglob("libmpv-2.dll"))
    if len(dlls) != 1:
        raise RuntimeError("Expected one libmpv-2.dll in the official archive")
    metadata = {
        "asset": ASSET, "url": URL, "sha256": SHA256, "size": SIZE,
        "provider": "mpv-player/mpv first-party GitHub CI",
        "license": "LGPL-3.0-or-later (first-party LGPL build; bundled FFmpeg LGPL variant)",
        "upstream_commit": SOURCE_COMMIT,
        "source_url": "https://github.com/mpv-player/mpv/tree/" + SOURCE_COMMIT,
        "source_archive": "https://github.com/mpv-player/mpv/archive/" + SOURCE_COMMIT + ".tar.gz",
        "build_workflow": "https://github.com/mpv-player/mpv/actions/runs/40141553607",
        "release": "https://github.com/mpv-player/mpv/releases/tag/git-release",
        "distribution_note": "Keep this manifest, LGPL notices and corresponding build/dependency sources when redistributing.",
    }
    (directory / "BUILD-MANIFEST.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return dlls[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "vendor" / "libmpv")
    args = parser.parse_args()
    print(fetch(args.directory))
