package tv.localbox.vpn

import org.json.JSONObject
import java.io.*
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.CancellationException

object ClientDownload {
    private const val MAX_SIZE=4L*1024*1024*1024
    data class Plan(val url: String,val revision: String,val size: Long=0,val sha256: String?=null)
    fun allowedUrl(value: String): Boolean = try {
        val uri=URI(value);val host=uri.host.orEmpty().lowercase()
        uri.scheme=="https" && uri.userInfo==null && (uri.port==-1 || uri.port==443) &&
            (host in setOf("github.com","api.github.com","codeload.github.com","raw.githubusercontent.com") || host.endsWith(".githubusercontent.com"))
    } catch(_: Exception) { false }
    private fun open(url: String): HttpURLConnection {
        var current=url
        repeat(7) {
            require(allowedUrl(current)) { "GitHub вернул неподдерживаемый адрес загрузки" }
            val conn=URL(current).openConnection() as HttpURLConnection
            conn.connectTimeout=20000;conn.readTimeout=20000;conn.instanceFollowRedirects=false
            conn.setRequestProperty("User-Agent","LocalBox-Android")
            conn.setRequestProperty("Accept-Encoding","identity")
            val status=conn.responseCode
            if(status in setOf(301,302,303,307,308)) {
                val next=conn.getHeaderField("Location") ?: error("Пустой редирект GitHub")
                conn.disconnect();current=URI(current).resolve(next).toString()
            } else {
                if(status!=200) {
                    val message=if(status==403 || status==429) "GitHub ограничил запросы. Попробуйте позже" else "GitHub: HTTP $status"
                    conn.disconnect();throw IOException(message)
                }
                return conn
            }
        }
        error("Слишком много перенаправлений GitHub")
    }
    private fun text(url: String): String {
        val conn=open(url)
        try { return conn.inputStream.use { input -> ByteArrayOutputStream().apply { ClientImport.copyLimited(input,this,2L*1024*1024) }.toString("UTF-8") } }
        finally { conn.disconnect() }
    }
    fun plan(source: ClientCatalog.Source): Plan = when(source) {
        ClientCatalog.Source.ENGLISH -> {
            val commit=JSONObject(text("https://api.github.com/repos/DdejjCAT/jackbox.tv/commits/main")).getString("sha")
            require(commit.matches(Regex("[a-f0-9]{40}"))) { "Некорректная версия репозитория клиента" }
            Plan("https://codeload.github.com/DdejjCAT/jackbox.tv/zip/$commit",commit)
        }
        ClientCatalog.Source.RUSSIAN -> {
            val release=JSONObject(text("https://api.github.com/repos/zAsQwE/localbox/releases/latest"))
            require(!release.optBoolean("draft") && !release.optBoolean("prerelease")) { "Нет стабильного Release LocalBox" }
            val assets=release.getJSONArray("assets")
            val asset=(0 until assets.length()).map { assets.getJSONObject(it) }.singleOrNull { it.optString("name")=="client-ru.zip" }
                ?: error("В последнем Release нет client-ru.zip")
            var digest=asset.optString("digest").removePrefix("sha256:")
            if(!digest.matches(Regex("[a-fA-F0-9]{64}"))) {
                val sums=(0 until assets.length()).map { assets.getJSONObject(it) }.singleOrNull { it.optString("name")=="SHA256SUMS" }
                    ?: error("В Release нет SHA-256 русского клиента")
                digest=Regex("(?m)^([a-fA-F0-9]{64})\\s+\\*?client-ru\\.zip\\s*$").find(text(sums.getString("browser_download_url")))?.groupValues?.get(1)
                    ?: error("В SHA256SUMS нет client-ru.zip")
            }
            val url=asset.getString("browser_download_url")
            require(url.startsWith("https://github.com/zAsQwE/localbox/releases/download/") && url.endsWith("/client-ru.zip"))
            Plan(url,"${release.getString("tag_name")}:${asset.getLong("id")}",asset.getLong("size"),digest.lowercase())
        }
    }
    fun verifyPlan(plan: Plan) {
        require(plan.size in 0..MAX_SIZE) { "Архив клиента слишком большой" }
        require(plan.sha256==null || plan.sha256.matches(Regex("[a-f0-9]{64}"))) { "Неверная SHA-256 архива" }
    }
    fun copy(input: InputStream,output: OutputStream,plan: Plan,cancelled: ()->Boolean={false},progress: (Long,Long)->Unit={_,_->},limit: Long=MAX_SIZE): Long {
        verifyPlan(plan)
        val sha=MessageDigest.getInstance("SHA-256");var size=0L;val buffer=ByteArray(128*1024)
        val started=System.nanoTime();var reported=0L
        while(true) {
            checkCancelled(cancelled)
            val count=input.read(buffer);if(count<0) break
            size+=count;require(size<=limit) { "Недостаточно свободного места для архива клиента" };require(size<=MAX_SIZE && (plan.size==0L || size<=plan.size)) { "Размер загрузки не соответствует Release" }
            output.write(buffer,0,count);sha.update(buffer,0,count)
            val now=System.nanoTime()
            if(now-reported>=500_000_000L) { progress(size,plan.size);reported=now }
            if(now-started>30L*60*1_000_000_000L) throw IOException("Превышено время загрузки клиента")
        }
        checkCancelled(cancelled)
        require(size>0 && (plan.size==0L || size==plan.size)) { "Архив клиента скачан не полностью" }
        val digest=sha.digest().joinToString("") { "%02x".format(it) }
        require(plan.sha256==null || digest==plan.sha256) { "SHA-256 архива не совпала. Прежний клиент сохранён" }
        progress(size,plan.size);return size
    }
    fun download(plan: Plan,file: File,cancelled: ()->Boolean,progress: (Long,Long)->Unit) {
        verifyPlan(plan)
        var failure: IOException?=null
        for(attempt in 1..3) {
            checkCancelled(cancelled);file.delete()
            val conn=try { open(plan.url) } catch(e: IOException) { failure=e;continue }
            try {
                val length=conn.getHeaderFieldLong("Content-Length",0L)
                require(length<=MAX_SIZE && (plan.size==0L || length<=0 || length==plan.size)) { "GitHub вернул другой размер архива" }
                val expected=if(plan.size==0L && length>0) plan.copy(size=length) else plan
                val budget=(file.parentFile!!.usableSpace-128L*1024*1024).coerceAtMost(MAX_SIZE)
                require(budget>0 && expected.size<=budget) { "Недостаточно свободного места для архива клиента" }
                conn.inputStream.use { input -> file.outputStream().buffered().use { copy(input,it,expected,cancelled,progress,budget) } }
                return
            } catch(e: IOException) { failure=e }
            finally { conn.disconnect() }
        }
        file.delete();throw IOException("Не удалось скачать клиент за 3 попытки: ${failure?.message}",failure)
    }
    fun checkCancelled(cancelled: ()->Boolean) { if(cancelled() || Thread.currentThread().isInterrupted) throw CancellationException("Загрузка отменена") }
}
