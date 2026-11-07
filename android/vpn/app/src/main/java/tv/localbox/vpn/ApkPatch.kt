package tv.localbox.vpn

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import com.android.apksig.ApkSigner
import com.android.apksig.ApkVerifier
import org.json.JSONObject
import java.io.*
import java.math.BigInteger
import java.security.*
import java.security.cert.X509Certificate
import java.util.*
import java.util.zip.*
import javax.security.auth.x500.X500Principal

object ApkPatch {
    private const val KEY_ALIAS = "localbox-game-patches-v1"
    private const val MAX_ENTRY = 256L*1024*1024
    private const val MAX_TOTAL = 4L*1024*1024*1024
    data class Analysis(val dex: Map<String,Map<String,NetworkDex.Match>>,val reason: String) {
        private val incomplete get()=dex.values.any { it.values.any { m -> m.ecast } } && !ecast
        val supported get()=!incomplete && dex.values.any { it.isNotEmpty() }
        val blobcast get()=dex.values.any { group -> group.values.any { it.blobcast } }
        val ecast get()=dex.values.any { group -> group.values.any { it.ecastSocket } } && dex.values.any { group -> group.values.any { it.ecastHttp } }
    }
    fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    fun analyze(files: List<File>): Analysis {
        val found=files.associate { file -> file.name to ZipFile(file).use { zip ->
            zip.entries().toList().filter { it.name.matches(Regex("classes(?:[2-9]|[1-9][0-9]+)?\\.dex")) }.mapNotNull { entry ->
                val match=NetworkDex.inspect(readEntry(zip,entry.name,64L*1024*1024))
                if(match.supported) entry.name to match else null
            }.toMap()
        } }
        val bc=found.values.any { group -> group.values.any { it.blobcast } }
        val socket=found.values.any { group -> group.values.any { it.ecastSocket } }
        val http=found.values.any { group -> group.values.any { it.ecastHttp } }
        val ecast=socket && http
        val supported=found.values.any { it.isNotEmpty() }
        return Analysis(found,when {
            ecast -> "Обнаружен совместимый Ecast-мост Scaleform. REST и WebSocket будут направлены на встроенный сервер; VPN не нужен"
            socket || http -> "Найден только один совместимый Ecast-мост: для патча нужны REST и WebSocket. Выберите установленную игру со всеми split APK; неизвестный сетевой код не изменён"
            bc -> "Обнаружен совместимый Java Blobcast-клиент. Можно создать копию для LocalBox"
            supported -> "Обнаружены адреса Ecast/Blobcast в Java-коде. Автопатч HTTP/WS доступен, работа конкретной игры требует проверки"
            else -> "Совместимый Java-клиент не найден. Для Unity, IL2CPP и адресов внутри нативных библиотек нужен отдельный профиль; этот APK не изменён"
        })
    }
    fun supported(context: Context,file: File): Boolean = try {
        context.packageManager.getPackageArchiveInfo(file.absolutePath,0)!=null && analyze(listOf(file)).supported
    } catch(_: Exception) { false }

    /** Only recognized game connection settings; download, store and analytics URLs stay intact. */
    fun patchConfig(original: ByteArray,port: Int): ByteArray? {
        val config=try { JSONObject(original.toString(Charsets.UTF_8)) } catch(_: Exception) { return null }
        var changed=false
        for(key in listOf("serverUrl","serverURL","blobcastUrl","ecastUrl")) {
            val value=config.optString(key)
            val scheme=if(value.contains("://")) value.substringBefore("://").lowercase() else ""
            if(scheme !in listOf("", "http", "https", "ws", "wss")) continue
            val host=value.substringAfter("://",value).substringBefore('/')
            if(GameEndpoints.isAuthority(host)) {
                config.put(key,when(scheme) {
                    "http", "https" -> "http://127.0.0.1:$port"
                    "ws", "wss" -> "ws://127.0.0.1:$port"
                    else -> "127.0.0.1:$port"
                });changed=true
            }
        }
        if(changed) for(key in listOf("protocol", "scheme")) {
            when(config.optString(key).lowercase()) {
                "https" -> config.put(key,"http")
                "wss" -> config.put(key,"ws")
            }
        }
        return if(changed) config.toString(2).toByteArray() else null
    }

