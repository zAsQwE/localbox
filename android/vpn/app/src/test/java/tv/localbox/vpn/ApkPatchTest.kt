package tv.localbox.vpn

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.security.MessageDigest
import java.util.zip.Adler32
import java.util.zip.ZipFile
import org.jf.dexlib2.*
import org.jf.dexlib2.iface.instruction.ReferenceInstruction
import org.jf.dexlib2.iface.reference.StringReference
import org.jf.dexlib2.immutable.*
import org.jf.dexlib2.immutable.instruction.*
import org.jf.dexlib2.immutable.reference.ImmutableStringReference
import org.jf.dexlib2.writer.io.MemoryDataStore
import org.jf.dexlib2.writer.pool.DexPool

class ApkPatchTest {
    @Test fun changesGameSettingsPreservesDownloadsAndRejectsUnrelatedConfig() {
        val input="""{"serverUrl":"blobcast.jackboxgames.com","isBundle":"true","downloadUrl":"https://downloads.example/pack.zip"}""".toByteArray()
        val result=JSONObject(ApkPatch.patchConfig(input,5557)!!.toString(Charsets.UTF_8))
        assertEquals("127.0.0.1:5557",result.getString("serverUrl"))
        assertEquals("true",result.getString("isBundle"))
        assertEquals("https://downloads.example/pack.zip",result.getString("downloadUrl"))
        assertNull(ApkPatch.patchConfig("{\"serverUrl\":\"https://unrelated.example\"}".toByteArray(),5557))
        assertNull(ApkPatch.patchConfig("not json".toByteArray(),5557))
    }
    @Test fun rewritesKnownJavaUrlsAndPreservesOtherServices() {
        val original=urlDex(listOf("https://ecast.jackboxgames.com/api/v2/rooms","wss://us.blobcast.jackboxgames.com/socket.io/1/", "https://gamenews.jackboxgames.com/Status/test.json"))
        assertEquals(2,NetworkDex.inspect(original).urlCount)
        val patched=NetworkDex.patch(original,5557)
        val text=strings(patched)
        assertTrue("http://127.0.0.1:5557/api/v2/rooms" in text)
        assertTrue("ws://127.0.0.1:5557/socket.io/1/" in text)
        assertTrue("https://gamenews.jackboxgames.com/Status/test.json" in text)
        assertArrayEquals(patched,NetworkDex.patch(patched,5557))
        assertTrue("http://127.0.0.1:61234/api/v2/rooms" in strings(NetworkDex.patch(patched,61234)))
        assertFalse(NetworkDex.inspect(urlDex(listOf("https://example.org/","https://ecast.jackboxgames.com.evil.example/"))).supported)
        assertFalse(NetworkDex.inspect(urlDex(listOf("http://localhost:8080/","http://127.0.0.1:8080/api/v2/rooms"))).supported)
        assertThrows(IllegalArgumentException::class.java) { NetworkDex.patch(original,80) }
    }
    @Test fun copyGetsItsOwnPackageSoItInstallsNextToTheOriginal() {
        val (manifest,resources)=ZipFile(File(javaClass.getResource("/retarget-fixture.apk")!!.toURI())).use { zip ->
            zip.getInputStream(zip.getEntry("AndroidManifest.xml")).readBytes() to zip.getInputStream(zip.getEntry("resources.arsc")).readBytes() }
        assertEquals("com.example.game.localbox",BinaryManifest.copyPackage("com.example.game"))
        assertEquals("com.example.game.localbox",BinaryManifest.copyPackage("com.example.game.localbox"))
        val patched=BinaryManifest.retarget(BinaryManifest.allowLocalHttp(manifest),"com.example.game.localbox","Example Game · LocalBox")
        assertEquals("com.example.game.localbox",BinaryManifest.info(patched).packageName)
        val values=BinaryManifest.strings(patched)
        fun all(element: String,name: String)=values.filter { it.first==element && it.second==name }.map { it.third }
        // Classes stay where they are: relative names are resolved against the original package.
        assertEquals(listOf("com.example.game.GameApp"),all("application","name"))
        assertEquals(listOf("com.example.game.MainActivity","com.other.lib.Screen"),all("activity","name"))
        assertEquals(listOf("com.example.game.Worker"),all("service","name"))
        // Device-wide unique names follow the copy, so they don't clash with the installed original.
        assertEquals(listOf("com.example.game.localbox.files;shared.authority.localbox"),all("provider","authorities"))
        assertEquals(listOf("com.example.game.localbox.permission.C2D_MESSAGE","game.shared.PERMISSION.localbox"),all("permission","name"))
        assertTrue("com.example.game.localbox.permission.C2D_MESSAGE" in all("uses-permission","name"))
        assertTrue("android.permission.INTERNET" in all("uses-permission","name"))
        assertEquals(listOf("game.shared.PERMISSION.localbox"),all("service","permission"))
        // The launcher shows the copy apart from the original; other labels are kept.
        assertEquals(listOf("Example Game · LocalBox"),all("application","label"))
        assertEquals(listOf("Example Game · LocalBox"),all("activity","label"))
        // HTTP permission from allowLocalHttp survives, and a second pass on the copy changes nothing.
        assertArrayEquals(patched,BinaryManifest.retarget(patched,"com.example.game.localbox"))
        val table=BinaryManifest.retargetResources(resources,"com.example.game","com.example.game.localbox")!!
        assertEquals(resources.size,table.size)
        assertTrue(String(table,Charsets.UTF_16LE).contains("com.example.game.localbox"))
        assertNull(BinaryManifest.retargetResources(table,"com.example.game","com.example.game.localbox"))
        System.getenv("LOCALBOX_RETARGET_OUT")?.let { File(it).writeBytes(patched);File("$it.arsc").writeBytes(table) }
    }
    @Test fun malformedManifestIsRejected() {
        assertThrows(IllegalArgumentException::class.java) { BinaryManifest.allowLocalHttp(ByteArray(300)) }
    }
    @Test fun fixtureSupportsDifferentDexAndRepatchingWithoutVersionHashes() {
        val path=System.getenv("LOCALBOX_TEST_APK");assumeTrue("Optional private fixture: LOCALBOX_TEST_APK",!path.isNullOrEmpty())
        ZipFile(File(path!!)).use { zip ->
            val original=zip.getInputStream(zip.getEntry("classes.dex")).use { it.readBytes() }
            assertTrue(NetworkDex.inspect(original).blobcast)
            val patched=NetworkDex.patch(original,5557)
            assertTrue("http://127.0.0.1:5557/room" in strings(patched))
            assertTrue(NetworkDex.inspect(patched).blobcast)
            val again=NetworkDex.patch(patched,61234)
            assertTrue("http://127.0.0.1:61234/room" in strings(again))
            assertFalse("http://127.0.0.1:5557/room" in strings(again))
            assertArrayEquals(MessageDigest.getInstance("SHA-1").digest(patched.copyOfRange(32,patched.size)),patched.copyOfRange(12,32))
            val expected=Adler32().apply { update(patched,12,patched.size-12) }.value
            val actual=(0..3).fold(0L) { sum,i -> sum or ((patched[8+i].toLong() and 255) shl (i*8)) };assertEquals(expected,actual)
            val manifest=zip.getInputStream(zip.getEntry("AndroidManifest.xml")).use { it.readBytes() }
            val modified=BinaryManifest.allowLocalHttp(manifest)
            assertTrue(modified.size>manifest.size)
            assertArrayEquals(modified,BinaryManifest.allowLocalHttp(modified))
        }
    }
    private fun strings(bytes: ByteArray): List<String> = org.jf.dexlib2.dexbacked.DexBackedDexFile.fromInputStream(Opcodes.getDefault(),bytes.inputStream().buffered()).classes.flatMap { c ->
        c.methods.flatMap { m -> m.implementation?.instructions?.mapNotNull { i -> ((i as? ReferenceInstruction)?.reference as? StringReference)?.string }?.toList() ?: emptyList() }
    }
    private fun urlDex(urls: List<String>): ByteArray {
        val instructions=urls.map { ImmutableInstruction21c(Opcode.CONST_STRING,0,ImmutableStringReference(it)) }+ImmutableInstruction10x(Opcode.RETURN_VOID)
        val method=ImmutableMethod("Ltest/Network;","open",emptyList(),"V",AccessFlags.PUBLIC.value or AccessFlags.STATIC.value,emptySet(),emptySet(),ImmutableMethodImplementation(1,instructions,emptyList(),emptyList()))
        val cls=ImmutableClassDef("Ltest/Network;",AccessFlags.PUBLIC.value,"Ljava/lang/Object;",emptyList(),null,emptySet(),emptyList(),listOf(method))
        val store=MemoryDataStore();DexPool.writeTo(store,ImmutableDexFile(Opcodes.getDefault(),listOf(cls)));return store.data
    }
}
