#!/usr/bin/env python3
"""Check release payloads and sanitized build logs without reporting matched values."""

import argparse
import ctypes
from hashlib import sha256
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile


PRIVATE_NAME = re.compile(
    r"(?i)(?:^|/)(?:\.riffuna(?:-developer)?|\.test-data|artist-ui-profile|"
    r"audio-cache|offline-audio|source-trace\.log|[^/]+\."
    r"(?:sqlite3?|jks|keystore|p12|pfx|dpapi)(?:-(?:wal|shm))?|"
    r"riffuna-collection[^/]*\.json)(?:/|$)"
)
MARKERS = {
    "fixture private data": re.compile(rb"PRIVATE_(?:HISTORY|PROFILE)_FIXTURE"),
    "private key": re.compile(rb"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[ \t]*(?:\r?\n|\\n)[A-Za-z0-9+/]{24,}"),
    "GitHub token": re.compile(rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "Bearer token": re.compile(rb"(?i)\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9_.~-]{20,}"),
    "signed media URL": re.compile(
        rb"https?://[a-zA-Z0-9.-]*googlevideo\.com/videoplayback\?[^\s\"'<>]{0,4096}"
        rb"(?:sig|signature|lsig|pot)=[A-Za-z0-9_%.-]{12,}"
    ),
    "absolute database path": re.compile(
        rb"(?:[A-Z]:[\\/]|/home/|/Users/)[^\r\n\"<>]{0,512}(?:library|local-files)\.sqlite3",
        re.IGNORECASE,
    ),
}
# Literal prefilters keep scans of the native runtime and ML models bounded in practice.
MARKER_PREFIXES = {
    "fixture private data": (b"private_",),
    "private key": (b"private key-----",),
    "GitHub token": (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_", b"github_pat_"),
    "Bearer token": (b"authorization",),
    "signed media URL": (b"googlevideo.com/videoplayback?",),
    "absolute database path": (b"library.sqlite3", b"local-files.sqlite3"),
}
GOOGLE_API_KEY = re.compile(rb"AIza[A-Za-z0-9_-]{35}")
UTF16_MARKERS = tuple(
    text.decode("ascii").encode(encoding)
    for prefixes in [*MARKER_PREFIXES.values(), (b"aiza",)]
    for text in prefixes
    for encoding in ("utf-16-le", "utf-16-be")
)
# Public client IDs already distributed in the pinned youtubei.js and bgutils-js packages.
PUBLIC_GOOGLE_KEY_DIGESTS = {
    "31043aae8be22df7c8159c11f0b029a8a0da56817f00ea996a37cc48db57482c",
    "2bea43e3f40eb708710f40552321c9486c28bca9b61ac45eac3afacf6006381f",
    "8e500b6bcf2807d65cb4f3cf74104d19887eb31ef84ea31191427c9a779e3d29",
}
ARCHIVE_SUFFIXES = {".apk", ".jar", ".zip", ".aar"}

def is_archive(stream, name: str) -> bool:
    return Path(name).suffix.lower() in ARCHIVE_SUFFIXES or stream.peek(4)[:4] == b"PK\x03\x04"


class PrivatePayload(ValueError):
    pass


def check_name(name: str) -> None:
    path = name.replace("\\", "/")
    if PRIVATE_NAME.search(path) or ".." in PurePosixPath(path).parts or path.startswith("/"):
        raise PrivatePayload("unexpected private or unsafe file name")


def check_bytes(data: bytes) -> None:
    lowered = data.lower()
    for label, marker in MARKERS.items():
        if any(prefix in lowered for prefix in MARKER_PREFIXES[label]) and marker.search(data):
            raise PrivatePayload(label)
    if b"aiza" in lowered and any(
        sha256(match[0]).hexdigest() not in PUBLIC_GOOGLE_KEY_DIGESTS
        for match in GOOGLE_API_KEY.finditer(data)
    ):
        raise PrivatePayload("Google API key")
    if data.startswith(b"SQLite format 3\0"):
        raise PrivatePayload("SQLite database payload")


def check_stream(stream, *, depth: int = 0, archive: bool = False) -> None:
    if archive:
        if depth >= 4:
            raise PrivatePayload("archive nesting limit")
        with zipfile.ZipFile(stream) as package:
            for info in package.infolist():
                check_name(info.filename)
                if info.is_dir():
                    continue
                with package.open(info) as entry:
                    nested = is_archive(entry, info.filename)
                    if nested and info.file_size > 512 * 1024 * 1024:
                        raise PrivatePayload("nested archive size limit")
                    check_stream(io.BytesIO(entry.read()) if nested else entry,
                                 depth=depth + 1, archive=nested)
        return
    carry = b""
    while chunk := stream.read(1024 * 1024):
        data = carry + chunk
        check_bytes(data)
        # Windows resources and PowerShell logs may store ASCII credentials in UTF-16.
        if b"\0" in data:
            lowered = data.lower()
            if any(marker in lowered for marker in UTF16_MARKERS):
                check_bytes(data.replace(b"\0", b""))
        carry = data[-16384:]


def embedded_msi(exe: Path, output: Path) -> None:
    if os.name != "nt":
        raise PrivatePayload("Windows is required to inspect the embedded installer")
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, handle, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = handle
    kernel.FindResourceW.argtypes = [handle, wintypes.LPCWSTR, ctypes.c_void_p]
    kernel.FindResourceW.restype = handle
    kernel.SizeofResource.argtypes = [handle, handle]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.LoadResource.argtypes = [handle, handle]
    kernel.LoadResource.restype = handle
    kernel.LockResource.argtypes = [handle]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [handle]
    module = kernel.LoadLibraryExW(str(exe), None, 0x22)
    if not module:
        raise PrivatePayload("cannot open installer resources")
    try:
        resource = kernel.FindResourceW(module, "msi", 10)
        size = kernel.SizeofResource(module, resource) if resource else 0
        address = kernel.LockResource(kernel.LoadResource(module, resource)) if size else 0
        if not size or not address:
            raise PrivatePayload("embedded MSI not found")
        output.write_bytes(memoryview((ctypes.c_ubyte * size).from_address(address)))
    finally:
        kernel.FreeLibrary(module)


def check_path(path: Path) -> None:
    check_name(path.name)
    if path.is_dir():
        for file in path.rglob("*"):
            check_name(file.relative_to(path).as_posix())
            if file.is_symlink():
                raise PrivatePayload("symbolic link in artifact")
            if file.is_file():
                with file.open("rb") as stream:
                    check_stream(stream, archive=is_archive(stream, file.name))
    else:
        with path.open("rb") as stream:
            check_stream(stream, archive=is_archive(stream, path.name))


def validate(path: Path, wix_dark: str | None) -> None:
    check_path(path)
    if not wix_dark:
        return
    with tempfile.TemporaryDirectory(prefix="riffuna-package-check-") as temp:
        work = Path(temp)
        msi = work / "setup.msi"
        embedded_msi(path, msi)
        result = subprocess.run(
            [wix_dark, "-nologo", "-x", str(work / "payload"), "-o", str(work / "setup.wxs"), str(msi)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        if result.returncode != 0:
            raise PrivatePayload("WiX could not extract the installer")
        payload = work / "payload"
        if not payload.is_dir() or not any(payload.rglob("*")):
            raise PrivatePayload("installer payload was empty")
        check_path(payload)
        check_path(work / "setup.wxs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--installer", action="store_true", help="unpack an EXE wrapping an MSI")
    parser.add_argument("--dark", help="WiX dark executable to extract the MSI")
    args = parser.parse_args()
    dark = args.dark or shutil.which("dark.exe") if args.installer else None
    if args.installer and not dark:
        parser.exit(1, "Privacy check failed: WiX dark.exe unavailable.\n")
    for path in args.paths:
        try:
            validate(path.resolve(strict=True), dark)
        except PrivatePayload as error:
            parser.exit(1, f"Privacy check failed: {error}.\n")
        except (OSError, RuntimeError, zipfile.BadZipFile):
            parser.exit(1, "Privacy check failed: unable to read payload.\n")
    print(f"Privacy check passed for {len(args.paths)} input(s).")


if __name__ == "__main__":
    main()
