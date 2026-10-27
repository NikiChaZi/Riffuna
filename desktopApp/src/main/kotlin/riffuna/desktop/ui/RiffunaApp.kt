@file:OptIn(androidx.compose.animation.ExperimentalSharedTransitionApi::class,androidx.compose.ui.ExperimentalComposeUiApi::class)
package riffuna.desktop.ui

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.focus.*
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.key.*
import androidx.compose.ui.unit.*
import riffuna.core.*

@Composable fun RiffunaApp(controller:RiffunaController,onOpen:(Track)->Unit,onImport:()->Unit) {
    val state by controller.state.collectAsState()
    var query by remember{mutableStateOf(state.query)}
    LaunchedEffect(state.query){query=state.query}
    var typing by remember{mutableStateOf(false)}
    var queueFocus by remember{mutableStateOf(false)}
    val globalFocus=remember{FocusRequester()};val filterFocus=remember{FocusRequester()}
    val listStates=remember{mutableMapOf<String,LazyListState>()}
    val listState=listStates.getOrPut(state.view+":"+state.playlistId){LazyListState()}
    var settings by remember{mutableStateOf(false)};var help by remember{mutableStateOf(false)}
    var editor by remember{mutableStateOf(false)};var editorOriginal by remember{mutableStateOf<PlaylistSummary?>(null)};var editorTracks by remember{mutableStateOf<List<Track>>(emptyList())}
    var chooser by remember{mutableStateOf<List<Track>?>(null)}
    fun create(tracks:List<Track> = emptyList()){editorOriginal=null;editorTracks=tracks;editor=true}
    fun edit(playlist:PlaylistSummary){editorOriginal=playlist;editorTracks=emptyList();editor=true}
    val showPlaylist:(List<Track>)->Unit={tracks->if(tracks.isNotEmpty())chooser=tracks}
    RiffunaTheme(state.reducedMotion) {
        Surface(Modifier.fillMaxSize(),color=RiffunaColors.Background) {
            Box(Modifier.fillMaxSize().onPreviewKeyEvent {event->
                if(event.type!=KeyEventType.KeyDown)return@onPreviewKeyEvent false
                if(event.isCtrlPressed&&event.key==Key.F){if(event.isShiftPressed){runCatching{filterFocus.requestFocus()}}else globalFocus.requestFocus();return@onPreviewKeyEvent true}
                if(typing)return@onPreviewKeyEvent false
                when {
                    event.key==Key.Spacebar->{controller.toggle();true}
                    event.isCtrlPressed&&event.key==Key.DirectionRight->{controller.next();true}
                    event.isCtrlPressed&&event.key==Key.DirectionLeft->{controller.previous();true}
                    event.isCtrlPressed&&event.key==Key.Q->{controller.toggleQueue();true}
                    event.isCtrlPressed&&event.key==Key.A->{if(!queueFocus){controller.selectAll();true}else false}
                    event.isCtrlPressed&&event.isShiftPressed&&event.key==Key.S->{controller.toggleShuffle();true}
                    event.isCtrlPressed&&event.isShiftPressed&&event.key==Key.R->{controller.cycleRepeat();true}
                    event.isAltPressed&&event.key==Key.DirectionLeft->{controller.navigateBack();true}
                    event.isAltPressed&&event.key==Key.DirectionRight->{controller.navigateForward();true}
                    event.isAltPressed&&!queueFocus&&state.view=="playlist"&&state.selectedIds.isNotEmpty()&&event.key in setOf(Key.DirectionUp,Key.DirectionDown)->{val id=state.selectedIds.singleOrNull();if(id!=null&&state.view=="playlist"&&state.localFilter.isBlank()&&state.localOrder=="custom"){val ids=state.visibleTracks.map{it.id}.toMutableList();val from=ids.indexOf(id);val to=from+if(event.key==Key.DirectionUp)-1 else 1;if(from>=0&&to in ids.indices){ids.add(to,ids.removeAt(from));controller.reorderPlaylist(ids)}};true}
                    event.key==Key.Delete->{if(!queueFocus&&state.selectedIds.isNotEmpty()){controller.removeSelected();true}else false}
                    event.key==Key.F1->{help=true;true}
                    event.key==Key.F2&&state.current!=null->{controller.openNowPlaying(true);controller.setLyricsFocus(!state.lyricsFocus);true}
                    event.key==Key.Escape->{if(state.expanded)controller.openNowPlaying(false)else controller.clearSelection();true}
                    else->false
                }
            }) {
                SharedTransitionLayout {
                    AnimatedContent(state.expanded,transitionSpec={fadeIn(tween(if(state.reducedMotion)0 else 230)) togetherWith fadeOut(tween(if(state.reducedMotion)0 else 160))},label="expanded player") {expanded->
                        val cover=Modifier.sharedElement(rememberSharedContentState("current-cover-${state.current?.id}"),this@AnimatedContent,boundsTransform={_,_->tween(if(state.reducedMotion)0 else 420,easing=FastOutSlowInEasing)})
                        if(expanded)ExpandedPlayer(controller,state,cover,onImport,showPlaylist)
                        else Column(Modifier.fillMaxSize()) {
                            Row(Modifier.weight(1f)) {
                                Sidebar(controller,state,{create()},{controller.refreshAudioDevices();settings=true},{help=true})
                                Column(Modifier.weight(1f).fillMaxHeight()) {
                                    Row(Modifier.fillMaxWidth().padding(horizontal=24.dp,vertical=18.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                        ActionIcon(Icons.Outlined.ArrowBack,"Назад · Alt + ←",controller::navigateBack,enabled=state.canGoBack,size=30.dp)
                                        ActionIcon(Icons.Outlined.ArrowForward,"Вперёд · Alt + →",controller::navigateForward,enabled=state.canGoForward,size=30.dp)
                                        SearchField(query,{query=it},"Трек, исполнитель или ссылка",Modifier.weight(1f),globalFocus,{typing=it},{controller.search(query)})
                                        Button(onClick={controller.search(query)},shape=RoundedCornerShape(12.dp),contentPadding=PaddingValues(horizontal=18.dp,vertical=11.dp)){Text("Найти")}
                                    }
                                    val alpha=remember{Animatable(1f)}
                                    LaunchedEffect(state.view,state.playlistId,state.reducedMotion){if(!state.reducedMotion){alpha.snapTo(0f);alpha.animateTo(1f,tween(180))}else alpha.snapTo(1f)}
                                    Box(Modifier.weight(1f).fillMaxWidth().padding(horizontal=28.dp).graphicsLayer{this.alpha=alpha.value}) {
                                        when(state.view){
                                            "home"->HomeScreen(controller,state,showPlaylist,{controller.showView("search");globalFocus.requestFocus()},Modifier.fillMaxSize())
                                            "playlists"->PlaylistsScreen(controller,state,{create()},::edit)
                                            "resonance"->ResonanceScreen(controller,state)
                                            else->TracksScreen(controller,state,listState,showPlaylist,{state.playlists.firstOrNull{it.id==state.playlistId}?.let(::edit)},onOpen,filterFocus,{typing=it})
                                        }
                                    }
                                }
                                AnimatedVisibility(state.queueVisible,enter=expandHorizontally(tween(if(state.reducedMotion)0 else 220))+fadeIn(tween(if(state.reducedMotion)0 else 180)),exit=shrinkHorizontally(tween(if(state.reducedMotion)0 else 180))+fadeOut(tween(if(state.reducedMotion)0 else 150))) {
                                    QueuePanel(controller,state,showPlaylist,Modifier.width(286.dp).fillMaxHeight(),onFocus={queueFocus=it})
                                }
                            }
                            PlayerBar(controller,state,cover)
                        }
                    }
                }
                AnimatedVisibility(state.toast.isNotBlank(),Modifier.align(Alignment.BottomCenter).padding(bottom=120.dp),enter=fadeIn(tween(if(state.reducedMotion)0 else 180))+slideInVertically(tween(if(state.reducedMotion)0 else 180)){it/3},exit=fadeOut(tween(if(state.reducedMotion)0 else 120))) {
                    Surface(color=RiffunaColors.Raised,shape=RoundedCornerShape(12.dp),border=BorderStroke(1.dp,RiffunaColors.Border),shadowElevation=8.dp){Text(state.toast,Modifier.padding(horizontal=18.dp,vertical=12.dp),style=MaterialTheme.typography.bodyMedium)}
                }
            }
        }
        if(editor)PlaylistEditor(editorOriginal,{editor=false},{name,description->val original=editorOriginal;if(original==null){val id=controller.createPlaylistFrom(name,editorTracks);if(description.isNotBlank())controller.editPlaylist(id,name,description)}else controller.editPlaylist(original.id,name,description);editor=false},editorOriginal?.let{playlist->{controller.deletePlaylist(playlist.id);editor=false}})
        chooser?.let{tracks->AddPlaylistDialog(state.playlists,tracks,{chooser=null},{id->controller.addToPlaylist(id,tracks);chooser=null},{chooser=null;create(tracks)})}
        if(settings)SettingsDialog(controller,state){settings=false}
        if(help)KeyboardDialog{help=false}
        if(state.versionReference!=null)VersionsDialog(controller,state)
    }
}
