@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class,androidx.compose.ui.ExperimentalComposeUiApi::class)
package riffuna.desktop.ui

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.interaction.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.*
import androidx.compose.ui.input.key.*
import androidx.compose.ui.focus.*
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.*
import riffuna.core.*
import sh.calvin.reorderable.*

@Composable fun PlayingMark(playing:Boolean,modifier:Modifier=Modifier) {
    val motion=playing&&!LocalReducedMotion.current
    val amount=if(motion){val phase=rememberInfiniteTransition(label="playing mark");val value by phase.animateFloat(0f,1f,infiniteRepeatable(tween(900,easing=LinearEasing)),label="bar phase");value}else 0f
    Canvas(modifier.size(18.dp)){for(index in 0..2){val wave=if(motion)(.35+.65*kotlin.math.abs(kotlin.math.sin(amount*6.283+index*1.7))).toFloat()else .55f
        val width=3.dp.toPx();val height=size.height*wave;drawRoundRect(RiffunaColors.Coral,androidx.compose.ui.geometry.Offset(index*6.dp.toPx(),(size.height-height)/2),androidx.compose.ui.geometry.Size(width,height),androidx.compose.ui.geometry.CornerRadius(width/2))}}
}

@Composable fun TrackRow(track:Track,index:Int,current:Boolean,playing:Boolean,liked:Boolean,selected:Boolean,onPlay:()->Unit,onSelect:(Boolean,Boolean)->Unit,onLike:()->Unit,onQueue:()->Unit,onNext:()->Unit,onPlaylist:()->Unit,onVersions:()->Unit,onArtist:()->Unit,onOpen:()->Unit,onRemove:(()->Unit)?=null,dragModifier:Modifier?=null) {
    var menu by remember{mutableStateOf(false)};var control by remember{mutableStateOf(false)};var shift by remember{mutableStateOf(false)}
    val interaction=remember{MutableInteractionSource()};val hover by interaction.collectIsHoveredAsState()
    val background by animateColorAsState(when{selected->RiffunaColors.Selected;current->Color(0xFF282A28);hover->RiffunaColors.Raised;else->Color.Transparent},tween(if(LocalReducedMotion.current)0 else 130),label="track background")
    Row(Modifier.fillMaxWidth().height(70.dp).clip(RoundedCornerShape(10.dp)).background(background).hoverable(interaction)
        .onPointerEvent(PointerEventType.Press){event->control=event.keyboardModifiers.isCtrlPressed;shift=event.keyboardModifiers.isShiftPressed;if(event.buttons.isSecondaryPressed){if(!selected)onSelect(false,false);menu=true}}
        .combinedClickable(onClick={onSelect(control,shift)},onDoubleClick=onPlay).padding(horizontal=10.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)) {
        Box(Modifier.width(22.dp),contentAlignment=Alignment.Center){
            if(hover)Icon(Icons.Filled.PlayArrow,"Слушать",Modifier.size(22.dp).clickable(onClick=onPlay),tint=RiffunaColors.Text)
            else if(current)PlayingMark(playing)else Text((index+1).toString(),style=MaterialTheme.typography.labelMedium,color=RiffunaColors.Muted)
        }
        Artwork(track.thumbnail,Modifier.size(46.dp).clickable(onClick=onPlay),track.title,7.dp)
        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(4.dp)) {
            Text(track.title,maxLines=1,overflow=TextOverflow.Ellipsis,color=if(current)RiffunaColors.Coral else RiffunaColors.Text,style=MaterialTheme.typography.bodyMedium,fontWeight=FontWeight.Medium)
            Text(track.artist+(track.viewCount?.let{" · "+java.text.NumberFormat.getIntegerInstance(java.util.Locale.forLanguageTag("ru")).format(it)+" просм."}?:""),maxLines=1,overflow=TextOverflow.Ellipsis,color=RiffunaColors.Secondary,style=MaterialTheme.typography.bodySmall)
        }
        if(track.version.isNotBlank())SmallTag(track.version)
        Text(timeLabel(track.duration*1000L),style=MaterialTheme.typography.labelMedium,color=RiffunaColors.Secondary,modifier=Modifier.width(38.dp))
        ActionIcon(if(liked)Icons.Filled.Favorite else Icons.Outlined.FavoriteBorder,if(liked)"Убрать лайк" else "Мне нравится",onLike,active=liked,size=30.dp)
        if(dragModifier!=null)Icon(Icons.Outlined.DragIndicator,"Изменить порядок",dragModifier.size(20.dp),tint=RiffunaColors.Muted)
        Box{
            ActionIcon(Icons.Outlined.MoreHoriz,"Действия с треком",{menu=true},size=30.dp)
            DropdownMenu(menu,{menu=false}) {
                DropdownMenuItem({Text("Слушать")},{onPlay();menu=false},leadingIcon={Icon(Icons.Filled.PlayArrow,null)})
                DropdownMenuItem({Text("Слушать следующим")},{onNext();menu=false},leadingIcon={Icon(Icons.Outlined.QueuePlayNext,null)})
                DropdownMenuItem({Text("Добавить в очередь")},{onQueue();menu=false},leadingIcon={Icon(Icons.Outlined.PlaylistAdd,null)})
                DropdownMenuItem({Text("Добавить в плейлист…")},{onPlaylist();menu=false},leadingIcon={Icon(Icons.Outlined.LibraryMusic,null)})
                HorizontalDivider()
                DropdownMenuItem({Text("Другие записи…")},{onVersions();menu=false})
                DropdownMenuItem({Text("Найти исполнителя")},{onArtist();menu=false})
                DropdownMenuItem({Text("Открыть на YouTube")},{onOpen();menu=false})
                if(onRemove!=null){HorizontalDivider();DropdownMenuItem({Text("Убрать из подборки")},{onRemove();menu=false})}
            }
        }
    }
}

