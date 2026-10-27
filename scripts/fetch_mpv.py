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


DLL_SHA256 = "bbb8bb09e4ffc93cd93430b620f40b09e086b7dc63f1651c8a1ce38853ed5169"
MIRROR_ASSET = "Riffuna-0.2.0-windows-x64.zip"
MIRROR_URL = "https://github.com/NikiChaZi/Riffuna/releases/download/v0.2.0/" + MIRROR_ASSET
MIRROR_SHA256 = "cfd717933edba4a4789238503382d74c3ce78f64b3f23fcad3d11b4986a908b9"
MIRROR_SIZE = 307986741
MIRROR_PREFIX = "Riffuna.runtime/app/resources/vendor/libmpv/"


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download_pinned(url, destination, size, checksum):
    if destination.is_file() and destination.stat().st_size == size and file_hash(destination) == checksum:
        return
    temporary = destination.with_name(destination.name + ".part")
    try:
        digest = hashlib.sha256()
        length = 0
        with requests.get(url, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            with temporary.open("wb") as target:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    length += len(chunk)
                    if length > size:
                        raise RuntimeError("Pinned download exceeded expected size")
                    digest.update(chunk)
                    target.write(chunk)
        if length != size or digest.hexdigest() != checksum:
            raise RuntimeError("Pinned download failed its size/SHA256 check")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_mirror(directory):
    archive = directory / MIRROR_ASSET
    download_pinned(MIRROR_URL, archive, MIRROR_SIZE, MIRROR_SHA256)
    with zipfile.ZipFile(archive) as package:
        binary = package.read(MIRROR_PREFIX + "libmpv-2.dll")
        if hashlib.sha256(binary).hexdigest() != DLL_SHA256:
            raise RuntimeError("Mirror libmpv DLL differs from the pinned LGPL build")
        license_text = package.read(MIRROR_PREFIX + "LICENSE.LGPL")
        metadata = json.loads(package.read(MIRROR_PREFIX + "BUILD-MANIFEST.json"))
    metadata["download_mirror"] = {"url": MIRROR_URL, "sha256": MIRROR_SHA256, "size": MIRROR_SIZE}
    metadata["dll_sha256"] = DLL_SHA256
    temporary = directory / "libmpv-2.dll.part"
    try:
        temporary.write_bytes(binary)
        temporary.replace(directory / "libmpv-2.dll")
    finally:
        temporary.unlink(missing_ok=True)
    (directory / "LICENSE.LGPL").write_bytes(license_text)
    (directory / "BUILD-MANIFEST.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf8")
    return directory / "libmpv-2.dll"


def fetch(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / ASSET
    try:
        download_pinned(URL, archive, SIZE, SHA256)
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code not in (404, 410):
            raise
        return fetch_mirror(directory)
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