    /**
     * [separate]: the copy gets its own package name (`….localbox`) and a "· LocalBox" label, so it
     * installs next to the original game instead of conflicting with its signature.
     */
    fun create(context: Context,input: ApkSelection,port: Int,separate: Boolean=true,progress: (String)->Unit = {}): ApkResult {
        require(port in 1024..65535)
        val analysis=analyze(input.files);require(analysis.supported) { analysis.reason }
        val manifests=input.files.map { file -> ZipFile(file).use { BinaryManifest.info(readEntry(it,"AndroidManifest.xml")) } }
        val base=manifests.first()
        require(base.split.isEmpty()) { "Выбран отдельный split APK. Выберите установленную игру целиком" }
        require(!base.requiresSplits || input.files.size>1) { "Этой игре нужны дополнительные APK. Выберите установленную игру целиком" }
        require(manifests.all { it.packageName==input.packageName && it.version==base.version }) { "Части APK относятся к разным приложениям или версиям" }
        require(manifests.drop(1).all { it.split.isNotEmpty() } && manifests.map { it.split }.distinct().size==manifests.size) { "В наборе повторяются APK или отсутствуют имена split-частей" }
        val target=if(separate) BinaryManifest.copyPackage(input.packageName) else input.packageName
        val label=if(separate && !input.label.endsWith("LocalBox")) "${input.label} · LocalBox" else null
        val folder=File(context.filesDir,"patched").apply { mkdirs() }
        require(folder.usableSpace>input.files.sumOf { it.length() }*3+64L*1024*1024) { "Недостаточно места для копии игры" }
        val stage=File(folder,"new").apply { deleteRecursively();mkdirs() }
        val destination=File(folder,"current");val previous=File(folder,"previous")
        try {
            val key=signingKey()
            for((index,file) in input.files.withIndex()) {
                progress("Обрабатываю APK ${index+1}/${input.files.size}…")
                val unsigned=File(stage,"unsigned.apk");val signed=File(stage,file.name)
                ZipFile(file).use { zip ->
                    val seen=HashSet<String>();var total=0L
                    val counter=CountedOutput(unsigned.outputStream().buffered())
                    ZipOutputStream(counter).use { output ->
                        for(entry in zip.entries()) {
                            val name=entry.name;require(seen.add(name)) { "В APK повторяется файл: $name" }
                            if(oldSignature(name)) continue
                            val replacement=when {
                                name=="AndroidManifest.xml" -> {
                                    val manifest=readEntry(zip,name).let { if(index==0) BinaryManifest.allowLocalHttp(it) else it }
                                    if(target!=input.packageName) BinaryManifest.retarget(manifest,target,if(index==0) label else null)
                                    else if(index==0) manifest else null
                                }
                                name=="resources.arsc" && target!=input.packageName -> BinaryManifest.retargetResources(readEntry(zip,name),input.packageName,target)
                                analysis.dex[file.name]?.containsKey(name)==true -> NetworkDex.patch(readEntry(zip,name,64L*1024*1024),port)
                                name.startsWith("assets/") && (name.endsWith(".jet") || name.endsWith(".json")) && entry.size in 1..(1024*1024) -> patchConfig(readEntry(zip,name),port)
                                else -> null
                            }
                            val stored=entry.method==ZipEntry.STORED || (name.startsWith("lib/") && name.endsWith(".so"))
                            val item=ZipEntry(name).apply {
                                time=315532800000L
                                if(stored) {
                                    method=ZipEntry.STORED;size=replacement?.size?.toLong() ?: entry.size
                                    crc=if(replacement==null) entry.crc else CRC32().apply { update(replacement) }.value
                                    require(size>=0 && crc>=0)
                                    val alignment=if(name.startsWith("lib/") && name.endsWith(".so")) 16384 else 4
                                    val padding=((alignment-(counter.count+30+name.toByteArray(Charsets.UTF_8).size+4)%alignment)%alignment).toInt()
                                    extra=ByteArray(4+padding).apply { this[0]=0xfe.toByte();this[1]=0xca.toByte();this[2]=padding.toByte();this[3]=(padding shr 8).toByte() }
                                }
                            }
                            output.putNextEntry(item)
                            val limit=minOf(MAX_TOTAL-total,MAX_ENTRY)
                            total+=if(replacement!=null) { require(replacement.size<=limit);output.write(replacement);replacement.size.toLong() }
                                else zip.getInputStream(entry).use { ClientImport.copyLimited(it,output,limit) }
                            output.closeEntry()
                        }
                    }
                }
                progress("Подписываю APK ${index+1}/${input.files.size}…")
                val signer=ApkSigner.SignerConfig.Builder("LocalBox",key.first,listOf(key.second)).build()
                ApkSigner.Builder(listOf(signer)).setInputApk(unsigned).setOutputApk(signed).setMinSdkVersion(24)
                    .setV1SigningEnabled(true).setV2SigningEnabled(true).setV3SigningEnabled(false).setV4SigningEnabled(false).build().sign()
                val result=ApkVerifier.Builder(signed).setMinCheckedPlatformVersion(24).build().verify()
                check(result.isVerified) { "Не прошла проверка подписи APK: ${result.errors}" }
                unsigned.delete()
            }
            ApkResult(stage,input.files.map { File(stage,it.name) },target,label ?: input.label,port,input.packageName).saveMetadata()
            previous.deleteRecursively()
            if(destination.exists()) check(destination.renameTo(previous)) { "Не удалось заменить предыдущий результат" }
            if(!stage.renameTo(destination)) { previous.renameTo(destination);error("Не удалось сохранить копию") }
            previous.deleteRecursively()
            return ApkResult.read(destination) ?: error("Результат не найден")
        } finally { stage.deleteRecursively() }
    }

