package riffuna.desktop

import kotlin.test.*
import kotlinx.serialization.json.*
import java.nio.file.*
import riffuna.core.Track

class MusicModelTest {
    @Test fun kotlinInferenceMatchesPythonTowerRankerAndRecommendationOrder() {
        val directory=Path.of(System.getProperty("user.dir")).parent.resolve("build/kotlin-music-model")
        org.junit.Assume.assumeTrue(Files.isRegularFile(directory.resolve("manifest.json")))
        val fixture=Json.parseToJsonElement(javaClass.getResource("/music-parity.json")!!.readText()).jsonObject
        fun array(key:String)=fixture[key]!!.jsonArray.map{it.jsonPrimitive.float}.toFloatArray()
        fun tracks(key:String)=fixture[key]!!.jsonArray.map{row->val t=row.jsonObject;Track(t["id"]!!.jsonPrimitive.content,t["title"]!!.jsonPrimitive.content,t["artist"]!!.jsonPrimitive.content)}
        MusicModel(directory).use{model->
            val actual=model.query(array("profile"));val expected=array("query")
            assertEquals(expected.size,actual.size)
            expected.indices.forEach{assertTrue(kotlin.math.abs(expected[it]-actual[it])<.00001f,"Tower mismatch at $it")}
            val scores=model.score(array("rank_features"),20);val wanted=array("rank_scores")
            scores.indices.forEach{assertTrue(kotlin.math.abs(wanted[it]-scores[it])<.00001f,"Ranker mismatch at $it")}
            assertEquals(fixture["recommendations"]!!.jsonArray.map{it.jsonPrimitive.content},model.recommend(tracks("seeds"),tracks("excluded")).map{it.catalogId})
            assertTrue(model.recommend(listOf(Track("unknown","Unknown song","Missing Artist 12345")),emptyList()).isEmpty())
        }
        fixture["buckets"]!!.jsonObject.forEach{(word,value)->assertEquals(value.jsonPrimitive.int,MusicModel.bucket(word))}
    }
}
