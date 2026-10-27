package riffuna.core

import kotlin.random.Random
import kotlin.test.*

class PlaybackQueuePropertyTest {
    private fun track(id: Int) = Track(id.toString(), "Song $id", "Artist", 180)

    @Test
    fun randomEditingSequencesKeepUniqueIdsAndAValidAnchor() {
        repeat(100) { seed ->
            val random = Random(seed)
            val queue = PlaybackQueue(random = Random(seed))
            repeat(250) { operation ->
                val before = queue.current?.id
                val id = random.nextInt(20)
                var anchorShouldSurvive = true
                when (random.nextInt(7)) {
                    0 -> queue.enqueue(listOf(track(id), track(id)))
                    1 -> {
                        queue.remove(id.toString())
                        anchorShouldSurvive = before != id.toString()
                    }
                    2 -> queue.reorder(queue.tracks.shuffled(random).map { it.id })
                    3 -> queue.move(id.toString(), if (random.nextBoolean()) 1 else -1)
                    4 -> queue.enqueueNext(track(id))
                    5 -> {
                        queue.tracks.randomOrNull(random)?.let(queue::begin)
                        anchorShouldSurvive = false
                    }
                    6 -> {
                        if (random.nextInt(10) == 0) {
                            queue.reset()
                            anchorShouldSurvive = false
                        }
                    }
                }
                val message = "seed=$seed operation=$operation"
                val ids = queue.tracks.map { it.id }
                assertEquals(ids.size, ids.distinct().size, message)
                assertTrue(queue.index == -1 || queue.index in queue.tracks.indices, message)
                assertEquals(queue.priorityIds.size, queue.priorityIds.distinct().size, message)
                assertTrue(queue.priorityIds.all { it in ids }, message)
                assertTrue(queue.continuationIds.orEmpty().all { it in ids }, message)
                if (anchorShouldSurvive) assertEquals(before, queue.current?.id, message)
            }
        }
    }

    @Test
    fun shuffleVisitsEachEntryExactlyOnceAndPrefetchDoesNotConsumeIt() {
        repeat(100) { seed ->
            val tracks = (0..seed % 20).map(::track)
            val queue = PlaybackQueue(tracks, random = Random(seed))
            queue.begin(tracks.first())
            val seen = mutableSetOf(tracks.first().id)
            repeat(tracks.size - 1) {
                val planned = queue.peekNext(true, RepeatMode.OFF)
                repeat(5) { assertEquals(planned, queue.peekNext(true, RepeatMode.OFF)) }
                val step = assertNotNull(queue.next(true, RepeatMode.OFF))
                assertEquals(planned, queue.tracks[step.index])
                queue.begin(queue.tracks[step.index], recordHistory = step.recordHistory)
                assertTrue(seen.add(queue.current!!.id), "Repeated shuffle entry seed=$seed")
            }
            assertEquals(tracks.map { it.id }.toSet(), seen)
            assertNull(queue.next(true, RepeatMode.OFF))
            assertNull(queue.peekNext(true, RepeatMode.OFF))
            val restart = assertNotNull(queue.next(true, RepeatMode.ALL))
            if (tracks.size > 1) assertNotEquals(queue.index, restart.index)
        }
    }

    @Test
    fun shuffleBackAndForwardFollowHistoryAndExplicitPriorityWins() {
        val queue = PlaybackQueue((0..9).map(::track), random = Random(42))
        queue.begin(queue.tracks.first())
        val step = assertNotNull(queue.next(true, RepeatMode.OFF))
        queue.begin(queue.tracks[step.index])
        val selected = queue.current
        val back = assertNotNull(queue.previous(true))
        queue.begin(queue.tracks[back.index], recordHistory = false)
        assertEquals(selected, queue.peekNext(true, RepeatMode.OFF))
        val forward = assertNotNull(queue.next(true, RepeatMode.OFF))
        queue.begin(queue.tracks[forward.index], recordHistory = false)
        queue.enqueueNext(track(50))
        queue.enqueueNext(track(50))
        assertEquals(track(50), queue.peekNext(true, RepeatMode.OFF))
        assertEquals(track(50), queue.tracks[assertNotNull(queue.next(true, RepeatMode.OFF)).index])
    }

    @Test
    fun restoredStateSanitizesDuplicatesAndKeepsRemovedCurrentContinuation() {
        val tracks = (0..3).map(::track)
        val queue = PlaybackQueue(tracks, 1)
        queue.remove("1")
        val restored = PlaybackQueue(queue.tracks, queue.index)
        restored.restore(listOf("2", "2", "missing"), queue.continuationIds)
        assertEquals(listOf("2"), restored.priorityIds)
        val step = assertNotNull(restored.next(false, RepeatMode.OFF))
        restored.begin(restored.tracks[step.index])
        assertEquals(track(2), restored.current)
        restored.remove("2")
        restored.remove("3")
        assertNull(restored.next(false, RepeatMode.OFF))
        assertEquals(0, restored.next(false, RepeatMode.ALL)?.index)
    }

    @Test
    fun malformedPersistedRepeatModeFallsBackToOff() {
        assertEquals(RepeatMode.OFF, RepeatMode.fromKey("invalid"))
        assertEquals(RepeatMode.ONE, RepeatMode.fromKey("one"))
        assertEquals(RepeatMode.OFF, RepeatMode.ALL.next())
    }
}
