@file:OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)

package riffuna.desktop

import androidx.compose.foundation.layout.width
import androidx.compose.ui.ImageComposeScene
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.onPointerEvent
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import kotlin.test.*
import kotlinx.coroutines.*
import kotlinx.coroutines.swing.Swing
import riffuna.desktop.ui.ProgressSlider
import riffuna.desktop.ui.RiffunaTheme

/** Dispatches real Compose pointer events offscreen, without controlling desktop windows. */
class ProgressSliderTest {
    @Test
    fun hoveringUntilTheTimeLabelAppearsDoesNotBlockClicks() = runBlocking {
        val commits = mutableListOf<Float>()
        withSlider(commitOnPress = true, commit = commits::add) { scene ->
            scene.pointer(PointerEventType.Enter, 160f)
            scene.pointer(PointerEventType.Move, 160f)
            delay(350)
            scene.pointer(PointerEventType.Move, 160f)
            scene.pointer(PointerEventType.Press, 160f)
            scene.pointer(PointerEventType.Release, 160f)
            assertEquals(.8f, commits.single(), .01f)
        }
    }

    @Test
    fun playbackSliderSeeksOnPressAnywhereWithoutDraggingOrWaitingForRelease() = runBlocking {
        val commits = mutableListOf<Float>()
        withSlider(commitOnPress = true, commit = commits::add) { scene ->
            scene.pointer(PointerEventType.Press, 160f)
            assertEquals(.8f, commits.single(), .01f)
            scene.pointer(PointerEventType.Release, 160f)
            assertEquals(1, commits.size, "Release must not repeat a click seek")
            scene.pointer(PointerEventType.Press, 40f)
            assertEquals(.2f, commits.last(), .01f)
            scene.pointer(PointerEventType.Release, 40f)
        }
        assertEquals(2, commits.size)
    }

    @Test
    fun consumedMouseReleaseStillCommitsTheClick() = runBlocking {
        val commits = mutableListOf<Float>()
        withSlider(consumeRelease = true, commit = commits::add) { scene ->
            scene.pointer(PointerEventType.Press, 160f)
            scene.pointer(PointerEventType.Release, 160f)
        }
        assertEquals(1, commits.size)
        assertEquals(.8f, commits.single(), .01f)
    }

    @Test
    fun separateClicksSeekForwardAndBackwardWithoutDragging() = runBlocking {
        val commits = mutableListOf<Float>()
        withSlider(commit = commits::add) { scene ->
            scene.pointer(PointerEventType.Press, 160f)
            assertTrue(commits.isEmpty(), "Do not seek before release")
            scene.pointer(PointerEventType.Release, 160f)
            scene.pointer(PointerEventType.Press, 40f)
            scene.pointer(PointerEventType.Release, 40f)
        }
        assertEquals(2, commits.size)
        assertEquals(.8f, commits[0], .01f)
        assertEquals(.2f, commits[1], .01f)
    }

    @Test
    fun slightMouseMovementStillCommitsOnceAndDragCommitsOnlyAtRelease() = runBlocking {
        val commits = mutableListOf<Float>()
        withSlider(commit = commits::add) { scene ->
            scene.pointer(PointerEventType.Press, 100f)
            scene.pointer(PointerEventType.Move, 102f)
            scene.pointer(PointerEventType.Release, 102f)
            assertEquals(1, commits.size)
            scene.pointer(PointerEventType.Press, 40f)
            scene.pointer(PointerEventType.Move, 170f)
            assertEquals(1, commits.size)
            scene.pointer(PointerEventType.Release, 170f)
        }
        assertEquals(2, commits.size)
        assertEquals(.51f, commits[0], .01f)
        assertEquals(.85f, commits[1], .01f)
    }

    @Test
    fun disabledSliderDoesNotSeek() = runBlocking {
        val commits = mutableListOf<Float>()
        withSlider(enabled = false, commit = commits::add) { scene ->
            scene.pointer(PointerEventType.Press, 150f)
            scene.pointer(PointerEventType.Release, 150f)
        }
        assertTrue(commits.isEmpty())
    }

    private suspend fun withSlider(
        enabled: Boolean = true,
        consumeRelease: Boolean = false,
        commitOnPress: Boolean = false,
        commit: (Float) -> Unit,
        block: suspend (ImageComposeScene) -> Unit,
    ) {
        val scene =
            withContext(Dispatchers.Swing) {
                ImageComposeScene(200, 24, Density(1f), coroutineContext = Dispatchers.Swing) {
                    RiffunaTheme(true) {
                        ProgressSlider(
                            0f,
                            {},
                            Modifier.width(200.dp).onPointerEvent(
                                PointerEventType.Release,
                                PointerEventPass.Initial,
                            ) { event ->
                                if (consumeRelease) event.changes.forEach { it.consume() }
                            },
                            onCommit = commit,
                            commitOnPress = commitOnPress,
                            enabled = enabled,
                        )
                    }
                }
            }
        try {
            repeat(4) {
                withContext(Dispatchers.Swing) { scene.render(System.nanoTime()).close() }
                delay(20)
            }
            block(scene)
        } finally {
            withContext(Dispatchers.Swing) { scene.close() }
        }
    }

    private suspend fun ImageComposeScene.pointer(type: PointerEventType, x: Float) {
        withContext(Dispatchers.Swing) {
            sendPointerEvent(type, Offset(x, 12f))
            render(System.nanoTime()).close()
        }
        delay(20)
    }
}
