package riffuna.desktop

import kotlinx.serialization.json.*
import java.net.URI
import javax.imageio.ImageIO
import java.awt.image.BufferedImage

/** Conservative observation of sampled frames, never a claim about the audio. */
object StoryboardCheck {
    fun inspect(info:JsonObject,fetch:(String,Int)->ByteArray=DesktopNetwork::bytes):String? {
        val id=info["id"]?.jsonPrimitive?.content?:return null
        val board=info["storyboards"]?.jsonArray.orEmpty().map{it.jsonObject}.filter{row->
            val width=row["thumbnail_width"]?.jsonPrimitive?.intOrNull?:0;val height=row["thumbnail_height"]?.jsonPrimitive?.intOrNull?:0
            val rows=row["rows"]?.jsonPrimitive?.intOrNull?:0;val cols=row["columns"]?.jsonPrimitive?.intOrNull?:0
            width in 100..320&&height in 1..240&&rows*cols in 1..100&&width.toLong()*height*rows*cols<=4_000_000&&(row["thumbnail_count"]?.jsonPrimitive?.intOrNull?:0)>=6
        }.maxByOrNull{it["thumbnail_width"]!!.jsonPrimitive.int}?:return null
        val width=board["thumbnail_width"]!!.jsonPrimitive.int;val height=board["thumbnail_height"]!!.jsonPrimitive.int
        val rows=board["rows"]!!.jsonPrimitive.int;val cols=board["columns"]!!.jsonPrimitive.int
        val count=board["thumbnail_count"]!!.jsonPrimitive.int;val sheets=board["storyboard_count"]!!.jsonPrimitive.int
        if(sheets !in 1..200)return null
        var reference:IntArray?=null;var observed=0
        for(index in listOf(0,sheets/2,sheets-1).distinct()) {
            val url=board["template_url"]!!.jsonPrimitive.content.replace("\$M",index.toString())
            val uri=URI(url);if(uri.scheme!="https"||!uri.host.endsWith(".ytimg.com")||!uri.path.startsWith("/sb/$id/"))return null
            val data=fetch(url,2*1024*1024)
            val image=ImageIO.createImageInputStream(data.inputStream()).use{input->
                val readers=ImageIO.getImageReaders(input);if(!readers.hasNext())return null
                val reader=readers.next();try{reader.input=input;if(reader.getWidth(0)!=width*cols||reader.getHeight(0)!=height*rows)return null;reader.read(0)}finally{reader.dispose()}
            }
            for(cell in 0 until minOf(rows*cols,count-index*rows*cols)) {
                val small=BufferedImage(32,24,BufferedImage.TYPE_INT_RGB);val g=small.createGraphics();g.drawImage(image.getSubimage(cell%cols*width,cell/cols*height,width,height),0,0,32,24,null);g.dispose()
                val pixels=IntArray(32*24*3);val gray=DoubleArray(32*24)
                for(y in 0 until 24)for(x in 0 until 32){val color=small.getRGB(x,y);val at=y*32+x;pixels[at*3]=(color ushr 16) and 255;pixels[at*3+1]=(color ushr 8) and 255;pixels[at*3+2]=color and 255;gray[at]=(pixels[at*3]+pixels[at*3+1]+pixels[at*3+2])/3.0}
                val mean=gray.average();if(gray.sumOf{(it-mean)*(it-mean)}/gray.size<64)return null
                val previous=reference
                if(previous==null)reference=pixels else {val differences=pixels.indices.map{kotlin.math.abs(pixels[it]-previous[it])};if(differences.average()>3||differences.count{it>24}.toDouble()/pixels.size>.02)return null}
                observed++
            }
        }
        return if(observed>=6)"Категория YouTube: ${info["category"]?.jsonPrimitive?.content}. На $observed выбранных кадрах начала, середины и конца — статичное непустое изображение. Между выбранными кадрами видео не проверено." else null
    }
}
