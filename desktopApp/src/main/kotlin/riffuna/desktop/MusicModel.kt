package riffuna.desktop

import ai.onnxruntime.*
import java.io.DataInputStream
import java.nio.FloatBuffer
import java.nio.file.*
import java.text.Normalizer
import java.util.Locale
import java.util.PriorityQueue
import kotlin.math.*
import kotlinx.serialization.json.*
import org.bouncycastle.crypto.digests.Blake2bDigest
import riffuna.core.*

/** Music-only Two-Tower retrieval and CatBoost inference, entirely inside the JVM. */
class MusicModel(
    private val directory: Path,
    private val artistTags: (String) -> List<String> = { emptyList() },
) : AutoCloseable {
    private data class Entry(
        val id: String,
        val title: String,
        val artist: String,
        val genres: List<String>,
    )

    private val env = OrtEnvironment.getEnvironment()
    private val options =
        OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(1)
            setInterOpNumThreads(1)
        }
    private val tower: OrtSession
    private val ranker: OrtSession
    private val entries: List<Entry>
    private val columns: Array<IntArray>
    private val values: Array<FloatArray>
    private val vectors: FloatArray
    private val popularity: FloatArray
    private val featureDim: Int
    private val genreDim: Int
    private val vectorDim: Int
    private val exact: Map<Pair<String, String>, Int>
    private val artists: Map<String, List<Int>>
    private val genreIndex: Map<String, Int>

    init {
        val manifest =
            Json.parseToJsonElement(Files.readString(directory.resolve("manifest.json"))).jsonObject
        require(
            manifest["domain"]?.jsonPrimitive?.content == "music" &&
                manifest["schema"]?.jsonPrimitive?.int == 1
        )
        entries =
            Json.parseToJsonElement(Files.readString(directory.resolve("catalog.json")))
                .jsonArray
                .map { row ->
                    val item = row.jsonObject
                    Entry(
                        item["id"]!!.jsonPrimitive.content,
                        item["title"]!!.jsonPrimitive.content,
                        item["artist"]!!.jsonPrimitive.content,
                        item["genres"]?.jsonArray.orEmpty().map { it.jsonPrimitive.content },
                    )
                }
        genreIndex =
            Json.parseToJsonElement(Files.readString(directory.resolve("genre_names.json")))
                .jsonArray
                .mapIndexed { i, v -> normal(v.jsonPrimitive.content) to i }
                .toMap()
        DataInputStream(Files.newInputStream(directory.resolve("catalog.bin")).buffered()).use {
            input ->
            require(String(input.readNBytes(8), Charsets.US_ASCII) == "RIFMUS01")
            val count = input.readInt()
            featureDim = input.readInt()
            genreDim = input.readInt()
            vectorDim = input.readInt()
            require(
                count == entries.size &&
                    count in 1..1_000_000 &&
                    featureDim in 1..65536 &&
                    genreDim in 1..featureDim &&
                    vectorDim in 1..2048
            )
            columns = Array(count) { IntArray(0) }
            values = Array(count) { FloatArray(0) }
            for (row in 0 until count) {
                val size = input.readInt()
                require(size in 0..featureDim)
                columns[row] = IntArray(size)
                values[row] = FloatArray(size)
                for (column in 0 until size) {
                    columns[row][column] = input.readUnsignedShort()
                    values[row][column] = input.readFloat()
                    require(columns[row][column] < featureDim && values[row][column].isFinite())
                }
            }
            vectors = FloatArray(count * vectorDim) { input.readFloat() }
            popularity = FloatArray(count) { input.readFloat() }
            require(input.read() == -1)
        }
        exact =
            entries.indices.associateBy { normal(entries[it].artist) to normal(entries[it].title) }
        artists = entries.indices.groupBy { normal(entries[it].artist) }
        tower = env.createSession(directory.resolve("user_tower.onnx").toString(), options)
        ranker =
            try {
                env.createSession(directory.resolve("ranker.onnx").toString(), options)
            } catch (e: Exception) {
                tower.close()
                options.close()
                throw e
            }
    }

    private fun match(track: Track): Pair<List<Int>, Boolean> {
        val artist = normal(track.artist)
        val title = normal(track.title).removePrefix("$artist ")
        exact[artist to title]?.let {
            return listOf(it) to true
        }
        val same = artists[artist].orEmpty()
        same
            .firstOrNull { similarity(title, normal(entries[it].title)) >= .92 }
            ?.let {
                return listOf(it) to true
            }
        return same to false
    }

    private fun dense(ids: List<Int>): FloatArray {
        val result = FloatArray(featureDim)
        ids.forEach { row ->
            columns[row].forEachIndexed { i, c -> result[c] += values[row][i] / ids.size }
        }
        return result
    }

    private fun tagged(track: Track, tags: List<String>): FloatArray? {
        val genre = tags.mapNotNull { genreIndex[normal(it)] }.distinct()
        if (genre.isEmpty()) return null
        val result = FloatArray(featureDim)
        val norm = sqrt(genre.size.toFloat())
        genre.forEach { result[it] = 1 / norm }
        result[genreDim + bucket(normal(track.artist))] = .5f
        normal(track.title)
            .split(' ')
            .filter { it.isNotBlank() }
            .distinct()
            .forEach { result[genreDim + 128 + bucket(it)] += .2f }
        return result
    }

    internal fun query(profile: FloatArray): FloatArray =
        run(tower, "profile", profile, 1, featureDim)

    internal fun score(features: FloatArray, count: Int): FloatArray =
        run(ranker, "features", features, count, 8)

    private fun run(
        session: OrtSession,
        name: String,
        data: FloatArray,
        rows: Int,
        dim: Int,
    ): FloatArray {
        OnnxTensor.createTensor(
                env,
                FloatBuffer.wrap(data),
                longArrayOf(rows.toLong(), dim.toLong()),
            )
            .use { tensor ->
                session.run(mapOf(name to tensor)).use { result ->
                    val buffer = (result[0] as OnnxTensor).floatBuffer
                    return FloatArray(buffer.remaining()).also { buffer.get(it) }
                }
            }
    }

    @Synchronized
    fun recommend(seeds: List<Track>, excluded: List<Track>, limit: Int = 25): List<Suggestion> {
        val used = seeds.take(100)
        val profiles = mutableListOf<FloatArray>()
        val exclude = mutableSetOf<Int>()
        val tags =
            used
                .filter { match(it).first.isEmpty() }
                .map { it.artist }
                .distinct()
                .take(6)
                .associateWith { artistTags(it) }
        used.forEach { track ->
            val (ids, exact) = match(track)
            if (ids.isNotEmpty()) {
                profiles.add(dense(ids))
                if (exact) exclude.addAll(ids)
            } else tagged(track, tags[track.artist].orEmpty())?.let(profiles::add)
        }
        excluded.take(500).forEach {
            val (ids, exact) = match(it)
            if (exact) exclude.addAll(ids)
        }
        if (profiles.isEmpty()) return emptyList()
        val profile = FloatArray(featureDim)
        profiles.forEach { p -> p.forEachIndexed { i, v -> profile[i] += v / profiles.size } }
        val query = query(profile)
        val top = PriorityQueue<Pair<Int, Float>>(compareBy { it.second })
        entries.indices.forEach { row ->
            if (row !in exclude) {
                var score = 0f
                for (i in 0 until vectorDim) score += vectors[row * vectorDim + i] * query[i]
                if (top.size < 200) top.add(row to score)
                else if (score > top.peek().second) {
                    top.poll()
                    top.add(row to score)
                }
            }
        }
        val candidates = top.toList().sortedByDescending { it.second }
        if (candidates.isEmpty()) return emptyList()
        val features = FloatArray(candidates.size * 8)
        val affinities = used.groupingBy { normal(it.artist) }.eachCount()
        candidates.forEachIndexed { index, (row, retrieval) ->
            val offset = index * 8
            features[offset] = retrieval
            var genreDot = 0f
            var allDot = 0f
            var genreCount = 0
            columns[row].forEachIndexed { i, c ->
                val value = values[row][i]
                allDot += value * profile[c]
                if (c < genreDim) {
                    genreDot += value * profile[c]
                    genreCount++
                }
            }
            features[offset + 1] = genreDot
            features[offset + 2] =
                (affinities[normal(entries[row].artist)] ?: 0).toFloat() /
                    used.size.coerceAtLeast(1)
            features[offset + 3] = ln1p(popularity[row])
            features[offset + 4] = ln1p(profiles.size.toFloat())
            features[offset + 5] = genreCount.toFloat()
            features[offset + 6] =
                profiles.maxOf { p ->
                    var sum = 0f
                    columns[row].forEachIndexed { i, c ->
                        if (c < genreDim) sum += values[row][i] * p[c]
                    }
                    sum
                }
            features[offset + 7] = allDot
        }
        val scores = score(features, candidates.size)
        val counts = mutableMapOf<String, Int>()
        val result = mutableListOf<Suggestion>()
        candidates.indices
            .sortedByDescending { scores[it] }
            .forEach { index ->
                val entry = entries[candidates[index].first]
                if (result.size < limit.coerceIn(1, 50) && (counts[entry.artist] ?: 0) < 3) {
                    result.add(Suggestion(entry.id, entry.title, entry.artist, entry.genres))
                    counts[entry.artist] = (counts[entry.artist] ?: 0) + 1
                }
            }
        return result
    }

    @Synchronized
    override fun close() {
        ranker.close()
        tower.close()
        options.close()
    }

    companion object {
        internal fun normal(text: String) =
            Regex("[^\\p{L}\\p{N}]+")
                .replace(
                    Normalizer.normalize(text, Normalizer.Form.NFKC)
                        .lowercase(Locale.ROOT)
                        .replace("ё", "е")
                        .replace("ß", "ss")
                        .replace("ς", "σ"),
                    " ",
                )
                .trim()

        internal fun bucket(text: String): Int {
            val bytes = text.toByteArray(Charsets.UTF_8)
            val digest = Blake2bDigest(64)
            digest.update(bytes, 0, bytes.size)
            val output = ByteArray(8)
            digest.doFinal(output, 0)
            return output[0].toInt() and 127
        }

        private fun similarity(a: String, b: String): Double {
            if (a == b) return 1.0
            if (a.isEmpty() || b.isEmpty()) return 0.0
            fun matches(a0: Int, a1: Int, b0: Int, b1: Int): Int {
                var best = 0
                var ai = a0
                var bi = b0
                var prev = IntArray(b1 - b0 + 1)
                for (i in a0 until a1) {
                    val next = IntArray(b1 - b0 + 1)
                    for (j in b0 until b1) if (a[i] == b[j]) {
                        val n = prev[j - b0] + 1
                        next[j - b0 + 1] = n
                        if (n > best) {
                            best = n
                            ai = i - n + 1
                            bi = j - n + 1
                        }
                    }
                    prev = next
                }
                return if (best == 0) 0
                else best + matches(a0, ai, b0, bi) + matches(ai + best, a1, bi + best, b1)
            }
            return 2.0 * matches(0, a.length, 0, b.length) / (a.length + b.length)
        }
    }
}
