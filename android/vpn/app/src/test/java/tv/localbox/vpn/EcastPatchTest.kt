package tv.localbox.vpn

import java.io.File
import java.util.zip.ZipFile
import org.jf.dexlib2.*
import org.jf.dexlib2.dexbacked.DexBackedDexFile
import org.jf.dexlib2.iface.instruction.*
import org.jf.dexlib2.iface.reference.MethodReference
import org.jf.dexlib2.iface.reference.StringReference
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class EcastPatchTest {
    @Test fun redirectsOnlyGameApiAndPreservesPathsAndOtherServices() {
        val pattern = Regex(EcastDex.httpPattern)
        for (host in listOf("ecast.jackboxgames.com", "ecast-prod-use2.jackboxgames.com", "api.jackbox.tv", "127.0.0.1:5555")) {
            val path = "/api/v2/rooms?retry=2&name=A%20B"
            assertEquals("http://127.0.0.1:5557$path", "https://$host$path".replaceFirst(pattern, "http://127.0.0.1:5557"))
        }
        for (url in listOf("https://downloads.example/pack.zip", "https://ecast.jackboxgames.com/assets/game.zip",
            "https://ecast.jackboxgames.com.evil.example/api/v2/rooms", "https://ecast.jackboxgames.com@evil.example/api/v2/rooms",
            "https://gamenews.jackboxgames.com/api/v2/news", "https://api.jackbox.tv/api/v20/rooms")) {
            assertEquals(url, url.replaceFirst(pattern, "http://127.0.0.1:5557"))
        }
        val config = JSONObject(ApkPatch.patchConfig("""{"serverUrl":"127.0.0.1:5555","downloadUrl":"https://example.org/pack.zip"}""".toByteArray(),5557)!!.toString(Charsets.UTF_8))
        assertEquals("127.0.0.1:5557", config.getString("serverUrl"))
        assertEquals("https://example.org/pack.zip", config.getString("downloadUrl"))
    }

    @Test fun patchesActualJpp7BridgeAndPreservesControlFlowAndNativeMethods() {
        val path=System.getenv("LOCALBOX_ECAST_APK")
        assumeTrue("Private fixture: LOCALBOX_ECAST_APK", !path.isNullOrEmpty())
        ZipFile(File(path!!)).use { zip ->
            val original=zip.getInputStream(zip.getEntry("classes.dex")).use { it.readBytes() }
            val match=NetworkDex.inspect(original)
            assertTrue(match.ecast)
            assertTrue(ApkPatch.analyze(listOf(File(path))).ecast)
            val patched=NetworkDex.patch(original,5557)
            assertTrue(NetworkDex.inspect(patched).ecast)
            assertArrayEquals(patched, NetworkDex.patch(patched,5557))
            val again=NetworkDex.patch(patched,61234)
            val before=dex(original);val after=dex(again)
            val socket=after.classes.single { it.type.endsWith("/JNIecastManager;") }
            val connect=socket.methods.single { it.name=="connect" }
            val code=connect.implementation!!.instructions.toList()
            assertEquals("127.0.0.1", ((code[0] as ReferenceInstruction).reference as StringReference).string)
            assertEquals(61234, (code[1] as NarrowLiteralInstruction).narrowLiteral)
            val strings=code.mapNotNull { ((it as? ReferenceInstruction)?.reference as? StringReference)?.string }
            assertTrue(":61234" in strings);assertFalse(":80" in strings);assertFalse(":5557" in strings)
            val oldHttp=before.classes.single { it.type.endsWith("/JNIUrlQueueManager;") }
            val newHttp=after.classes.single { it.type==oldHttp.type }
            val oldQueue=oldHttp.methods.single { it.name=="QueueUrl" }.implementation!!
            val newQueue=newHttp.methods.single { it.name=="QueueUrl" }.implementation!!
            assertEquals(EcastDex.HELPER, ((newQueue.instructions.first() as ReferenceInstruction).reference as MethodReference).name)
            assertEquals(1, newHttp.methods.count { it.name==EcastDex.HELPER })
            assertEquals(oldQueue.tryBlocks.map { it.startCodeAddress+4 }, newQueue.tryBlocks.map { it.startCodeAddress })
            assertEquals(oldQueue.tryBlocks.map { it.codeUnitCount }, newQueue.tryBlocks.map { it.codeUnitCount })
            assertEquals(oldQueue.tryBlocks.flatMap { it.exceptionHandlers }.map { it.handlerCodeAddress+4 },
                newQueue.tryBlocks.flatMap { it.exceptionHandlers }.map { it.handlerCodeAddress })
            assertEquals(oldQueue.instructions.count()+2, newQueue.instructions.count())
            for (c in before.classes) {
                val next=after.classes.single { it.type==c.type }
                for(m in c.methods.filter { AccessFlags.NATIVE.isSet(it.accessFlags) }) {
                    val n=next.methods.single { it.name==m.name && it.parameterTypes==m.parameterTypes }
                    assertEquals(m.accessFlags,n.accessFlags);assertNull(n.implementation)
                }
            }
            System.getenv("LOCALBOX_PATCHED_DEX")?.let { File(it).writeBytes(patched) }
        }
    }
    private fun dex(bytes: ByteArray)=DexBackedDexFile.fromInputStream(Opcodes.getDefault(),bytes.inputStream().buffered())
}
