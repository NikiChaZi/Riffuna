# Third-party components

New Riffuna changes from 0.1.3 are licensed under PolyForm Noncommercial 1.0.0 (LICENSE). The previously published MIT-licensed code retains its original permissions and notice (LICENSES/MIT-legacy.txt). See LICENSING.md. Dependencies retain their own licenses; the noncommercial restriction does not relicense or limit rights granted by third-party libraries.

## Current Kotlin desktop package

The application includes Kotlin/Compose Multiplatform and its JVM dependencies, a bundled Java runtime, SQLite JDBC, JNA/JNA Platform, ONNX Runtime, Bouncy Castle, Reorderable and SLF4J. Dependency JARs retain their upstream META-INF notices; Java's notices are in the runtime legal directory. Versions are pinned in the Gradle files.

Node.js v24.15.0 is included for the YouTube source component. Its complete upstream license and bundled-component notices are in `LICENSES/Node-v24.15.0-LICENSE.txt`. Source: https://github.com/nodejs/node/tree/v24.15.0 .

YouTube.js 18.3.0, Undici 8.12.3 and their locked npm dependencies are included under `source-runtime/node_modules` with their upstream notices. YouTube.js and Undici use the MIT license. Undici source: https://github.com/nodejs/undici . YouTube.js source: https://github.com/LuanRT/YouTube.js . The application's own JSON-lines wrapper is maintained in `source-runtime/index.mjs`.

Python, PySide6, Qt, Shiboken, yt-dlp and PyInstaller are not included in the Kotlin desktop runtime. Previous Python/Qt sources remain in this repository for development history. Their third-party permissions and previously distributed notices remain applicable to those historical packages.

Music, artwork and lyrics fetched during use are not distributed as part of the application package. The local recommendation model uses Music4All-Onion numerical features and derived vectors. Dataset attribution, source DOI, CC-BY-4.0 license link, metadata provenance and transformations are included in `LICENSES/Music4All-Onion-ATTRIBUTION.json` and `music-model/ATTRIBUTION.json`. Third-party data and component rights remain separate from Riffuna's own code license. Original interaction records, music and lyrics are not bundled.

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
