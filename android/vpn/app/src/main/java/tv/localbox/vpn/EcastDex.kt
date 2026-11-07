package tv.localbox.vpn

import org.jf.dexlib2.AccessFlags
import org.jf.dexlib2.Opcode
import org.jf.dexlib2.builder.MutableMethodImplementation
import org.jf.dexlib2.builder.instruction.*
import org.jf.dexlib2.iface.ClassDef
import org.jf.dexlib2.iface.Method
import org.jf.dexlib2.iface.instruction.ReferenceInstruction
import org.jf.dexlib2.iface.reference.MethodReference
import org.jf.dexlib2.iface.reference.StringReference
import org.jf.dexlib2.immutable.*
import org.jf.dexlib2.immutable.instruction.*
import org.jf.dexlib2.immutable.reference.*

/** Recognized Scaleform Java JNI bridges, independent of pack, namespace and DEX location.
 * Redirect at the bridge boundary so separately downloaded SWFs/configs use it too.
 * Never modify native libraries, certificate verification, licensing or asset URLs.
 */
object EcastDex {
    const val HELPER = "\$localbox\$ecastHttp"
    const val WS_HELPER = "\$localbox\$ecastWs"
    private val socketParams = listOf("Ljava/lang/String;", "I", "Ljava/lang/String;", "Z")
    private val httpParams = listOf("I", "Ljava/lang/String;", "[B", "I", "[Ljava/lang/String;")
    // Rewrite game API traffic only. News, analytics, stores and game downloads remain upstream.
    val httpPattern = "(?i)^https?://${GameEndpoints.authorityPattern}(?=/api/v2(?:/|[?#]|$)|/tts/generate(?:[?#]|$))"
    val wsPattern = "(?i)^wss?://${GameEndpoints.authorityPattern}(?=/api/v2/(?:rooms|audience)/)"
    private fun texts(method: Method) = method.implementation?.instructions?.mapNotNull {
        ((it as? ReferenceInstruction)?.reference as? StringReference)?.string
    }?.toList().orEmpty()
    private fun refs(method: Method) = method.implementation?.instructions?.mapNotNull {
        (it as? ReferenceInstruction)?.reference as? MethodReference
    }?.toList().orEmpty()
    private fun socketMethod(c: ClassDef) = c.methods.singleOrNull {
        it.name.equals("connect", true) && it.parameterTypes.map { p -> p.toString() } in listOf(socketParams, listOf("Ljava/lang/String;")) && it.returnType == "V" &&
            it.implementation != null
    }
    private fun httpMethod(c: ClassDef) = c.methods.singleOrNull {
        it.name.equals("QueueUrl", true) && it.parameterTypes.map { p -> p.toString() } == httpParams && it.returnType == "V" &&
            it.implementation != null
    }
    fun isSocket(socket: ClassDef): Boolean {
        if (!socket.type.endsWith("/JNIecastManager;")) return false
        val connect = socketMethod(socket) ?: return false
        val strings = texts(connect)
        val uri = connect.parameterTypes.size == 1
        val port = connect.implementation!!.registerCount - 3
        val dynamicPort = connect.implementation!!.instructions.any {
            val ref = (it as? ReferenceInstruction)?.reference as? MethodReference
            ref?.definingClass == "Ljava/lang/StringBuilder;" && ref.name == "append" && ref.parameterTypes == listOf("I") &&
                ((it as? org.jf.dexlib2.iface.instruction.FiveRegisterInstruction)?.registerD == port ||
                    (it as? org.jf.dexlib2.iface.instruction.RegisterRangeInstruction)?.startRegister?.plus(1) == port)
        }
        return socket.fields.any { it.type == "Lcom/koushikdutta/async/http/WebSocket;" } &&
            socket.methods.any { it.name == "NativeHandleEvent" && AccessFlags.NATIVE.isSet(it.accessFlags) } &&
            "ecast-v0" in strings && (uri || (strings.any { it == "ws://" || it == "wss://" } &&
                (strings.any { it.matches(Regex(":[0-9]{1,5}")) } || dynamicPort))) &&
            refs(connect).any { it.definingClass == "Lcom/koushikdutta/async/http/AsyncHttpClient;" && it.name == "websocket" } &&
            connect.implementation!!.registerCount in (connect.parameterTypes.size + if (AccessFlags.STATIC.isSet(connect.accessFlags)) 0 else 1)..255
    }
    fun isHttp(http: ClassDef): Boolean {
        if (!http.type.endsWith("/JNIUrlQueueManager;")) return false
        val queue = httpMethod(http) ?: return false
        return http.fields.any { it.name == "vUrlQueue" && it.type == "Ljava/util/HashMap;" } &&
            refs(queue).any { it.definingClass == http.type && it.name.equals("ProcessNextUrl", true) } &&
            http.methods.any { it.name == "UrlQueueCallback" && AccessFlags.NATIVE.isSet(it.accessFlags) } &&
            queue.implementation!!.registerCount in (if (AccessFlags.STATIC.isSet(queue.accessFlags)) 5 else 6)..255
    }
    fun supports(classes: Collection<ClassDef>) = classes.any { isSocket(it) } && classes.any { isHttp(it) }
    private fun method(original: Method, implementation: org.jf.dexlib2.iface.MethodImplementation) =
        ImmutableMethod(original.definingClass, original.name, original.parameters, original.returnType,
            original.accessFlags, original.annotations, original.hiddenApiRestrictions, implementation)

