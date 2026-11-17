package riffuna.android

internal fun sourceFailureLog(error: Throwable): String =
    "HTTPS failure=${error.javaClass.simpleName}"

internal fun audioFailureLog(code: Int, cause: Throwable?): String =
    "code=$code cause=${cause?.javaClass?.simpleName.orEmpty()}"

internal fun foregroundFailureLog(error: IllegalStateException): String =
    "Preparing foreground unavailable: ${error.javaClass.simpleName}"
