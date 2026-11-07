package tv.localbox.vpn

import androidx.test.platform.app.InstrumentationRegistry
import dalvik.system.DexClassLoader
import java.io.File
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.zip.ZipFile
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.jf.dexlib2.*
import org.jf.dexlib2.dexbacked.DexBackedDexFile
import org.jf.dexlib2.immutable.*
import org.jf.dexlib2.immutable.instruction.*
import org.jf.dexlib2.immutable.reference.ImmutableMethodReference
import org.jf.dexlib2.writer.io.MemoryDataStore
import org.jf.dexlib2.writer.pool.DexPool
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Test-only replacement for native callbacks into Scaleform, never used in patched game APKs. */
object EcastBridgeEvents {
    val events=LinkedBlockingQueue<Pair<String,String>>()
    val responses=LinkedBlockingQueue<ByteArray>()
    @JvmStatic fun event(name: String,body: String) { events.offer(name to body) }
    @JvmStatic fun response(id: Int,result: Int,size: Int,body: ByteArray?) {
        responses.offer(body ?: "{\"error\":\"HTTP failed: $id/$result/$size\"}".toByteArray())
    }
}

class EcastPatchDeviceTest {
    @Test fun signedApkAndOriginalJpp7HttpAndWebsocketBridge() = verifyBridge(false)
    @Test fun signedMultiDexApkWithBridgesInDifferentDex() = verifyBridge(true)

    private fun verifyBridge(multiDex: Boolean) {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val supplied=File(context.filesDir,"fixture-ecast.apk")
        assertTrue("Supply the private JPP7 fixture-ecast.apk",supplied.isFile)
        val fixture=if(multiDex) splitDexFixture(supplied,File(context.cacheDir,"fixture-multidex.apk")) else supplied
        val originalHash=ApkPatch.sha256(fixture.readBytes())
        val source=ApkSelection.document(context,fixture.inputStream())
        assertTrue(ApkPatch.analyze(source.files).ecast)
        val result=ApkPatch.create(context,source,5557)
        val patched=result.files.single()
        assertEquals(originalHash,ApkPatch.sha256(fixture.readBytes()))
        ZipFile(fixture).use { before -> ZipFile(patched).use { after ->
            for(entry in before.entries()) {
                if(entry.name.startsWith("META-INF/") || entry.name.matches(Regex("classes[0-9]*\\.dex")) || entry.name in listOf("AndroidManifest.xml","assets/config.jet","assets/games/PartyPack/jbg.config.jet")) continue
                assertArrayEquals(entry.name,before.getInputStream(entry).use { it.readBytes() },after.getInputStream(after.getEntry(entry.name)).use { it.readBytes() })
            }
            val config=JSONObject(after.getInputStream(after.getEntry("assets/config.jet")).bufferedReader().use { it.readText() })
            assertEquals("127.0.0.1:5557",config.getString("serverUrl"))
        } }
        // Execute the game's real Java network methods. Only callbacks into the unstarted
        // native game engine are replaced by a recorder in this disposable test DEX.
        val testDex=File(context.codeCacheDir,"ecast-network-test-${System.nanoTime()}.jar")
        ZipOutputStream(testDex.outputStream()).use { output -> ZipFile(patched).use { z ->
            for(entry in z.entries().toList().filter { it.name.matches(Regex("classes[0-9]*\\.dex")) }) {
                output.putNextEntry(ZipEntry(entry.name))
                output.write(callbackRecorder(z.getInputStream(entry).use { it.readBytes() }))
                output.closeEntry()
            }
        } }
        assertTrue(testDex.setReadOnly())
        val loader=DexClassLoader(testDex.absolutePath,context.codeCacheDir.absolutePath,null,javaClass.classLoader)
        val queueClass=loader.loadClass("com.jackboxgames.jbgplayer.JNIUrlQueueManager")
        val rewrite=queueClass.getMethod(EcastDex.HELPER,String::class.java)
        assertEquals("http://127.0.0.1:5557/api/v2/rooms?retry=1",rewrite.invoke(null,"https://ecast.jackboxgames.com/api/v2/rooms?retry=1"))
        val download="https://downloads.example/pack7.zip"
        assertEquals(download,rewrite.invoke(null,download))
        EcastBridgeEvents.events.clear();EcastBridgeEvents.responses.clear()
        val directory=File(context.filesDir,"ecast-test-engine").apply { mkdirs() }
        context.assets.open("games.json").use { input -> File(directory,"games.json").outputStream().use { input.copyTo(it) } }
        NativeServer.load()
        assertNull(NativeServer.start(directory.absolutePath,"127.0.0.1",5557,8081))
        var socket: Any?=null
        var socketClass: Class<*>?=null
        try {
            val queue=queueClass.getMethod("getInstance").invoke(null)
            val create=JSONObject().put("appTag","quiplash3").put("appId","37c1627d-4b01-4f45-b95f-80197cd4403c")
                .put("userId","ecast-fixture-host").put("maxPlayers",8)
            queueClass.getMethod("QueueUrl",Int::class.javaPrimitiveType,String::class.java,ByteArray::class.java,
                Int::class.javaPrimitiveType,Array<String>::class.java).invoke(queue,42,
                "https://ecast.jackboxgames.com/api/v2/rooms",create.toString().toByteArray(),1,arrayOf("Content-Type","application/json"))
            val response=EcastBridgeEvents.responses.poll(15,TimeUnit.SECONDS)
            assertNotNull("Real Java REST request did not complete",response)
            val created=JSONObject(response!!.toString(Charsets.UTF_8))
            assertTrue(created.toString(),created.optBoolean("ok"))
            val room=created.getJSONObject("body")
            socketClass=loader.loadClass("com.jackboxgames.jbgplayer.JNIecastManager")
            socket=socketClass.getMethod("getInstance").invoke(null)
            val path="/api/v2/rooms/${room.getString("code")}/play?role=host&host-token=${room.getString("token")}&user-id=ecast-fixture-host"
            socketClass.getMethod("connect",String::class.java,Int::class.javaPrimitiveType,String::class.java,Boolean::class.javaPrimitiveType)
                .invoke(socket,"ecast.jackboxgames.com",443,path,true)
            awaitMessage("client/welcome")
            socketClass.getMethod("sendMessage",String::class.java).invoke(socket,
                """{"opcode":"room/lock","seq":1,"params":{}}""")
            awaitMessage("ok")
            assertFalse(JSONObject(NativeServer.status()).getJSONObject("room").getBoolean("qrVisible"))
        } finally {
            socket?.let { socketClass!!.getMethod("disconnect").invoke(it) }
            NativeServer.stop();testDex.delete()
        }
    }

