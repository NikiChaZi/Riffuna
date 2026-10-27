package riffuna.android

import android.app.Application
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import androidx.media3.common.*
import androidx.media3.common.util.UnstableApi
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.cache.*
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.*
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import okhttp3.OkHttpClient
import riffuna.core.*

@androidx.annotation.OptIn(UnstableApi::class)
class AndroidAudio(
    context: Context,
    http: OkHttpClient,
    cacheName: String = "audio",
    private val current: () -> Track?,
) : AudioEngine {
    @Volatile private var sourceHeaders = emptyMap<String, String>()
    private val remote = DataSource.Factory { RangeAudioDataSource(http) { sourceHeaders } }
    private val cache =
        SimpleCache(
            File(context.cacheDir, cacheName),
            LeastRecentlyUsedCacheEvictor(512L * 1024 * 1024),
            StandaloneDatabaseProvider(context),
        )
    private val data =
        CacheDataSource.Factory()
            .setCache(cache)
            .setUpstreamDataSourceFactory(DefaultDataSource.Factory(context, remote))
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
    val player =
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(data))
            .build()
            .apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(C.USAGE_MEDIA)
                        .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                        .build(),
                    true,
                )
                setHandleAudioBecomingNoisy(true)
                setWakeMode(C.WAKE_MODE_LOCAL)
            }
    private val mutable = MutableStateFlow(AudioState())
    override val state: StateFlow<AudioState> = mutable
    private val handler = Handler(Looper.getMainLooper())
    private var failure: String? = null
    private val tick =
        object : Runnable {
            override fun run() {
                publish()
                handler.postDelayed(this, 100)
            }
        }

    init {
        player.addListener(
            object : Player.Listener {
                override fun onEvents(player: Player, events: Player.Events) {
                    publish()
                }

                override fun onPlayerError(error: PlaybackException) {
                    failure = "Не удалось воспроизвести запись. Проверь подключение и VPN"
                    publish()
                }
            }
        )
        handler.post(tick)
    }

    private fun publish() {
        mutable.value =
            AudioState(
                player.currentPosition.coerceAtLeast(0),
                player.duration.takeIf { it != C.TIME_UNSET }?.coerceAtLeast(0) ?: 0,
                player.isPlaying,
                player.playbackState == Player.STATE_ENDED,
                failure,
                player.playbackState == Player.STATE_BUFFERING,
                player.isCurrentMediaItemSeekable,
            )
    }

    override suspend fun open(source: AudioSource) =
        withContext(Dispatchers.Main) {
            failure = null
            sourceHeaders = source.headers.toMap()
            val track = current()
            val metadata =
                MediaMetadata.Builder()
                    .setTitle(track?.title)
                    .setArtist(track?.artist)
                    .apply {
                        track
                            ?.thumbnail
                            ?.takeIf { it.startsWith("https://") }
                            ?.let { setArtworkUri(android.net.Uri.parse(it)) }
                    }
                    .build()
            player.setMediaItem(
                MediaItem.Builder()
                    .setUri(source.uri)
                    .setMediaId(track?.id ?: source.uri)
                    .setCustomCacheKey(
                        if (track != null)
                            track.id +
                                ":" +
                                (android.net.Uri.parse(source.uri).getQueryParameter("itag")
                                    ?: "local")
                        else source.uri
                    )
                    .setMediaMetadata(metadata)
                    .build()
            )
            player.prepare()
            player.playWhenReady = source.autoPlay
        }

    override fun toggle() {
        if (player.playWhenReady) pause() else resume()
    }

    override fun pause() {
        player.pause()
    }

    override fun resume() {
        player.play()
    }

    override fun seek(positionMs: Long) {
        player.seekTo(positionMs.coerceAtLeast(0))
    }

    override fun setVolume(volume: Float) {
        player.volume = volume.coerceIn(0f, 1f)
    }

    override fun close() {
        handler.removeCallbacks(tick)
        player.release()
        cache.release()
    }
}

