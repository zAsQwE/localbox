package tv.localbox.vpn

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class ClientImportTest {
    private fun zip(vararg files: Pair<String, String>): ByteArrayInputStream {
        val bytes = ByteArrayOutputStream()
        ZipOutputStream(bytes).use { zip ->
            for ((name, value) in files) {
                zip.putNextEntry(ZipEntry(name)); zip.write(value.toByteArray()); zip.closeEntry()
            }
        }
        return ByteArrayInputStream(bytes.toByteArray())
    }

    @Test fun importsNestedClientAndPreservesRelativeAssets() {
        val folder = Files.createTempDirectory("localbox-client-").toFile()
        try {
            ClientImport.install(zip("client-ru/index.html" to "page", "client-ru/assets/a.js" to "script"), folder)
            assertEquals("page", File(folder, "client/index.html").readText())
            assertEquals("script", File(folder, "client/assets/a.js").readText())
        } finally { folder.deleteRecursively() }
    }

    @Test fun failedImportKeepsPreviousClientAndRejectsTraversal() {
        val folder = Files.createTempDirectory("localbox-client-").toFile()
        try {
            File(folder, "client").mkdirs()
            File(folder, "client/index.html").writeText("previous")
            assertThrows(IllegalArgumentException::class.java) { ClientImport.install(zip("../escape" to "bad"), folder) }
            assertEquals("previous", File(folder, "client/index.html").readText())
            assertFalse(File(folder.parentFile, "escape").exists())
        } finally { folder.deleteRecursively() }
    }

    @Test fun keepsBothLanguagesAndRollsBackCancelledImport() {
        val folder=Files.createTempDirectory("localbox-client-").toFile()
        try {
            ClientImport.install(zip("index.html" to "English","main/a.js" to "en"),folder)
            ClientImport.install(zip("client-ru/index.html" to "Русский","client-ru/main/a.js" to "ru"),folder,"client-ru",requireMain=true)
            assertEquals("English",File(folder,"client/index.html").readText())
            assertEquals("Русский",File(folder,"client-ru/index.html").readText())
            assertThrows(java.util.concurrent.CancellationException::class.java) {
                ClientImport.install(zip("index.html" to "new"),folder,"client-ru",{true})
            }
            assertEquals("Русский",File(folder,"client-ru/index.html").readText())
            assertThrows(IllegalArgumentException::class.java) { ClientImport.install(zip("index.html" to "invalid"),folder,"client-ru",requireMain=true) }
            assertEquals("Русский",File(folder,"client-ru/index.html").readText())
        } finally { folder.deleteRecursively() }
    }

    @Test fun sizeLimitStopsBeforeWritingExcessBytes() {
        val output = ByteArrayOutputStream()
        assertThrows(IllegalArgumentException::class.java) { ClientImport.copyLimited(ByteArrayInputStream(ByteArray(200)), output, 100) }
        assertEquals(0, output.size())
    }

    @Test fun portsMustBeDifferentUnprivilegedAndBrowserCompatible() {
        assertNull(Ports.error(5555, 8080))
        assertNotNull(Ports.error(5555, 6666))
        assertNotNull(Ports.error(5555, 5555))
        assertNotNull(Ports.error(443, 8080))
    }
}
