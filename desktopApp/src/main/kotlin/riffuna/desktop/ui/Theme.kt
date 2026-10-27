package riffuna.desktop.ui

import androidx.compose.animation.core.*
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.*
import androidx.compose.foundation.interaction.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*

object RiffunaColors {
    val Background=Color(0xFF101214)
    val Surface=Color(0xFF181B1F)
    val Raised=Color(0xFF20252A)
    val Hover=Color(0xFF292F35)
    val Border=Color(0xFF30363C)
    val Text=Color(0xFFF4F1E8)
    val Secondary=Color(0xFFA3A8AD)
    val Muted=Color(0xFF737D86)
    val Coral=Color(0xFFFF875F)
    val CoralBright=Color(0xFFFFA080)
    val Selected=Color(0xFF38312C)
}
val LocalReducedMotion=staticCompositionLocalOf{false}

@Composable fun RiffunaTheme(reducedMotion:Boolean,content:@Composable ()->Unit) {
    val colors=RiffunaColors
    MaterialTheme(colorScheme=darkColorScheme(
        primary=colors.Coral,onPrimary=colors.Background,primaryContainer=Color(0xFF493329),onPrimaryContainer=Color(0xFFFFCAB8),
        secondary=Color(0xFFCAB6A4),onSecondary=colors.Background,secondaryContainer=Color(0xFF34312D),onSecondaryContainer=colors.Text,
        tertiary=Color(0xFFB9C4B2),onTertiary=colors.Background,tertiaryContainer=Color(0xFF303B2B),onTertiaryContainer=Color(0xFFDDE6D6),
        background=colors.Background,onBackground=colors.Text,surface=colors.Surface,onSurface=colors.Text,
        surfaceVariant=colors.Raised,onSurfaceVariant=colors.Secondary,outline=colors.Border,outlineVariant=colors.Border,
        surfaceTint=Color.Transparent,surfaceDim=colors.Background,surfaceBright=colors.Hover,
        surfaceContainerLowest=Color(0xFF0C0E10),surfaceContainerLow=colors.Surface,surfaceContainer=colors.Raised,surfaceContainerHigh=Color(0xFF252B30),surfaceContainerHighest=colors.Hover,
        inverseSurface=colors.Text,inverseOnSurface=colors.Background,inversePrimary=Color(0xFF91432B),scrim=Color.Black,
        error=Color(0xFFFF9A86),onError=Color(0xFF3B1009),errorContainer=Color(0xFF54251C),onErrorContainer=Color(0xFFFFD6CA)
    ),shapes=Shapes(extraSmall=RoundedCornerShape(6.dp),small=RoundedCornerShape(10.dp),medium=RoundedCornerShape(14.dp),large=RoundedCornerShape(18.dp),extraLarge=RoundedCornerShape(24.dp))) {
        CompositionLocalProvider(LocalReducedMotion provides reducedMotion,LocalMinimumInteractiveComponentSize provides 0.dp){content()}
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable fun ActionIcon(icon:ImageVector,label:String,onClick:()->Unit,modifier:Modifier=Modifier,active:Boolean=false,enabled:Boolean=true,size:Dp=36.dp) {
    val source=remember{MutableInteractionSource()};val hovered by source.collectIsHoveredAsState();val pressed by source.collectIsPressedAsState()
    val duration=if(LocalReducedMotion.current)0 else 120
    val scale by animateFloatAsState(if(pressed).9f else 1f,tween(duration),label="button press")
    val background by animateColorAsState(if(active)RiffunaColors.Coral.copy(alpha=.14f)else if(hovered)RiffunaColors.Hover else Color.Transparent,tween(duration),label="button hover")
    TooltipArea(tooltip={Surface(color=RiffunaColors.Raised,shape=RoundedCornerShape(7.dp),border=BorderStroke(1.dp,RiffunaColors.Border)){Text(label,Modifier.padding(horizontal=10.dp,vertical=6.dp),style=MaterialTheme.typography.labelMedium)}},delayMillis=500) {
        IconButton(onClick=onClick,enabled=enabled,interactionSource=source,modifier=modifier.size(size).scale(scale).clip(RoundedCornerShape(9.dp)).background(background)) {
            Icon(icon,contentDescription=label,tint=if(!enabled)RiffunaColors.Muted.copy(alpha=.4f)else if(active)RiffunaColors.Coral else RiffunaColors.Secondary,modifier=Modifier.size(20.dp))
        }
    }
}

@Composable fun SectionTitle(title:String,action:String?=null,onAction:()->Unit={}) {
    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){Text(title,style=MaterialTheme.typography.titleLarge,fontWeight=FontWeight.SemiBold,modifier=Modifier.weight(1f));if(action!=null)TextButton(onClick=onAction){Text(action,color=RiffunaColors.Secondary)}}
}
@Composable fun SmallTag(text:String,coral:Boolean=false) {
    Text(text,Modifier.clip(RoundedCornerShape(5.dp)).background(if(coral)RiffunaColors.Coral.copy(alpha=.12f)else RiffunaColors.Raised).padding(horizontal=7.dp,vertical=4.dp),color=if(coral)RiffunaColors.Coral else RiffunaColors.Secondary,style=MaterialTheme.typography.labelSmall)
}
fun timeLabel(milliseconds:Long):String {val seconds=milliseconds.coerceAtLeast(0)/1000;return "${seconds/60}:${(seconds%60).toString().padStart(2,'0')}"}
fun trackCount(count:Int):String {val suffix=when{count%100 in 11..14->"треков";count%10==1->"трек";count%10 in 2..4->"трека";else->"треков"};return "$count $suffix"}
