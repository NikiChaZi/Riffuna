package riffuna.core

import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.*

@OptIn(ExperimentalCoroutinesApi::class)
class QueueTest {
    private fun track(id: Char) = Track(id.toString().repeat(11), "Song $id", "Artist", 180)

    @Test
    fun directSelectionDoesNotEnqueueAndClearKeepsCurrent() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val library = MemoryLibrary()
        val audio = FakeAudio()
        val controller = LocalController(library, FakeSource(), audio)
        try {
            val a = track('a')
            val b = track('b')
            controller.enqueue(a)
            controller.play(b)
            assertEquals(listOf(a), controller.state.value.queue)
            assertEquals(b, controller.state.value.current)
            controller.clearQueue()
            assertEquals(b, controller.state.value.current)
            assertTrue(controller.state.value.queue.isEmpty())
            assertEquals(0, audio.opened)
        } finally {
            controller.close()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun playNextDeduplicatesAndTakesPriorityOverShuffle() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val library = MemoryLibrary()
        val controller = LocalController(library, FakeSource(), FakeAudio())
        try {
            val a = track('a')
            val b = track('b')
            val c = track('c')
            listOf(a, b, c).forEach(controller::enqueue)
            controller.play(a)
            controller.toggleShuffle()
            controller.playNext(c)
            controller.playNext(c)
            assertEquals(listOf(a, c, b), controller.state.value.queue)
            controller.next()
            assertEquals(c, controller.state.value.current)
            assertEquals(3, controller.state.value.queue.size)
        } finally {
            controller.close()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun likesAndQueuesStayIndependent() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val library = MemoryLibrary()
        val controller = LocalController(library, FakeSource(), FakeAudio())
        try {
            val a = track('a')
            controller.toggleLike(a)
            controller.enqueue(a)
            controller.clearQueue()
            assertEquals(listOf(a), controller.state.value.likes)
        } finally {
            controller.close()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun removingPlayingEntryKeepsCurrentAndContinuesFromItsSuccessor() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val controller = LocalController(MemoryLibrary(), FakeSource(), FakeAudio())
        try {
            val a = track('a')
            val b = track('b')
            val c = track('c')
            listOf(a, b, c).forEach(controller::enqueue)
            controller.play(b)
            controller.removeFromQueue(b.id)
            assertEquals(b, controller.state.value.current)
            assertEquals(listOf(a, c), controller.state.value.queue)
            controller.next()
            assertEquals(c, controller.state.value.current)
        } finally {
            controller.close()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun clickingQueueFromLikesDoesNotReplaceQueueWithLikedTracks() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val controller = LocalController(MemoryLibrary(), FakeSource(), FakeAudio())
        try {
            val a = track('a')
            val b = track('b')
            val c = track('c')
            listOf(a, b).forEach(controller::enqueue)
            controller.toggleLike(c)
            controller.showView(LibraryView.LIKES)
            controller.playQueueTrack(b.id)
            assertEquals(listOf(a, b), controller.state.value.queue)
            assertEquals(b, controller.state.value.current)
            controller.moveInQueue(b.id, -1)
            assertEquals(listOf(b, a), controller.state.value.queue)
            assertEquals(0, controller.state.value.queueIndex)
        } finally {
            controller.close()
            Dispatchers.resetMain()
        }
    }
}

private class FakeSource : MusicSource {
    override suspend fun search(query: String, limit: Int) = emptyList<Track>()

    override suspend fun resolve(track: Track): AudioSource {
        awaitCancellation()
    }
}

private class FakeAudio : AudioEngine {
    override val state = MutableStateFlow(AudioState())
    var opened = 0

    override suspend fun open(source: AudioSource) {
        opened++
    }

    override fun toggle() {}

    override fun pause() {}

    override fun resume() {}

    override fun seek(positionMs: Long) {}

    override fun setVolume(volume: Float) {}

    override fun close() {}
}

private class MemoryLibrary : MusicLibrary {
    private val liked = mutableListOf<Track>()
    private var queued = emptyList<Track>() to -1
    private var selected: Track? = null

    override fun likes() = liked.toList()

    override fun history() = emptyList<Track>()

    override fun queue() = queued

    override fun current() = selected

    override fun saveQueue(tracks: List<Track>, index: Int, current: Track?) {
        queued = tracks to index
        selected = current
    }

    override fun like(track: Track, value: Boolean) {
        liked.removeAll { it.id == track.id }
        if (value) liked.add(track)
    }

    override fun recordPlay(track: Track) {}

    override fun playlists() = emptyList<PlaylistSummary>()

    override fun playlistTracks(id: Long) = emptyList<Track>()

    override fun createPlaylist(name: String) = 1L

    override fun addToPlaylist(id: Long, tracks: List<Track>) {}

    override fun editPlaylist(id: Long, name: String, description: String) {}

    override fun deletePlaylist(id: Long) {}

    override fun removeFromPlaylist(id: Long, trackId: String) {}

    override fun setting(name: String, default: String) = default

    override fun setSetting(name: String, value: String) {}

    override fun reorderPlaylist(id: Long, ids: List<String>) {}

    override fun duplicatePlaylist(id: Long) = 1L

    override fun setPreferred(original: Track, replacement: Track?) {}

    override fun preferred(track: Track) = track

    override fun close() {}
}
