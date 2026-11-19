package riffuna.android

internal fun sourceFailureLog(error: Throwable): String =
    "HTTPS failure=${error.javaClass.simpleName}"

internal fun audioFailureLog(code: Int, cause: Throwable?): String {
    val origin =
        cause?.stackTrace?.firstOrNull {
            it.className.startsWith("androidx.media3.") ||
                it.className in
                    setOf(
                        "riffuna.android.LoudnessProcessor",
                        "riffuna.android.RangeAudioDataSource",
                    )
        }
    val summary = "code=$code cause=${cause?.javaClass?.simpleName.orEmpty()}"
    return if (origin == null) summary
    else "$summary origin=${origin.className}.${origin.methodName}"
}

internal fun foregroundFailureLog(error: IllegalStateException): String =
    "Preparing foreground unavailable: ${error.javaClass.simpleName}"
