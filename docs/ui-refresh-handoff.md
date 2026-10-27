# Library UI refresh — ownership and integration

Work remains in C:/Projects/free-spotify on codex/0.2.0-player, preserving the existing dev4 changes. This contribution does not edit window.py, expanded_player.py, lyrics modules, motion.py, playback, storage, versioning or packaging.

## Shared visual tokens

- Background #101214; sidebar/surface #17191C / #191D21; hover #252B30; borders #30363C.
- Main text #F4F1E8; secondary #A3A8AD; quiet #92999F. Coral #FF875F; bright coral #FFA080.
- Current recording: #302B27 with #5B4033 edge. Selection: #38312C with #8C6049 edge. These are separate states.
- Spacing 8/12/16/24. Control radius 10, card 12, major surface 16.
- Library heading 36px, section 20px, tile 15px, row 14px, secondary 12–13px. Segoe UI; warm neutral, no purple, no gradients.

## Integration

`from musicdesk.surface_motion import install_surface_motion`

Call `install_surface_motion(window, window.motion_policy)` after the existing controls and shared MotionPolicy have been built. Calling it again after adding new buttons is safe. Icon buttons, tiles and library actions already attach themselves and discover window.motion_policy on their first interaction. The installer is useful for raw navigation/action QPushButtons from window.py.

The helper paints an input-transparent overlay, uses the existing Tween API, never applies graphics effects, never scales layout geometry and has no recurring idle timer. Hover/focus uses 150ms, exit/release 120ms, press 75ms. New input starts at the current value; hide/disable stops animations; reduced motion settles them. No audio objects or playback clocks are used.

Existing HomePage, PlaylistPage, ListTools, TrackRow, QueueRow and TrackList signal APIs are retained. Home's feature is the exact current or first recent recording. Empty libraries contain only actionable empty states; no demo content is introduced. Card art follows available width with a 208px ceiling. Ctrl/Shift selection is mirrored onto the row's selected property because a row can paint above the list item's selection background. Track IDs, queue order, drag and keyboard commands remain unchanged.

## Primary design references

Compositions and interaction principles only; no source or artwork copied:

- Spotify Desktop: https://newsroom.spotify.com/2023-06-20/spotify-desktop-experience-redesign-your-library-now-playing-views-customize/ — stable browse/library/player zones and local library filtering.
- Feishin: https://github.com/jeffvli/feishin — artwork and metadata hierarchy, collection browsing.
- Utaloom: https://github.com/cabrata/utaloom — desktop music composition, listen-again and explicit actions.
- YouTube Music desktop wrapper: https://github.com/pear-devs/pear-desktop (redirect from th-ch/youtube-music); no wrapper code copied.
- Yandex team design discussion: https://education.yandex.ru/knowledge/pochemu-yandeks-muzika-otkazalas-ot-notki-yet-another-podcast-27 — source available in search; direct URL currently redirects, so no screenshot or code from it was used.

## QA

Offline fixture renderer: `scripts/render_library_refresh.py --output PATH`. It creates temporary SQLite data, disables artwork fetch and prefetch, and labels every exported image OFFLINE FIXTURE. It never reads the user's library. Final test and screenshot evidence follows below.

## Frozen result — 2026-10-26

Production files are frozen for the main chat's integration/build:

- Modified: musicdesk/style.py, widgets.py, library_views.py, list_tools.py, track_list.py, icons.py.
- New: musicdesk/surface_motion.py.
- Tests: tests/test_surface_refresh.py (new), tests/test_library_views.py (responsive artwork geometry assertion replaces obsolete fixed 128px assertion).
- Renderer: scripts/render_library_refresh.py (new). Existing scripts/render_ui.py was not edited by this contribution.
- No changes by this contribution to window.py, expanded_player.py, lyrics*.py, motion.py, appearance.py, playback.py, storage.py, models.py, versions, existing EXE or packaging. Other shared-checkout changes remain intact. No commit, build, installation or publication performed here.

Validation:

- 123 passed in 100.68s. Exact suite: tests/test_surface_refresh.py tests/test_library_views.py tests/test_list_tools.py tests/test_visual_ui.py tests/test_ui_search.py tests/test_collection_integration.py tests/test_playlist_editing.py tests/test_queue_actions.py tests/test_collection_tools.py tests/test_library_ui.py tests/test_sliders.py; pytest -q -o faulthandler_timeout=15 --basetemp=.test-data/visual-refresh-final. Log: .test-data/visual-refresh-final.log.
- The successful run emitted two 15-second faulthandler threshold dumps during fixture reapplication of QApplication.setStyleSheet (tests/test_ui_search.py:33 and tests/test_sliders.py:20). It completed without interruption or failing tests. This does not establish the cause of any earlier hanging run.
- Targeted teardown/result-population suite: 11 passed in 9.72s, log .test-data/visual-refresh-teardown.log. Covers three clear/repopulate cycles of 120 rows with garbage collection, interruption, shared reduced motion, single click intents, transparent feedback, responsive original cached art, exact hero recording identity and selection clearing.
- First regression exposed a SurfaceMotion event filter accessing fields while Python/Qt dismantled an old wrapper. Corrected using weak references and a teardown guard; the regression tests include this lifecycle case. No errors were suppressed in pytest.
- git diff --check passes for the modified tracked files; Git only warns about repository LF normalization of Windows working-copy line endings.

Fifteen final OFFLINE FIXTURE PNGs are under:
C:/Users/Nikita/.codex/visualizations/2026/10/25/01a171bf-9a9b-74b1-a25a-d7682b98cf9f/

Names: refresh-home-{1280,1000}, refresh-home-queue-{1280,1000}, refresh-playlists-{1280,1000}, refresh-tracks-{1280,1000}, refresh-selected-{1280,1000}, refresh-filter-empty-{1280,1000}, refresh-loading, refresh-error, refresh-home-empty. Each is explicitly labelled OFFLINE FIXTURE; empty-home capture uses a separate genuinely empty temporary database. Sizes are 1280x800 and 1000x650 plus a 26px export-only fixture caption. No demo records or fixture art appear in normal application code.

Integration note: when the owner restores selection while QListWidget signals are blocked, call track_list._selection_surfaces() after restoring it. The main chat has already wired that call and install_surface_motion(self, self.motion_policy).
