# libmpv Windows LGPL build and corresponding source references

Riffuna loads the unmodified `libmpv-2.dll` dynamically. The pinned first-party
Windows x86_64 build is identified by `libmpv-BUILD-MANIFEST.json`, including the
original archive SHA256 and the unpacked DLL SHA256. The first-party release
identifies this variant as LGPLv3, built with `-Dgpl=false` and an LGPL FFmpeg.
Riffuna does not bundle the GPL libmpv variant, import library, Java archives,
headers, or the downloaded development ZIP in its application package.

mpv source (exact revision):
- https://github.com/mpv-player/mpv/tree/baa3e11d42cb7978da634a8a6a3a55fe074d01be
- https://github.com/mpv-player/mpv/archive/baa3e11d42cb7978da634a8a6a3a55fe074d01be.tar.gz

FFmpeg source (exact revision reported by the DLL):
- https://github.com/FFmpeg/FFmpeg/tree/9d9703e3b6f1e00e56b48067cbcf52a2fb808ee3
- https://github.com/FFmpeg/FFmpeg/archive/9d9703e3b6f1e00e56b48067cbcf52a2fb808ee3.tar.gz

Build configuration, dependency acquisition and first-party packaging:
- https://github.com/mpv-player/mpv/actions/runs/40141553607
- https://github.com/mpv-player/mpv/tree/baa3e11d42cb7978da634a8a6a3a55fe074d01be/.github/workflows
- https://github.com/mpv-player/mpv/blob/baa3e11d42cb7978da634a8a6a3a55fe074d01be/DOCS/compile-windows.md
- https://github.com/mpv-player/mpv/releases/tag/git-release

Keep the complete corresponding source and dependency build materials for the
exact binary when redistributing it; these references identify upstream material
but do not themselves replace a complete corresponding-source distribution.
The download helper preserves the original archive and its provenance locally.

The bundled mpv `LICENSE.LGPL` text is LGPL2.1; it is preserved verbatim as
`libmpv-LGPL-2.1-or-later.txt`. The combined first-party LGPLv3 build also uses the
LGPLv3/GPLv3 texts supplied in this directory. See `libmpv-Copyright.txt` for mpv
attribution and per-file licensing.

Riffuna's PolyForm Noncommercial restrictions do not apply to libmpv, FFmpeg or
other third-party components. Users retain their licenses' rights to modify and
replace those libraries and to reverse-engineer the combined application for
debugging such modifications. In the Kotlin Windows package, close Riffuna and replace
`Riffuna.runtime/app/resources/vendor/libmpv/libmpv-2.dll` with an ABI-compatible
replacement DLL. Keep a backup of the original binary. The source uses JNA to load
this file dynamically. The legacy Python one-file application also supported the
RIFFUNA_LIBMPV environment variable.
No signature or hash check prevents the application from loading a replacement.