    private fun splitDexFixture(source: File, destination: File): File {
        ZipFile(source).use { z -> ZipOutputStream(destination.outputStream()).use { output ->
            val d=DexBackedDexFile.fromInputStream(Opcodes.getDefault(),z.getInputStream(z.getEntry("classes.dex")).buffered())
            fun encoded(classes: Collection<org.jf.dexlib2.iface.ClassDef>): ByteArray {
                val store=MemoryDataStore();DexPool.writeTo(store,ImmutableDexFile(d.opcodes,classes));return store.data
            }
            for(entry in z.entries()) {
                if(entry.name.startsWith("META-INF/")) continue
                output.putNextEntry(ZipEntry(entry.name))
                if(entry.name=="classes.dex") output.write(encoded(d.classes.filterNot { EcastDex.isSocket(it) }))
                else z.getInputStream(entry).use { it.copyTo(output) }
                output.closeEntry()
            }
            output.putNextEntry(ZipEntry("classes2.dex"));output.write(encoded(d.classes.filter { EcastDex.isSocket(it) }));output.closeEntry()
        } }
        return destination
    }

    private fun awaitMessage(opcode: String): JSONObject {
        val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(15)
        while(System.nanoTime()<deadline) {
            val event=EcastBridgeEvents.events.poll(1,TimeUnit.SECONDS) ?: continue
            if(event.first=="WebSocket.ConnectResult") assertEquals("success",event.second)
            if(event.first!="WebSocket.MessageReceived") continue
            val msg=JSONObject(event.second)
            if(msg.optString("opcode")==opcode) return msg
        }
        error("Game Java bridge did not receive $opcode")
    }

    private fun callbackRecorder(bytes: ByteArray): ByteArray {
        val d=DexBackedDexFile.fromInputStream(Opcodes.getDefault(),bytes.inputStream().buffered())
        val classes=d.classes.map { c ->
            if(!c.type.endsWith("/JNIecastManager;") && !c.type.endsWith("/JNIUrlQueueManager;")) return@map c
            val methods=c.methods.map { m ->
                if(!AccessFlags.NATIVE.isSet(m.accessFlags)) return@map m
                check(m.returnType=="V" && AccessFlags.STATIC.isSet(m.accessFlags))
                val count=m.parameterTypes.size
                val instructions=mutableListOf<org.jf.dexlib2.iface.instruction.Instruction>()
                val name=when(m.name) { "NativeHandleEvent" -> "event"; "UrlQueueCallback" -> "response"; else -> null }
                if(name!=null) instructions.add(ImmutableInstruction3rc(Opcode.INVOKE_STATIC_RANGE,0,count,
                    ImmutableMethodReference("Ltv/localbox/vpn/EcastBridgeEvents;",name,m.parameterTypes,"V")))
                instructions.add(ImmutableInstruction10x(Opcode.RETURN_VOID))
                ImmutableMethod(m.definingClass,m.name,m.parameters,m.returnType,m.accessFlags and AccessFlags.NATIVE.value.inv(),
                    m.annotations,m.hiddenApiRestrictions,ImmutableMethodImplementation(count,instructions,emptyList(),emptyList()))
            }
            ImmutableClassDef(c.type,c.accessFlags,c.superclass,c.interfaces,c.sourceFile,c.annotations,c.fields,methods)
        }
        val store=MemoryDataStore();DexPool.writeTo(store,ImmutableDexFile(d.opcodes,classes));return store.data
    }
}
