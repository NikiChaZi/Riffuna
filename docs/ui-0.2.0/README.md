# Riffuna 0.2.0 — visual review

Visual work only, on `codex/ui-0.2.0`. This is part of the future 0.2.0, not a release.
The first QA pass uses 0.1.2 (`9a5b514`). Integration with published 0.1.3 and its updated licensing/audio behavior is still required before final QA. New Riffuna changes are intended for source-available, noncommercial use; commercial use requires a separate agreement with NikiChaZi. Do not replace the newer license files with this branch's inherited 0.1.2 files.

## Decisions

- Keep the warm graphite/coral identity. Add restrained sage and sand tiles to distinguish library, history and search. No purple, gradients, glows or decorative shadows.
- Separate discovery navigation from the local library. Keep the search field and player in stable positions.
- Give each list a recognizable section cover and a clear heading. Move version badges into the metadata line and cap their height; titles retain horizontal space.
- Show the current recording above the queue without putting that recording into the queue. Existing queue order, selection and scroll behavior stay intact.
- Turn the existing example searches into explicit cards. Local likes/history shortcuts use the existing library; there are no simulated recommendations or invented listening statistics.
- At 1000×650, narrow side panels and hide only the decorative record illustration. Search, likes, queue and all player controls remain available.
- Replace the temporary waveform with an original R/Play mark. One SVG generates a transparent PNG and a 15-frame ICO (16–256 px). The same icon is assigned to QApplication and MainWindow, bundled as runtime data, and embedded into the EXE. Explicit Windows AppUserModelID: `Riffuna.Desktop`.

## Official references inspected on 2026-10-25

- [Spotify desktop/web presentation](https://webplayer.byspotify.com/): persistent library navigation, compact recording rows and separation of browsing from the current session. The official screenshots were viewed in the browser.
- [Spotify Now Playing documentation](https://support.spotify.com/kr-en/article/now-playing/): grouping of playback, save, repeat and queue actions.
- [Yandex Music desktop presentation](https://music.yandex.ru/download/): prominent primary action, collection entry points and persistent player. The desktop screenshots on the official page were viewed in the browser.
- [Yandex Music player/queue documentation](https://www.yandex.ru/support/music/ru/listening-and-settings/player-functions): distinction between queue and listening history.
- [Microsoft Windows icon construction](https://learn.microsoft.com/en-us/windows/apps/design/style/iconography/app-icon-construction): scaled icon sizes.

These references inform hierarchy and usability. Riffuna does not reuse their artwork, layouts, gradients, colors or recommendation features.

## Screenshots

All images below were rendered with `scripts/render_ui.py`, entirely offline, using a temporary synthetic library and original geometric fixture covers. They contain no user listening history or personal database. They are actual Qt renders, not mockups. The private baseline supplied for inspection is not included.

| State | Before (0.1.2) | After |
|---|---|---|
| Home | [before](before/01-home.png) | [after](after/01-home.png) |
| Search | [before](before/02-search.png) | [after](after/02-search.png) |
| Likes | [before](before/03-likes.png) | [after](after/03-likes.png) |
| History | [before](before/04-history.png) | [after](after/04-history.png) |
| Empty search | [before](before/05-empty.png) | [after](after/05-empty.png) |
| Queue closed | [before](before/06-likes-no-queue.png) | [after](after/06-likes-no-queue.png) |
| Minimum / queue open | — | [1000×650](after/07-minimum-queue.png) |
| Minimum / queue closed | — | [1000×650](after/08-minimum-no-queue.png) |
| Loading | — | [after](after/09-loading.png) |
| Search error | — | [after](after/10-error.png) |
| Empty likes | — | [after](after/11-empty-likes.png) |

## Verification

- Full suite on 0.1.2 base: **235 passed, 6 skipped**. Network opt-in tests remain skipped.
- New tests cover ICO frames, actual Qt icon loading, Windows identity, minimum geometry, compact badges, home navigation, unclipped empty-state text and a current recording outside the queue.
- Source and PyInstaller startup were checked on the native `windows` platform with isolated data directories and automatic exit. Both exited 0, reported all 15 icon sizes, `Riffuna.Desktop`, and nonzero `WM_GETICON` small/big handles. Evidence: [source](startup-source.json), [packaged](startup-packaged.json).
- The EXE's `RT_GROUP_ICON` contains the same 15 resolutions. This checks runtime and executable resources, not merely the existence of an ICO file. Existing pinned shortcuts may retain Windows' older icon cache; this test does not modify user shortcuts or the Explorer cache.
- No search, cache, audio transport, recommendation or dependency changes were made. Click-to-seek, hover time/percent previews, output selection, repeat-one/all and SeekAudioGuard are covered by the existing regression suite.

### Reproduce in this worktree

```powershell
C:\Projects\free-spotify\.venv\Scripts\python.exe scripts\render_ui.py --output .test-data\ui-after
C:\Projects\free-spotify\.venv\Scripts\python.exe -m pytest -q
.\build.ps1 -Python C:\Projects\free-spotify\.venv\Scripts\python.exe
.\scripts\check_ui_startup.ps1 -Python C:\Projects\free-spotify\.venv\Scripts\python.exe
.\scripts\check_ui_startup.ps1 -Packaged
```

`MUSICDESK_UI_REPORT` is an opt-in local smoke-test output. It contains only runtime/icon identity information, never track or library data. Neither the test build nor 0.2.0 is published by this branch.
