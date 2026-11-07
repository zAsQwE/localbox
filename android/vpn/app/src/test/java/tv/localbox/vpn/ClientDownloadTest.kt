package tv.localbox.vpn

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.CancellationException

class ClientDownloadTest {
    @Test fun verifiesDownloadSizeAndShaBeforeAcceptingArchive() {
        val bytes="client fixture".toByteArray()
        val plan=ClientDownload.Plan("https://github.com/example/client.zip","test",bytes.size.toLong(),ApkPatch.sha256(bytes))
        val output=ByteArrayOutputStream()
        assertEquals(bytes.size.toLong(),ClientDownload.copy(ByteArrayInputStream(bytes),output,plan))
        assertArrayEquals(bytes,output.toByteArray())
        assertThrows(IllegalArgumentException::class.java) { ClientDownload.copy(ByteArrayInputStream(bytes),ByteArrayOutputStream(),plan.copy(sha256="0".repeat(64))) }
        assertThrows(IllegalArgumentException::class.java) { ClientDownload.copy(ByteArrayInputStream(bytes.copyOf(3)),ByteArrayOutputStream(),plan) }
    }
    @Test fun cancelsWithoutWritingAndRejectsUnsafeRedirects() {
        val output=ByteArrayOutputStream()
        assertThrows(CancellationException::class.java) {
            ClientDownload.copy(ByteArrayInputStream(ByteArray(20)),output,ClientDownload.Plan("https://github.com/archive.zip","test"),{true})
        }
        assertEquals(0,output.size())
        assertTrue(ClientDownload.allowedUrl("https://release-assets.githubusercontent.com/file.zip"))
        assertTrue(ClientDownload.allowedUrl("https://codeload.github.com/DdejjCAT/jackbox.tv/zip/abc"))
        for(url in listOf("http://github.com/file.zip","https://github.com.evil.example/file.zip","https://user:pass@github.com/file.zip","https://127.0.0.1/file.zip","file:///private")) assertFalse(url,ClientDownload.allowedUrl(url))
    }
}