class RiffunaApplication : Application() {
    private val defaultGraph: AppGraph by lazy { AppGraph(this) }
    internal var testGraph: AppGraph? = null
    val graph: AppGraph
        get() = testGraph ?: defaultGraph
}

class AppGraph(
    context: Context,
    libraryName: String = "library.sqlite3",
    cacheName: String = "audio",
) {
    val http =
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .callTimeout(25, TimeUnit.SECONDS)
            .followRedirects(false)
            .build()
    val library = AndroidLibrary(context, libraryName)
    val source = BrowserMusicSource(context, http, library)
    val audio = AndroidAudio(context, http, cacheName) { controller.state.value.current }
    lateinit var controller: LocalController
        private set

    init {
        controller = LocalController(library, source, audio)
    }
}

@androidx.annotation.OptIn(UnstableApi::class)
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null
    private lateinit var graph: AppGraph
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val preparingId = 1002
    private val preparingChannel = "riffuna_preparing"

    override fun onCreate() {
        super.onCreate()
        graph = (application as RiffunaApplication).graph
        val routing =
            object : ForwardingPlayer(graph.audio.player) {
                override fun getAvailableCommands(): Player.Commands =
                    super.getAvailableCommands()
                        .buildUpon()
                        .add(Player.COMMAND_SEEK_TO_NEXT)
                        .add(Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM)
                        .add(Player.COMMAND_SEEK_TO_PREVIOUS)
                        .add(Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM)
                        .build()

                override fun isCommandAvailable(command: Int) = availableCommands.contains(command)

                override fun seekToNext() {
                    graph.controller.next()
                }

                override fun seekToNextMediaItem() {
                    graph.controller.next()
                }

                override fun seekToPrevious() {
                    graph.controller.previous()
                }

                override fun seekToPreviousMediaItem() {
                    graph.controller.previous()
                }
            }
        session =
            MediaSession.Builder(this, routing)
                .setSessionActivity(
                    android.app.PendingIntent.getActivity(
                        this,
                        0,
                        Intent(this, MainActivity::class.java),
                        android.app.PendingIntent.FLAG_IMMUTABLE or
                            android.app.PendingIntent.FLAG_UPDATE_CURRENT,
                    )
                )
                .build()
        serviceScope.launch {
            graph.controller.state
                .map { it.playbackLoading to it.current?.title }
                .distinctUntilChanged()
                .collect {
                    session?.let { current ->
                        onUpdateNotification(current, graph.audio.player.playWhenReady)
                    }
                }
        }
    }

    override fun onUpdateNotification(session: MediaSession, startInForegroundRequired: Boolean) {
        if (graph.controller.state.value.playbackLoading) {
            val manager = getSystemService(android.app.NotificationManager::class.java)
            manager.createNotificationChannel(
                android.app.NotificationChannel(
                    preparingChannel,
                    "Подключение музыки",
                    android.app.NotificationManager.IMPORTANCE_LOW,
                )
            )
            val notification =
                android.app.Notification.Builder(this, preparingChannel)
                    .setSmallIcon(riffuna.android.R.drawable.ic_stat_music)
                    .setContentTitle(graph.controller.state.value.current?.title ?: "Riffuna")
                    .setContentText("Подключаем запись…")
                    .setContentIntent(
                        android.app.PendingIntent.getActivity(
                            this,
                            0,
                            Intent(this, MainActivity::class.java),
                            android.app.PendingIntent.FLAG_IMMUTABLE or
                                android.app.PendingIntent.FLAG_UPDATE_CURRENT,
                        )
                    )
                    .setOngoing(true)
                    .setOnlyAlertOnce(true)
                    .build()
            if (android.os.Build.VERSION.SDK_INT >= 29)
                startForeground(
                    preparingId,
                    notification,
                    android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK,
                )
            else startForeground(preparingId, notification)
        } else {
            super.onUpdateNotification(session, startInForegroundRequired)
            getSystemService(android.app.NotificationManager::class.java).cancel(preparingId)
        }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onDestroy() {
        serviceScope.cancel()
        session?.release()
        session = null
        graph.audio.pause()
        super.onDestroy()
    }
}
