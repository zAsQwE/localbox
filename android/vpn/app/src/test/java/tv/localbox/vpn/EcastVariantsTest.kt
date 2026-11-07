package tv.localbox.vpn

import java.io.File
import java.nio.file.Files
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream
import org.jf.dexlib2.*
import org.jf.dexlib2.dexbacked.DexBackedDexFile
import org.jf.dexlib2.builder.MutableMethodImplementation
import org.jf.dexlib2.builder.instruction.*
import org.jf.dexlib2.iface.ClassDef
import org.jf.dexlib2.iface.instruction.ReferenceInstruction
import org.jf.dexlib2.iface.instruction.FiveRegisterInstruction
import org.jf.dexlib2.iface.instruction.OneRegisterInstruction
import org.jf.dexlib2.iface.reference.MethodReference
import org.jf.dexlib2.iface.reference.StringReference
import org.jf.dexlib2.immutable.*
import org.jf.dexlib2.immutable.instruction.*
import org.jf.dexlib2.immutable.reference.*
import org.jf.dexlib2.rewriter.*
import org.jf.dexlib2.writer.io.MemoryDataStore
import org.jf.dexlib2.writer.pool.DexPool
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class EcastVariantsTest {
    private fun fixture(): DexBackedDexFile {
        val path=System.getenv("LOCALBOX_ECAST_APK")
        assumeTrue("Private fixture required",!path.isNullOrEmpty())
        val data=ZipFile(path!!).use { z -> z.getInputStream(z.getEntry("classes.dex")).use { it.readBytes() } }
        return DexBackedDexFile.fromInputStream(Opcodes.getDefault(),data.inputStream().buffered())
    }
    private fun encode(classes: Collection<ClassDef>): ByteArray {
        val store=MemoryDataStore();DexPool.writeTo(store,ImmutableDexFile(Opcodes.getDefault(),classes));return store.data
    }
    private fun apk(file: File,entries: Map<String,ByteArray>) {
        ZipOutputStream(file.outputStream()).use { z -> for((name,data) in entries) { z.putNextEntry(ZipEntry(name));z.write(data);z.closeEntry() } }
    }
    @Test fun detectsBothBridgesAcrossDexAndSplitFilesButRejectsAnIncompleteSet() {
        val classes=fixture().classes
        val socket=classes.filter { EcastDex.isSocket(it) }
        val other=classes.filterNot { EcastDex.isSocket(it) }
        assertTrue(socket.isNotEmpty())
        val directory=Files.createTempDirectory("localbox-multidex").toFile()
        try {
            val base=File(directory,"base.apk");val split=File(directory,"split.apk")
            apk(base,mapOf("classes.dex" to encode(other)))
            apk(split,mapOf("classes2.dex" to encode(socket)))
            assertFalse(ApkPatch.analyze(listOf(base)).supported)
            assertFalse(ApkPatch.analyze(listOf(split)).supported)
            val complete=ApkPatch.analyze(listOf(base,split))
            assertTrue(complete.supported);assertTrue(complete.ecast)
            assertTrue(NetworkDex.inspect(NetworkDex.patch(encode(socket),5557)).ecastSocket)
            assertTrue(NetworkDex.inspect(NetworkDex.patch(encode(other),5557)).ecastHttp)
            val types=listOf(socket,other).flatMap { part ->
                val patched=NetworkDex.patch(encode(part),5557)
                DexBackedDexFile.fromInputStream(Opcodes.getDefault(),patched.inputStream().buffered()).classes.map { it.type }
            }
            assertEquals(types.size,types.distinct().size)
            apk(base,mapOf("classes.dex" to encode(other),"classes2.dex" to encode(socket)))
            assertTrue(ApkPatch.analyze(listOf(base)).ecast)
        } finally { directory.deleteRecursively() }
    }
    @Test fun acceptsRelocatedBridgeNamespacesAndRepatchesTheirActualOwnerReferences() {
        val rewriter=DexRewriter(object: RewriterModule() {
            override fun getTypeRewriter(rewriters: Rewriters): Rewriter<String> = Rewriter { value ->
                value.replace("Lcom/jackboxgames/jbgplayer/","Lexample/androidport/")
            }
        })
        val relocated=encode(rewriter.dexFileRewriter.rewrite(fixture()).classes)
        assertTrue(NetworkDex.inspect(relocated).ecast)
        val result=NetworkDex.patch(relocated,61234)
        val parsed=DexBackedDexFile.fromInputStream(Opcodes.getDefault(),result.inputStream().buffered())
        val http=parsed.classes.single { EcastDex.isHttp(it) }
        val first=http.methods.single { it.name=="QueueUrl" }.implementation!!.instructions.first()
        assertEquals(http.type,((first as ReferenceInstruction).reference as MethodReference).definingClass)
        assertArrayEquals(result,NetworkDex.patch(result,61234))
    }
    @Test fun supportsUriWebsocketBridgeAndKeepsItsPathAndQuery() {
        val classes=fixture().classes.map { c ->
            if(!EcastDex.isSocket(c)) return@map c
            val methods=c.methods.map { m ->
                if(m.name!="connect") return@map m
                ImmutableMethod(m.definingClass,m.name,listOf(ImmutableMethodParameter("Ljava/lang/String;",emptySet(),null)),"V",
                    m.accessFlags,m.annotations,m.hiddenApiRestrictions,ImmutableMethodImplementation(5,listOf(
                        ImmutableInstruction21c(Opcode.CONST_STRING,0,ImmutableStringReference("ecast-v0")),
                        ImmutableInstruction35c(Opcode.INVOKE_STATIC,0,0,0,0,0,0,ImmutableMethodReference("Lcom/koushikdutta/async/http/AsyncHttpClient;","getDefaultInstance",emptyList(),"Lcom/koushikdutta/async/http/AsyncHttpClient;")),
                        ImmutableInstruction11x(Opcode.MOVE_RESULT_OBJECT,1),
                        ImmutableInstruction11n(Opcode.CONST_4,2,0),
                        ImmutableInstruction35c(Opcode.INVOKE_VIRTUAL,4,1,4,0,2,0,ImmutableMethodReference("Lcom/koushikdutta/async/http/AsyncHttpClient;","websocket",listOf("Ljava/lang/String;","Ljava/lang/String;","Lcom/koushikdutta/async/http/AsyncHttpClient\$WebSocketConnectCallback;"),"Lcom/koushikdutta/async/future/Future;")),
                        ImmutableInstruction10x(Opcode.RETURN_VOID)
                    ),emptyList(),emptyList()))
            }
            ImmutableClassDef(c.type,c.accessFlags,c.superclass,c.interfaces,c.sourceFile,c.annotations,c.fields,methods)
        }
        val data=encode(classes);assertTrue(NetworkDex.inspect(data).ecast)
        val patched=NetworkDex.patch(data,5557)
        assertArrayEquals(patched,NetworkDex.patch(patched,5557))
        val url="wss://ecast-prod-use2.jackboxgames.com/api/v2/rooms/ABCD/play?role=host&host-token=a%2Fb"
        assertEquals("ws://127.0.0.1:5557/api/v2/rooms/ABCD/play?role=host&host-token=a%2Fb",url.replaceFirst(Regex(EcastDex.wsPattern),"ws://127.0.0.1:5557"))
    }
    @Test fun recognizesRegionalEndpointsWithoutRedirectingDownloadsOrImpostors() {
        for(host in listOf("ecast-prod-use2.jackboxgames.com","ecast.jackbox.tv","jb-ecast.klucva.ru","server.rujackbox.loamfy.com")) {
            assertEquals("http://127.0.0.1:5557/api/v2/rooms",GameEndpoints.rewriteLiteral("https://$host/api/v2/rooms",5557))
            assertNull(GameEndpoints.rewriteLiteral("https://$host/download/game.zip",5557))
            assertNull(GameEndpoints.rewriteLiteral("https://$host.evil.example/api/v2/rooms",5557))
        }
        assertEquals("ws://127.0.0.1:61234/api/v2/rooms/ABCD/play",GameEndpoints.rewriteLiteral("ws://127.0.0.1:5555/api/v2/rooms/ABCD/play",61234))
    }
    @Test fun patchesSocketThatBuildsItsPortFromTheIntegerArgument() {
        val classes=fixture().classes.map { c ->
            if(!EcastDex.isSocket(c)) return@map c
            val methods=c.methods.map { m ->
                if(m.name!="connect") return@map m
                val code=MutableMethodImplementation(m.implementation!!)
                val index=code.instructions.indexOfFirst { ((it as? ReferenceInstruction)?.reference as? StringReference)?.string==":80" }
                assertTrue(index>=0)
                val register=(code.instructions[index] as OneRegisterInstruction).registerA
                code.replaceInstruction(index,BuilderInstruction21c(Opcode.CONST_STRING,register,ImmutableStringReference(":")))
                val builder=(code.instructions[index+1] as FiveRegisterInstruction).registerC
                code.addInstruction(index+3,BuilderInstruction35c(Opcode.INVOKE_VIRTUAL,2,builder,m.implementation!!.registerCount-3,0,0,0,
                    ImmutableMethodReference("Ljava/lang/StringBuilder;","append",listOf("I"),"Ljava/lang/StringBuilder;")))
                code.addInstruction(index+4,BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT,builder))
                ImmutableMethod(m.definingClass,m.name,m.parameters,m.returnType,m.accessFlags,m.annotations,m.hiddenApiRestrictions,code)
            }
            ImmutableClassDef(c.type,c.accessFlags,c.superclass,c.interfaces,c.sourceFile,c.annotations,c.fields,methods)
        }
        val original=encode(classes);assertTrue(NetworkDex.inspect(original).ecast)
        val patched=NetworkDex.patch(original,61234)
        assertArrayEquals(patched,NetworkDex.patch(patched,61234))
    }
}
