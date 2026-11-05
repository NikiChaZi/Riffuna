package riffuna.core

import kotlin.test.*

class ArtworkRequestsTest {
    @Test
    fun oldAlbumUrlsAreUpgradedAtPhysicalPixelSize() {
        val old = "https://yt3.googleusercontent.com/album=w120-h120-l90-rj"
        assertEquals(
            "https://yt3.googleusercontent.com/album=w1024-h1024-l90-rj",
            ArtworkRequests.candidates(old, 780).first(),
        )
        assertEquals(old, ArtworkRequests.candidates(old, 780).last())
        assertEquals(
            "https://lh3.ggpht.com/album=w512-h512-c",
            ArtworkRequests.candidates("https://lh3.ggpht.com/album=s120-c", 380).first(),
        )
    }

    @Test
    fun videoCoversRemoveLowResolutionQueryAndRetainFallbacks() {
        val old = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg?sqp=small&rs=signature"
        val urls = ArtworkRequests.candidates(old, 800)
        assertEquals("https://i.ytimg.com/vi/aaaaaaaaaaa/maxresdefault.jpg", urls.first())
        assertTrue(urls.any { it.endsWith("/sddefault.jpg") })
        assertTrue(urls.any { it.endsWith("/hqdefault.jpg") })
        assertEquals(old, urls.last())
        assertTrue(ArtworkRequests.isPlaceholder(urls.first(), 120, 90))
        assertFalse(ArtworkRequests.isPlaceholder(urls.first(), 1280, 720))
        assertFalse(ArtworkRequests.isPlaceholder(old, 120, 90))
    }

    @Test
    fun unrelatedOrBlankUrlsAreNotRewritten() {
        for (url in
            listOf(
                "https://example.org/w120-h120.jpg",
                "https://notgoogleusercontent.com/a=w120-h120",
                "file:///local.jpg",
            )) assertEquals(listOf(url), ArtworkRequests.candidates(url, 720))
        assertTrue(ArtworkRequests.candidates("", 720).isEmpty())
    }
}
