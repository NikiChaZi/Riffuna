# Third-party components

New Riffuna changes from 0.1.3 are licensed under PolyForm Noncommercial 1.0.0 (LICENSE). The previously published MIT-licensed code retains its original permissions and notice (LICENSES/MIT-legacy.txt). See LICENSING.md. Dependencies retain their own licenses; the noncommercial restriction does not relicense or limit rights granted by third-party libraries.

Qt, PySide6 and Shiboken6 6.10.2 declare LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only in the official distribution metadata. These dynamically linked libraries are unmodified. License texts: LICENSES/. Upstream sources and build instructions (v6.10.2): https://code.qt.io/pyside/pyside-setup.git/ and https://code.qt.io/qt/ .

Python: LICENSES/LICENSE.txt in the one-file application resources. Other bundled dependency notices, including yt-dlp, ytmusicapi, requests and PyInstaller, are provided in their bundled distribution metadata. The release also includes a separate license and source-reference archive. External Node.js is not included. No music or YouTube artwork is included.

## libmpv / FFmpeg audio playback

The Windows application dynamically loads the unmodified first-party libmpv
LGPL build `v0.41.0-dev-gbaa3e11d4` (x86_64), using the LGPL FFmpeg variant.
Its verified configuration includes `-Dgpl=false`; the first-party provider
identifies this combined variant as LGPLv3. The GPL binary variant is not used.
Only `libmpv-2.dll` is packaged from the development archive.

Attribution, licenses and exact source/build references are included in
`LICENSES/libmpv-Copyright.txt`, `LICENSES/libmpv-LGPL-2.1-or-later.txt`,
`LICENSES/LGPL-3.0-only.txt`, `LICENSES/GPL-3.0-only.txt`,
`LICENSES/libmpv-SOURCES.md` and `LICENSES/libmpv-BUILD-MANIFEST.json`.
The first-party build is from https://github.com/mpv-player/mpv/releases/tag/git-release .

Third-party LGPL rights remain independent of Riffuna's own license, including
modification/replacement of these libraries and reverse engineering for debugging
such modifications. See the replacement path and source references in
`LICENSES/libmpv-SOURCES.md`.