@Composable fun QueuePanel(controller:RiffunaController,state:AppState,onPlaylist:(List<Track>)->Unit,modifier:Modifier=Modifier,onFocus:(Boolean)->Unit={}) {
    val listState=rememberLazyListState()
    val reorder=rememberReorderableLazyListState(listState){from,to->val ids=state.queue.map{it.id}.toMutableList();val source=ids.indexOf(from.key);val destination=ids.indexOf(to.key);if(source>=0&&destination>=0){ids.add(destination,ids.removeAt(source));controller.reorderQueue(ids)}}
    var menu by remember{mutableStateOf(false)};var selected by remember{mutableStateOf<Set<String>>(emptySet())};var anchor by remember{mutableStateOf<String?>(null)};val queueFocus=remember{FocusRequester()}
    Column(modifier.background(RiffunaColors.Surface).focusRequester(queueFocus).onFocusChanged{onFocus(it.hasFocus)}.onPreviewKeyEvent{event->
        if(event.type!=KeyEventType.KeyDown)return@onPreviewKeyEvent false
        when {
            event.isCtrlPressed&&event.key==Key.A->{selected=state.queue.map{it.id}.toSet();true}
            event.key==Key.Delete->{selected.forEach(controller::removeFromQueue);selected=emptySet();true}
            event.isAltPressed&&event.key in setOf(Key.DirectionUp,Key.DirectionDown)->{selected.singleOrNull()?.let{controller.moveInQueue(it,if(event.key==Key.DirectionUp)-1 else 1)};true}
            event.key==Key.Enter->{selected.singleOrNull()?.let(controller::playQueueTrack);true}
            else->false
        }
    }.focusable().padding(horizontal=16.dp,vertical=14.dp)) {
        Row(verticalAlignment=Alignment.CenterVertically){Text("Очередь",style=MaterialTheme.typography.titleMedium,fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f));ActionIcon(Icons.Outlined.Close,"Скрыть очередь",controller::toggleQueue,size=30.dp)}
        Row(Modifier.padding(top=4.dp,bottom=10.dp),verticalAlignment=Alignment.CenterVertically) {
            Text(trackCount(state.queue.size),style=MaterialTheme.typography.bodySmall,color=RiffunaColors.Secondary,modifier=Modifier.weight(1f))
            ActionIcon(Icons.Filled.PlayArrow,"Слушать очередь с начала",controller::playQueue,enabled=state.queue.isNotEmpty(),size=30.dp)
            ActionIcon(Icons.Outlined.Shuffle,"Перемешать очередь",controller::toggleShuffle,active=state.shuffle,enabled=state.queue.isNotEmpty(),size=30.dp)
            Box{ActionIcon(Icons.Outlined.MoreHoriz,"Действия с очередью",{menu=true},size=30.dp);DropdownMenu(menu,{menu=false}) {
                DropdownMenuItem({Text("Сохранить в плейлист…")},{onPlaylist(state.queue);menu=false},enabled=state.queue.isNotEmpty())
                DropdownMenuItem({Text("Убрать выбранные")},{selected.forEach(controller::removeFromQueue);selected=emptySet();menu=false},enabled=selected.isNotEmpty())
                DropdownMenuItem({Text("Очистить очередь")},{controller.clearQueue();menu=false},enabled=state.queue.isNotEmpty())
            }}
        }
        if(state.queue.isEmpty())Column(Modifier.weight(1f).fillMaxWidth(),verticalArrangement=Arrangement.Center,horizontalAlignment=Alignment.CenterHorizontally) {
            Icon(Icons.Outlined.QueueMusic,null,Modifier.size(38.dp),tint=RiffunaColors.Muted);Spacer(Modifier.height(14.dp));Text("Очередь пока пуста",style=MaterialTheme.typography.bodyMedium);Text("Добавляй музыку через +",Modifier.padding(top=6.dp),style=MaterialTheme.typography.bodySmall,color=RiffunaColors.Secondary)
        }else LazyColumn(Modifier.weight(1f),state=listState,verticalArrangement=Arrangement.spacedBy(4.dp)) {
            items(state.queue,key={it.id}){track->ReorderableItem(reorder,track.id){dragging->
                var rowMenu by remember{mutableStateOf(false)};var ctrl by remember{mutableStateOf(false)};var shift by remember{mutableStateOf(false)}
                val current=state.queue.getOrNull(state.queueIndex)?.id==track.id||(state.queueIndex==-1&&state.current?.id==track.id)
                Row(Modifier.fillMaxWidth().height(64.dp).clip(RoundedCornerShape(9.dp)).background(when{dragging->RiffunaColors.Hover;track.id in selected->RiffunaColors.Selected;current->Color(0xFF2B2E2B);else->Color.Transparent})
                    .onPointerEvent(PointerEventType.Press){event->ctrl=event.keyboardModifiers.isCtrlPressed;shift=event.keyboardModifiers.isShiftPressed;queueFocus.requestFocus();if(event.buttons.isSecondaryPressed){if(track.id !in selected)selected=setOf(track.id);rowMenu=true}}
                    .combinedClickable(onClick={val ids=state.queue.map{it.id};val a=ids.indexOf(anchor);val b=ids.indexOf(track.id);val range=if(shift&&a>=0)ids.subList(minOf(a,b),maxOf(a,b)+1).toSet()else setOf(track.id);selected=when{shift&&ctrl->selected+range;shift->range;ctrl->if(track.id in selected)selected-track.id else selected+track.id;else->range};if(!shift)anchor=track.id},onDoubleClick={controller.playQueueTrack(track.id)}).padding(horizontal=7.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(10.dp)) {
                    Box(Modifier.size(42.dp).clickable{controller.playQueueTrack(track.id)}) {Artwork(track.thumbnail,Modifier.fillMaxSize(),track.title,6.dp);if(current)Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha=.45f)),contentAlignment=Alignment.Center){PlayingMark(state.playing)}}
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(4.dp)){Text(track.title,maxLines=1,overflow=TextOverflow.Ellipsis,color=if(current)RiffunaColors.Coral else RiffunaColors.Text,style=MaterialTheme.typography.bodySmall,fontWeight=FontWeight.Medium);Text(track.artist,maxLines=1,overflow=TextOverflow.Ellipsis,color=RiffunaColors.Secondary,style=MaterialTheme.typography.labelSmall)}
                    Icon(Icons.Outlined.DragIndicator,"Изменить порядок",Modifier.draggableHandle().size(16.dp),tint=RiffunaColors.Muted)
                    Box{ActionIcon(Icons.Outlined.MoreVert,"Действия",{rowMenu=true},size=24.dp);DropdownMenu(rowMenu,{rowMenu=false}) {
                        DropdownMenuItem({Text("Слушать")},{controller.playQueueTrack(track.id);rowMenu=false})
                        DropdownMenuItem({Text("Слушать следующим")},{controller.playNext(track);rowMenu=false})
                        DropdownMenuItem({Text("В плейлист…")},{onPlaylist(listOf(track));rowMenu=false})
                        DropdownMenuItem({Text("Другие записи…")},{controller.findVersions(track);rowMenu=false})
                        HorizontalDivider();DropdownMenuItem({Text(if(track.id in selected&&selected.size>1)"Убрать выбранные"else "Убрать из очереди")},{if(track.id in selected&&selected.size>1){selected.forEach(controller::removeFromQueue);selected=emptySet()}else controller.removeFromQueue(track.id);rowMenu=false})
                    }}
                }
            }}
        }
    }
}
