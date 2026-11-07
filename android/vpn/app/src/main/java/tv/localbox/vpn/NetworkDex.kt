package tv.localbox.vpn

import org.jf.dexlib2.Opcode
import org.jf.dexlib2.Opcodes
import org.jf.dexlib2.AccessFlags
import org.jf.dexlib2.dexbacked.DexBackedDexFile
import org.jf.dexlib2.iface.ClassDef
import org.jf.dexlib2.iface.Method
import org.jf.dexlib2.iface.instruction.*
import org.jf.dexlib2.iface.reference.FieldReference
import org.jf.dexlib2.iface.reference.StringReference
import org.jf.dexlib2.immutable.*
import org.jf.dexlib2.immutable.instruction.ImmutableInstruction21c
import org.jf.dexlib2.immutable.instruction.ImmutableInstruction31c
import org.jf.dexlib2.immutable.reference.ImmutableStringReference
import org.jf.dexlib2.immutable.value.ImmutableStringEncodedValue
import org.jf.dexlib2.writer.io.MemoryDataStore
import org.jf.dexlib2.writer.pool.DexPool
import java.security.MessageDigest

/** Recognize the network implementation, independent of APK package, version and DEX location. */
object NetworkDex {
    private const val MARKER_PREFIX = "Ltv/localbox/patch/NetworkMarker"
    private const val MARKER_ID = "localbox-game-network-v1"
    data class Match(val blobcast: Boolean, val urlCount: Int, val ecastSocket: Boolean = false, val ecastHttp: Boolean = false) {
        val ecast get() = ecastSocket || ecastHttp
        val supported get() = blobcast || ecast || urlCount>0
    }
    private val local=Regex("^http://127\\.0\\.0\\.1:[0-9]+/room$")
    private val parameterTypes=listOf("Ljava/lang/String;","Ljava/lang/String;","Ljava/lang/String;","Z")
    private fun dex(bytes: ByteArray)=DexBackedDexFile.fromInputStream(Opcodes.getDefault(),bytes.inputStream().buffered())
    private fun text(i: Instruction)=((i as? ReferenceInstruction)?.reference as? StringReference)?.string
    private fun marked(c: ClassDef) = c.type.startsWith(MARKER_PREFIX) && c.fields.any {
        it.name=="id" && (it.initialValue as? org.jf.dexlib2.iface.value.StringEncodedValue)?.value==MARKER_ID
    }
    private fun allowLocal(classes: Collection<ClassDef>) = classes.any { marked(it) || EcastDex.isSocket(it) || EcastDex.isHttp(it) || blobcast(it) }
    private fun rewrite(value: String,port: Int,localAllowed: Boolean): String? {
        val match=GameEndpoints.literal.matchEntire(value) ?: return null
        val host=match.groupValues[2].substringBefore(':').lowercase()
        if(!localAllowed && host in listOf("127.0.0.1","localhost")) return null
        return GameEndpoints.rewriteLiteral(value,port)
    }
    private fun blobcast(c: ClassDef): Boolean {
        if(!c.type.endsWith("/blobcast/BlobCastClient;")) return false
        if(c.fields.none { it.name=="_socket" && it.type=="Lcom/koushikdutta/async/http/socketio/SocketIOClient;" }) return false
        val constructors=c.methods.filter { it.name=="<init>" }.toList()
        if(constructors.size!=1) return false
        val ctor=constructors.single();val impl=ctor.implementation ?: return false
        if(ctor.parameterTypes.size!=5 || ctor.parameterTypes.drop(1).map { it.toString() }!=parameterTypes || impl.tryBlocks.isNotEmpty()) return false
        if(!ctor.parameterTypes.first().toString().endsWith("/IBlobCastClientDelegate;")) return false
        // A prefix is safe only for this straight-line constructor; no branch/exception offsets move.
        if(impl.instructions.any { it is OffsetInstruction }) return false
        val urlRegister=impl.registerCount-6+2
        if(urlRegister !in 0..255 || impl.instructions.none {
            it.opcode==Opcode.IPUT_OBJECT && (it as TwoRegisterInstruction).registerA==urlRegister &&
                ((it as ReferenceInstruction).reference as? FieldReference)?.let { f -> f.name=="_url" && f.type=="Ljava/lang/String;" && f.definingClass==c.type }==true
        }) return false
        val connect=c.methods.singleOrNull { it.name=="connectToService" && it.parameterTypes.isEmpty() }?.implementation ?: return false
        return connect.instructions.any { text(it) in listOf(":38202",":38203") } ||
            (text(impl.instructions.first())?.matches(local)==true && connect.instructions.any { text(it)=="" })
    }
    fun inspect(bytes: ByteArray): Match {
        val d=dex(bytes)
        val localAllowed=allowLocal(d.classes)
        return Match(d.classes.any { blobcast(it) },d.classes.sumOf { c -> c.methods.sumOf { m -> m.implementation?.instructions?.count { text(it)?.let { s -> rewrite(s,5555,localAllowed)!=null }==true } ?: 0 } }, d.classes.any { EcastDex.isSocket(it) }, d.classes.any { EcastDex.isHttp(it) })
    }
    fun patch(bytes: ByteArray, port: Int): ByteArray {
        require(port in 1024..65535)
        val d=dex(bytes);val ecast=d.classes.any { EcastDex.isSocket(it) || EcastDex.isHttp(it) };var changed=ecast
        val localAllowed=allowLocal(d.classes)
        val classes=d.classes.map { c ->
            val bc=blobcast(c)
            val methods=c.methods.map { method ->
                val impl=method.implementation ?: return@map method
                var modified=false
                val code=impl.instructions.map { i ->
                    val old=text(i)
                    val value=when {
                        bc && old in listOf(":38202",":38203") -> ""
                        old!=null -> rewrite(old,port,localAllowed)
                        else -> null
                    }
                    if(value==null) i else { modified=true;replaceString(i,value) }
                }.toMutableList()
                val constructor=bc && method.name=="<init>"
                if(constructor) {
                    val instruction=ImmutableInstruction21c(Opcode.CONST_STRING,impl.registerCount-6+2,ImmutableStringReference("http://127.0.0.1:$port/room"))
                    if(text(code.first())?.matches(local)==true) code[0]=instruction else code.add(0,instruction)
                    modified=true
                }
                if(!modified) method else {
                    changed=true
                    ImmutableMethod(method.definingClass,method.name,method.parameters,method.returnType,method.accessFlags,method.annotations,method.hiddenApiRestrictions,
                        ImmutableMethodImplementation(impl.registerCount,code,impl.tryBlocks,if(constructor) emptyList() else impl.debugItems))
                }
            }
            ImmutableClassDef(c.type,c.accessFlags,c.superclass,c.interfaces,c.sourceFile,c.annotations,c.fields,methods)
        }
        require(changed) { "В этом DEX нет поддерживаемого сетевого клиента" }
        val output=(if(ecast) classes.map { EcastDex.patch(it,port) } else classes).toMutableList()
        if(d.classes.none { marked(it) }) {
            // Each DEX/split gets its own marker type: avoid duplicate classes in a patched set.
            val identity=d.classes.map { it.type }.sorted().joinToString("\n").toByteArray(Charsets.UTF_8)
            val suffix=MessageDigest.getInstance("SHA-256").digest(identity).take(16).joinToString("") { "%02x".format(it) }
            val marker="${MARKER_PREFIX}_$suffix;"
            require(d.classes.none { it.type==marker }) { "В DEX конфликтует маркер LocalBox" }
            output.add(ImmutableClassDef(marker,AccessFlags.PUBLIC.value or AccessFlags.FINAL.value,"Ljava/lang/Object;",emptyList(),null,emptySet(),
                listOf(ImmutableField(marker,"id","Ljava/lang/String;",AccessFlags.PUBLIC.value or AccessFlags.STATIC.value or AccessFlags.FINAL.value,
                    ImmutableStringEncodedValue(MARKER_ID),emptySet(),emptySet())),emptyList()))
        }
        val store=MemoryDataStore();DexPool.writeTo(store,ImmutableDexFile(d.opcodes,output));return store.data
    }
    private fun replaceString(i: Instruction,value: String): Instruction {
        val reg=(i as OneRegisterInstruction).registerA
        return when(i.opcode) {
            Opcode.CONST_STRING -> ImmutableInstruction21c(i.opcode,reg,ImmutableStringReference(value))
            Opcode.CONST_STRING_JUMBO -> ImmutableInstruction31c(i.opcode,reg,ImmutableStringReference(value))
            else -> error("Неподдерживаемая строковая инструкция")
        }
    }
}
