# Historical Flutter exploration — superseded by Kotlin

The Flutter/FastAPI direction below was cancelled. Riffuna 0.2.0 uses Kotlin/Compose locally without a remote Riffuna server; see [kotlin-migration.md](kotlin-migration.md). The unintegrated Dart drafts are archived locally and are not part of the active application.

# Riffuna presentation handoff — stack decision pending

Status: Flutter implementation stopped after the main chat relayed the user's discussion of Kotlin / KMP / Compose versus Flutter. No further client code should be added until the main chat confirms the selected stack and file ownership. Python + FastAPI remains the backend direction; this document does not claim that the backend or Flutter app is implemented or running.

## Actual files created by the presentation chat

- client/lib/ui/riffuna_theme.dart: draft dark ThemeData, neutral/coral color tokens, typography, button/input/slider/navigation themes, reduced-motion duration helper and duration formatting.
- client/lib/ui/components.dart: draft artwork widget with honest unavailable-art fallback; interruptible hover/focus/press surface; artwork card; recording row and actions menu; empty/loading state; seek control with a local drag preview and one commit on release; transport controls. These invoke the supplied controller contract and do not create audio or network API clients. Image.network fetches only the provided artwork URL.
- This document.

Not created: RiffunaShell, library screens, responsive navigation shell, mini-player layout, queue screen, expanded player, lyric CustomPainter, line following, client tests. Do not integrate these drafts as a completed UI. No Flutter/Dart SDK analysis, formatter, widget test, runtime, screenshots, build or installation was performed for these Dart files. No SDK packages or dependencies were downloaded by this contribution. The controller/model files did not exist when these drafts were written; their imports await the main chat's implementation. Preserve source drafts until the stack decision; do not delete or convert other participants' work.

## Supplied ownership and controller contract