    private fun signingKey(): Pair<PrivateKey, X509Certificate> {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias(KEY_ALIAS)) {
            val end = Calendar.getInstance().apply { add(Calendar.YEAR, 30) }.time
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                    .setKeySize(2048).setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                    .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                    .setCertificateSubject(X500Principal("CN=LocalBox APK patches"))
                    .setCertificateSerialNumber(BigInteger.ONE).setCertificateNotBefore(Date(0))
                    .setCertificateNotAfter(end).build())
            }.generateKeyPair()
        }
        return Pair(store.getKey(KEY_ALIAS, null) as PrivateKey, store.getCertificate(KEY_ALIAS) as X509Certificate)
    }

    private fun readEntry(zip: ZipFile,name: String,limit: Long=MAX_ENTRY): ByteArray = zip.getInputStream(zip.getEntry(name) ?: error("Нет файла $name")).use {
        ByteArrayOutputStream().apply { ClientImport.copyLimited(it,this,limit) }.toByteArray()
    }
    private fun oldSignature(name: String): Boolean {
        val upper=name.uppercase(Locale.ROOT)
        return upper.startsWith("META-INF/") && (upper.endsWith(".SF") || upper.endsWith(".RSA") || upper.endsWith(".DSA") || upper.endsWith(".EC") || upper=="META-INF/MANIFEST.MF" || upper.substringAfterLast('/').startsWith("SIG-"))
    }
    private class CountedOutput(private val target: OutputStream): OutputStream() {
        var count=0L;private set
        override fun write(b: Int) { target.write(b);count++ }
        override fun write(b: ByteArray,off: Int,len: Int) { target.write(b,off,len);count+=len }
        override fun flush()=target.flush()
        override fun close()=target.close()
    }
}
