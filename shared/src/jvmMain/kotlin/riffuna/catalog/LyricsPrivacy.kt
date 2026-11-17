package riffuna.catalog

import riffuna.core.Track

private val videoId = Regex("[A-Za-z0-9_-]{11}")
private val localTrackId = Regex("local-[A-Za-z0-9_-]{1,128}")
private val privatePath =
    Regex(
        """[a-z]:[\\/]|\\\\|\b(?:file|content):/{1,3}|(?:^|[\s(\[{="'\x60])/(?:[^/\s]+/)+""",
        RegexOption.IGNORE_CASE,
    )

fun Track.validLyricsFileId(): Boolean = videoId.matches(id) || localTrackId.matches(id)

fun Track.mayQueryOnlineLyrics(): Boolean =
    videoId.matches(id) &&
        !privatePath.containsMatchIn(title) &&
        !privatePath.containsMatchIn(artist)
