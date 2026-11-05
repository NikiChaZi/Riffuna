package riffuna.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Bundle
import androidx.media3.common.ForwardingPlayer
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.*
import com.google.common.util.concurrent.Futures
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

@androidx.annotation.OptIn(UnstableApi::class)
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null
    private lateinit var graph: AppGraph
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val preparingId = 1002
    private val preparingChannel = "riffuna_preparing"
    private var preparingInForeground = false
    private val like = SessionCommand("riffuna.TOGGLE_LIKE", Bundle.EMPTY)

    override fun onCreate() {
        super.onCreate()
        graph = (application as RiffunaApplication).graph
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider(this).apply { setSmallIcon(R.drawable.ic_stat_music) }
        )
        val routing =
            object : ForwardingPlayer(graph.audio.player) {
                override fun play() = graph.controller.resumePlayback()

                override fun pause() = graph.controller.pausePlayback()

                override fun setPlayWhenReady(playWhenReady: Boolean) {
                    if (playWhenReady) graph.controller.resumePlayback()
                    else graph.controller.pausePlayback()
                }

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
        val mediaSession =
            MediaSession.Builder(this, routing)
                .setSessionActivity(
                    PendingIntent.getActivity(
                        this,
                        0,
                        Intent(this, MainActivity::class.java)
                            .addFlags(
                                Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
                            ),
                        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                    )
                )
                .setCallback(
                    object : MediaSession.Callback {
                        override fun onConnect(
                            session: MediaSession,
                            controller: MediaSession.ControllerInfo,
                        ): MediaSession.ConnectionResult {
                            if (controller.uid != applicationInfo.uid && !controller.isTrusted)
                                return MediaSession.ConnectionResult.reject()
                            return MediaSession.ConnectionResult.AcceptedResultBuilder(session)
                                .setAvailableSessionCommands(
                                    MediaSession.ConnectionResult.DEFAULT_SESSION_COMMANDS
                                        .buildUpon()
                                        .add(like)
                                        .build()
                                )
                                .build()
                        }

                        override fun onCustomCommand(
                            session: MediaSession,
                            controller: MediaSession.ControllerInfo,
                            customCommand: SessionCommand,
                            args: Bundle,
                        ): com.google.common.util.concurrent.ListenableFuture<SessionResult> {
                            if (customCommand.customAction != like.customAction)
                                return Futures.immediateFuture(
                                    SessionResult(SessionError.ERROR_NOT_SUPPORTED)
                                )
                            val track = graph.controller.state.value.current
                            if (
                                track == null ||
                                    track.id != session.player.currentMediaItem?.mediaId
                            )
                                return Futures.immediateFuture(
                                    SessionResult(SessionError.ERROR_INVALID_STATE)
                                )
                            graph.controller.toggleLike(track)
                            return Futures.immediateFuture(
                                SessionResult(SessionResult.RESULT_SUCCESS)
                            )
                        }
                    }
                )
                .build()
        session = mediaSession
        // Register immediately so Media3 publishes controls before a system controller binds.
        addSession(mediaSession)
        serviceScope.launch {
            graph.controller.state
                .map { it.loading }
                .distinctUntilChanged()
                .collect { resolving ->
                    if (resolving) showPreparing(mediaSession)
                    else if (preparingInForeground && !playerStarting()) removePreparing()
                }
        }
        serviceScope.launch {
            graph.controller.state
                .map { state ->
                    state.current?.let { track -> state.likes.any { it.id == track.id } }
                }
                .distinctUntilChanged()
                .collect { liked ->
                    mediaSession.setMediaButtonPreferences(
                        if (liked == null) emptyList()
                        else
                            listOf(
                                CommandButton.Builder(
                                        if (liked) CommandButton.ICON_HEART_FILLED
                                        else CommandButton.ICON_HEART_UNFILLED
                                    )
                                    .setDisplayName(
                                        if (liked) "Убрать из любимого" else "В любимое"
                                    )
                                    .setSessionCommand(like)
                                    .setSlots(
                                        CommandButton.SLOT_FORWARD_SECONDARY,
                                        CommandButton.SLOT_OVERFLOW,
                                    )
                                    .build()
                            )
                    )
                }
        }
    }

    private fun playerStarting(): Boolean =
        graph.audio.player.let {
            it.playWhenReady &&
                it.playbackState in listOf(Player.STATE_BUFFERING, Player.STATE_READY)
        }

    // Only the initial source lookup needs a bootstrap notification. Media3 owns all updates
    // once the player has a stream, including buffering, reconnection and track transitions.
    private fun showPreparing(session: MediaSession) {
        if (preparingInForeground || isPlaybackOngoing() || playerStarting()) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                preparingChannel,
                "Подключение музыки",
                NotificationManager.IMPORTANCE_LOW,
            )
        )
        val notification =
            Notification.Builder(this, preparingChannel)
                .setSmallIcon(R.drawable.ic_stat_music)
                .setContentTitle(graph.controller.state.value.current?.title ?: "Riffuna")
                .setContentText("Подключаем запись…")
                .setContentIntent(session.sessionActivity)
                .setStyle(Notification.MediaStyle().setMediaSession(session.platformToken))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .build()
        try {
            if (Build.VERSION.SDK_INT >= 29)
                startForeground(
                    preparingId,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK,
                )
            else startForeground(preparingId, notification)
            preparingInForeground = true
        } catch (error: IllegalStateException) {
            android.util.Log.w(
                "RiffunaAudio",
                "Preparing foreground unavailable: " + error.javaClass.simpleName,
            )
        }
    }

    private fun removePreparing() {
        if (!preparingInForeground) return
        if (!isPlaybackOngoing()) stopForeground(STOP_FOREGROUND_REMOVE)
        getSystemService(NotificationManager::class.java).cancel(preparingId)
        preparingInForeground = false
    }

    override fun onUpdateNotification(session: MediaSession, startInForegroundRequired: Boolean) {
        if (
            preparingInForeground &&
                graph.controller.state.value.loading &&
                !startInForegroundRequired
        )
            return
        super.onUpdateNotification(session, startInForegroundRequired)
        if (isPlaybackOngoing() || !graph.controller.state.value.loading && !playerStarting())
            removePreparing()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        if (
            preparingInForeground ||
                isPlaybackOngoing() &&
                    (playerStarting() ||
                        graph.controller.state.value.loading ||
                        graph.audio.state.value.buffering)
        )
            return
        super.onTaskRemoved(rootIntent)
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onDestroy() {
        serviceScope.cancel()
        graph.controller.pausePlayback()
        session?.let {
            removeSession(it)
            it.release()
        }
        session = null
        super.onDestroy()
    }
}