    fun patch(c: ClassDef, port: Int): ClassDef {
        val socket = isSocket(c)
        val http = isHttp(c)
        if (!socket && !http) return c
        val uriSocket = socket && socketMethod(c)!!.parameterTypes.size == 1
        val methods = c.methods.map { original ->
            when {
                socket && uriSocket && original == socketMethod(c) -> wrapArgument(original, c.type, WS_HELPER, original.implementation!!.registerCount - 1)
                socket && original == socketMethod(c) -> {
                    val impl = original.implementation!!
                    val code = MutableMethodImplementation(impl)
                    // Keep branches, catch ranges and debug offsets attached to their original instructions.
                    for (index in code.instructions.indices) {
                        val instruction = code.instructions[index]
                        val text = ((instruction as? ReferenceInstruction)?.reference as? StringReference)?.string ?: continue
                        val replacement = when {
                            text == "wss://" -> "ws://"
                            text.matches(Regex(":[0-9]{1,5}")) -> ":$port"
                            else -> continue
                        }
                        val register = (instruction as org.jf.dexlib2.iface.instruction.OneRegisterInstruction).registerA
                        code.replaceInstruction(index, if (instruction.opcode == Opcode.CONST_STRING_JUMBO)
                            BuilderInstruction31c(Opcode.CONST_STRING_JUMBO, register, ImmutableStringReference(replacement))
                        else BuilderInstruction21c(Opcode.CONST_STRING, register, ImmutableStringReference(replacement)))
                    }
                    val hostRegister = impl.registerCount - 4
                    // Idempotent: replace our old prefix when changing the selected port.
                    val first = code.instructions.take(3)
                    val oldPrefix = first.size == 3 && first[0].opcode == Opcode.CONST_STRING &&
                        (first[0] as org.jf.dexlib2.iface.instruction.OneRegisterInstruction).registerA == hostRegister &&
                        ((first[0] as ReferenceInstruction).reference as? StringReference)?.string == "127.0.0.1" &&
                        first[1].opcode == Opcode.CONST && first[2].opcode == Opcode.CONST_16
                    if (oldPrefix) repeat(3) { code.removeInstruction(0) }
                    code.addInstruction(0, BuilderInstruction21c(Opcode.CONST_STRING, hostRegister, ImmutableStringReference("127.0.0.1")))
                    code.addInstruction(1, BuilderInstruction31i(Opcode.CONST, hostRegister + 1, port))
                    code.addInstruction(2, BuilderInstruction21s(Opcode.CONST_16, hostRegister + 3, 0))
                    method(original, code)
                }
                http && original == httpMethod(c) -> wrapArgument(original, c.type, HELPER, original.implementation!!.registerCount - 4)
                else -> original
            }
        }.filterNot { (http && it.name == HELPER) || (uriSocket && it.name == WS_HELPER) }.toMutableList()
        if (http || uriSocket) {
            methods.add(ImmutableMethod(c.type, if (http) HELPER else WS_HELPER,
                listOf(ImmutableMethodParameter("Ljava/lang/String;", emptySet(), null)), "Ljava/lang/String;",
                AccessFlags.PUBLIC.value or AccessFlags.STATIC.value or AccessFlags.SYNTHETIC.value, emptySet(), emptySet(),
                ImmutableMethodImplementation(3, listOf(
                    ImmutableInstruction21c(Opcode.CONST_STRING, 0, ImmutableStringReference(if (http) httpPattern else wsPattern)),
                    ImmutableInstruction21c(Opcode.CONST_STRING, 1, ImmutableStringReference("${if (http) "http" else "ws"}://127.0.0.1:$port")),
                    ImmutableInstruction35c(Opcode.INVOKE_VIRTUAL, 3, 2, 0, 1, 0, 0,
                        ImmutableMethodReference("Ljava/lang/String;", "replaceFirst", listOf("Ljava/lang/String;", "Ljava/lang/String;"), "Ljava/lang/String;")),
                    ImmutableInstruction11x(Opcode.MOVE_RESULT_OBJECT, 2),
                    ImmutableInstruction11x(Opcode.RETURN_OBJECT, 2)
                ), emptyList(), emptyList())))
        }
        return ImmutableClassDef(c.type, c.accessFlags, c.superclass, c.interfaces, c.sourceFile, c.annotations, c.fields, methods)
    }
    private fun wrapArgument(original: Method, owner: String, name: String, register: Int): Method {
        val code = MutableMethodImplementation(original.implementation!!)
        val existing = (code.instructions.firstOrNull() as? ReferenceInstruction)?.reference as? MethodReference
        if (existing?.definingClass != owner || existing.name != name) {
            code.addInstruction(0, BuilderInstruction3rc(Opcode.INVOKE_STATIC_RANGE, register, 1,
                ImmutableMethodReference(owner, name, listOf("Ljava/lang/String;"), "Ljava/lang/String;")))
            code.addInstruction(1, BuilderInstruction11x(Opcode.MOVE_RESULT_OBJECT, register))
        }
        return method(original, code)
    }
}