Presentation ownership was limited to client/lib/ui/*.dart and docs/flutter-ui-handoff.md. The main chat owns main.dart, app_controller.dart, models.dart, pubspec, FastAPI, API client and audio implementation. Intended entry point, not yet written: RiffunaShell({required RiffunaController controller}), driven by ListenableBuilder.

RiffunaController extends ChangeNotifier:

- bool loading, playing, queueVisible, expanded, lyricsFocus, shuffle, approximateWords.
- String view, query, status, repeatMode.
- List<Track> visibleTracks, likes, history, queue; Track? current.
- int queueIndex, positionMs, durationMs; double volume in 0..1.
- List<PlaylistSummary> playlists; List<LyricLine> lyrics.
- Future<void> methods: search(String), showView(String), openPlaylist(int), play(Track), enqueue(Track), playNext(Track), next(), previous(), toggle(), seek(int), setVolume(double), toggleLike(Track), clearQueue(), createPlaylist(String), toggleShuffle(), cycleRepeat().
- void methods: openNowPlaying(bool), setLyricsFocus(bool), toggleQueue().

Models supplied to the presentation chat:

- Track: immutable id, title, artist, thumbnail, version (String), duration (seconds, int).
- PlaylistSummary: id (int), name, description, thumbnail, trackCount.
- LyricLine: nullable startMs/endMs, text, List<LyricWord> words.
- LyricWord: startMs, endMs, text. Controller supplies provider or computed word arrays; approximateWords must be disclosed.

No API was supplied for removing one queue item, adding selected records to an existing playlist, importing lyrics, changing backend URL, selecting output devices or retrieving detailed lyrics availability/source states. Do not show working controls for absent operations. Add contract methods explicitly when those features are implemented. Like state derives from exact recording ID membership in likes, not from title equivalence.

## Design preserved independently of client stack

| Token | Value |
|---|---|
| Background | #101214 |
| Sidebar / card | #17191C / #191D21 |
| Hover / border | #252B30 / #30363C |
| Main / secondary / quiet text | #F4F1E8 / #A3A8AD / #92999F |
| Accent / bright accent | #FF875F / #FFA080 |
| Current recording | #302B27, edge #5B4033 |
| Selected recording | #38312C, edge #8C6049 |
| Warm secondary action | #E6D8B9 |

Typography: library title 36/700, feature recording 30/700, section 20/700, card 15/600, row 14/600, secondary 12–13/400, kicker 10/600 with 1.5–1.8 tracking. Windows Segoe UI; mobile system sans with Cyrillic. Support font scaling; never hard-clip text to preserve a screenshot height. Spacing 8/12/16/24; radii controls 10, cards 12, large surface 16. No purple, no decorative gradients.

Desktop composition: navigation on the left, real library/search content in the center, optional queue on the right, persistent player below. At widths below 720 the requested Flutter design uses bottom NavigationBar, mini-player and a separate queue surface. Measure available container width; do not choose layout from operating system alone. Artwork is the visual lead. Home feature uses the exact current or first recent recording; empty libraries have useful actions and no demonstration data.

Collection rows must keep fixed action hit areas while title/artist text shrinks with ellipsis. Selection and current playback are independent. Keep full metadata in semantics/tooltips where appropriate. Desktop supports keyboard/focus and Ctrl/Shift selection; touch uses long-press selection and comfortable hit targets. Navigation/filter/sort must preserve exact IDs and saved playlist/queue ordering.

Motion: hover/focus 150ms, exit/release 120ms, press 75ms, page reveal 160ms. Interrupt from the current visual value. A decorative card action can rise 5 logical units; layout and scroll must not be rescaled. Stop finished/hidden animations. Respect OS reduced motion and any explicit user preference. Do not run a ticker or timer to invent audio progress.

Lyrics constraints for the future implementation: paint progressive fill from actual client position samples and supplied word ranges, shape the entire text paragraph before clipping word highlights, retain Unicode/bidirectional layout, snap on pause/seek/track change, and never claim computed words are provider-exact. Manual browsing disables line follow until the user resumes it. Every seek remains an intent until the player reports its actual position. The lyric painter and follow controller have NOT been implemented in this draft.

## Preserved Qt visual evidence, not Flutter execution evidence

See docs/ui-refresh-handoff.md for the completed earlier Qt contribution. The installed user build remains dev4; newer screenshot source version labels do not mean a new build was installed. This contribution built or installed neither Qt nor Flutter.

The last narrow Qt QueueRow fix was saved before the stack change: title/artist use an ignored horizontal size policy so play/remove actions fit a narrow row. After that change: 46 targeted tests passed in 12.97s (surface refresh, queue actions, library UI), log .test-data/visual-refresh-queue-final.log. Earlier broad UI run: 123 passed in 100.68s. The offline renderer additionally flushes native item layouts after resize/show before capture. This corrected stale capture geometry; actual final captured queue row widths are 236px at 1280 and 200px at 1000, with remove buttons inside those bounds.

Fifteen PNGs, all labelled OFFLINE FIXTURE, live under:
C:/Users/Nikita/.codex/visualizations/2026/10/25/01a171bf-9a9b-74b1-a25a-d7682b98cf9f/

- refresh-home-1280.png, refresh-home-1000.png.
- refresh-home-queue-1280.png, refresh-home-queue-1000.png.
- refresh-playlists-1280.png, refresh-playlists-1000.png.
- refresh-tracks-1280.png, refresh-tracks-1000.png.
- refresh-selected-1280.png, refresh-selected-1000.png.
- refresh-filter-empty-1280.png, refresh-filter-empty-1000.png.
- refresh-loading.png, refresh-error.png, refresh-home-empty.png.

These are temporary synthetic libraries and original QA illustrations. They are reference compositions for whichever stack is selected, not screenshots of a running Flutter app.

## Primary implementation references already checked

- https://docs.flutter.dev/ui/adaptive-responsive/general
- https://api.flutter.dev/flutter/widgets/ListenableBuilder-class.html
- https://api.flutter.dev/flutter/painting/TextPainter-class.html
- https://api.flutter.dev/flutter/widgets/ScrollNotification-class.html
- https://api.flutter.dev/flutter/material/Slider/onChangeEnd.html
- https://api.flutter.dev/flutter/widgets/MediaQueryData/disableAnimations.html

No source code or artwork was copied from GPL music clients. Their compositions informed the earlier design only; links and caveats are in docs/ui-refresh-handoff.md.
