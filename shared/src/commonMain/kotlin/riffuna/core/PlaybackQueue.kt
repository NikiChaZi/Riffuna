package riffuna.core

import kotlin.random.Random

/** Queue order and traversal are independent from audio, persistence and UI. */
class PlaybackQueue(
    initialTracks: List<Track> = emptyList(),
    initialIndex: Int = -1,
    private val random: Random = Random.Default,
) {
    data class Step(val index: Int, val recordHistory: Boolean = true)

    var tracks: List<Track> = initialTracks.distinctBy { it.id }
        private set

    var index: Int =
        initialTracks.getOrNull(initialIndex)?.id?.let { id -> tracks.indexOfFirst { it.id == id } }
            ?: -1
        private set

    private val priority = mutableListOf<String>()
    private val visited = mutableSetOf<String>()
    private val traversal = mutableListOf<String>()
    private var traversalIndex = -1
    private var continuation: List<String>? = null
    private var plannedShuffle: String? = null

    val current: Track?
        get() = tracks.getOrNull(index)

    val priorityIds: List<String>
        get() = priority.toList()

    val continuationIds: List<String>?
        get() = continuation?.toList()

    init {
        current?.let {
            visited.add(it.id)
            traversal.add(it.id)
            traversalIndex = 0
        }
    }

    fun restore(priorityIds: List<String>, continuationIds: List<String>?) {
        val ids = tracks.map { it.id }.toSet()
        priority.clear()
        priority.addAll(priorityIds.distinct().filter { it in ids })
        continuation = if (index == -1) continuationIds?.distinct()?.filter { it in ids } else null
    }

    fun enqueue(items: List<Track>): Int {
        val ids = tracks.map { it.id }.toMutableSet()
        val added = items.filter { ids.add(it.id) }
        tracks = tracks + added
        return added.size
    }

    fun reorder(ids: List<String>) {
        require(ids.size == tracks.size && ids.toSet() == tracks.map { it.id }.toSet())
        val anchor = current?.id
        val byId = tracks.associateBy { it.id }
        tracks = ids.map { byId.getValue(it) }
        index = tracks.indexOfFirst { it.id == anchor }
    }

    fun move(id: String, offset: Int) {
        require(offset == -1 || offset == 1)
        val from = tracks.indexOfFirst { it.id == id }
        val to = from + offset
        if (from < 0 || to !in tracks.indices) return
        val ids = tracks.map { it.id }.toMutableList()
        ids.add(to, ids.removeAt(from))
        reorder(ids)
    }

    fun enqueueNext(track: Track) {
        if (current?.id == track.id) return
        val anchor = current?.id
        val remaining = tracks.filter { it.id != track.id }.toMutableList()
        index = remaining.indexOfFirst { it.id == anchor }
        remaining.add((index + 1).coerceIn(0, remaining.size), track)
        tracks = remaining
        priority.removeAll { it == track.id }
        priority.add(0, track.id)
        continuation = continuation?.let { listOf(track.id) + it.filter { key -> key != track.id } }
    }

    fun begin(track: Track, context: List<Track> = tracks, recordHistory: Boolean = true) {
        val unique = context.distinctBy { it.id }
        if (unique.map { it.id } != tracks.map { it.id }) reset(unique) else tracks = unique
        continuation = null
        plannedShuffle = null
        index = tracks.indexOfFirst { it.id == track.id }
        if (index >= 0) visited.add(track.id)
        priority.removeAll { it == track.id }
        if (recordHistory && index >= 0) {
            if (traversalIndex + 1 < traversal.size)
                traversal.subList(traversalIndex + 1, traversal.size).clear()
            if (traversal.lastOrNull() != track.id) traversal.add(track.id)
            traversalIndex = traversal.lastIndex
        }
    }

    fun reset(items: List<Track> = emptyList()) {
        tracks = items.distinctBy { it.id }
        index = -1
        priority.clear()
        visited.clear()
        traversal.clear()
        traversalIndex = -1
        continuation = null
        plannedShuffle = null
    }

    fun remove(id: String) {
        val anchor = current?.id
        continuation =
            if (anchor == id) tracks.drop(index + 1).map { it.id }.filter { it != id }
            else continuation?.filter { it != id }
        tracks = tracks.filter { it.id != id }
        index = tracks.indexOfFirst { it.id == anchor }
        priority.removeAll { it == id }
        visited.remove(id)
        if (plannedShuffle == id) plannedShuffle = null
        // Keep traversal slots until navigation: a removed current entry is a history boundary.
    }

    fun shuffleChanged() {
        visited.clear()
        current?.let { visited.add(it.id) }
        plannedShuffle = null
    }

    private fun queued(id: String?): Track? = tracks.firstOrNull { it.id == id }

    private fun forward(): Int? =
        (traversalIndex + 1..traversal.lastIndex).firstOrNull { queued(traversal[it]) != null }

    private fun candidates(repeat: RepeatMode): List<Track> {
        val unplayed = tracks.filter { it.id !in visited }
        if (unplayed.isNotEmpty() || repeat != RepeatMode.ALL) return unplayed
        return tracks.filter { it.id != current?.id }.ifEmpty { tracks }
    }

    /** Repeated prefetch calls select the same next shuffle entry until the queue changes. */
    fun peekNext(shuffle: Boolean, repeat: RepeatMode): Track? {
        priority.firstNotNullOfOrNull(::queued)?.let {
            return it
        }
        if (shuffle) {
            forward()?.let {
                return queued(traversal[it])
            }
            val candidates = candidates(repeat)
            return candidates.firstOrNull { it.id == plannedShuffle }
                ?: candidates.randomOrNull(random)?.also { plannedShuffle = it.id }
        }
        continuation?.let { tail ->
            return tail.firstNotNullOfOrNull(::queued)
                ?: if (repeat == RepeatMode.ALL) tracks.firstOrNull() else null
        }
        return tracks.getOrNull(index + 1)
            ?: if (repeat == RepeatMode.ALL) tracks.firstOrNull() else null
    }

    fun next(shuffle: Boolean, repeat: RepeatMode): Step? {
        if (tracks.isEmpty()) return null
        priority.firstNotNullOfOrNull(::queued)?.let {
            return Step(tracks.indexOf(it))
        }
        if (shuffle) {
            forward()?.let { next ->
                traversalIndex = next
                return Step(tracks.indexOfFirst { it.id == traversal[next] }, recordHistory = false)
            }
            val candidates = candidates(repeat)
            if (candidates.isEmpty()) return null
            if (tracks.none { it.id !in visited } && repeat == RepeatMode.ALL) {
                visited.clear()
                current?.let { visited.add(it.id) }
            }
            val selected =
                candidates.firstOrNull { it.id == plannedShuffle } ?: candidates.random(random)
            plannedShuffle = null
            return Step(tracks.indexOf(selected))
        }
        val candidate = peekNext(false, repeat) ?: return null
        return Step(tracks.indexOf(candidate))
    }

    fun previous(shuffle: Boolean): Step? {
        if (!shuffle) return (index - 1).takeIf { it in tracks.indices }?.let(::Step)
        val previous =
            (traversalIndex - 1 downTo 0).firstOrNull { queued(traversal[it]) != null }
                ?: return null
        traversalIndex = previous
        return Step(tracks.indexOfFirst { it.id == traversal[previous] }, recordHistory = false)
    }
}
