package riffuna.core

import kotlin.test.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.test.runTest

class StateProjectionTest {
    @Test
    fun timelineTicksDoNotInvalidateScreensButPlaybackErrorsStillDo() = runTest {
        val base =
            AppState(playback = PlaybackUiState(current = Track("a", "Song"), durationMs = 180000))
        val ticks = (0..20).map { base.copy(playback = base.playback.copy(positionMs = it * 100L)) }
        val failed =
            ticks.last().copy(playback = ticks.last().playback.copy(playbackError = "Failed"))
        val screens =
            (ticks + failed).asFlow().map { it.screenSnapshot() }.distinctUntilChanged().toList()
        assertEquals(2, screens.size)
        assertNull(screens.first().playbackError)
        assertEquals("Failed", screens.last().playbackError)
        assertEquals(2000, ticks.last().positionMs)
        assertSame(base.libraryState, ticks.last().libraryState)
    }

    @Test
    fun durationControlsAndLibraryChangesRemainObservable() {
        val base = AppState()
        val changes =
            listOf(
                base.copy(playback = base.playback.copy(durationMs = 180000)),
                base.copy(playback = base.playback.copy(playing = true)),
                base.copy(playback = base.playback.copy(volume = .2f)),
                base.copy(queueState = base.queueState.copy(shuffle = true)),
                base.copy(libraryState = base.libraryState.copy(likes = listOf(Track("a", "Song")))),
            )
        changes.forEach { assertNotEquals(base.screenSnapshot(), it.screenSnapshot()) }
    }
}
