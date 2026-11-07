package tv.localbox.vpn

import android.content.Intent
import android.webkit.WebView
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.*
import java.net.*
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.zip.*
import javax.net.ssl.*

class ClientFlowDeviceTest {
    @Test fun testRealGitHubArchivePlans() {
        val en=ClientDownload.plan(ClientCatalog.Source.ENGLISH)
        assertTrue(en.url.startsWith("https://codeload.github.com/DdejjCAT/jackbox.tv/zip/"))
        assertEquals(40,en.revision.length)
        val ru=ClientDownload.plan(ClientCatalog.Source.RUSSIAN)
        assertTrue(ru.url.endsWith("/client-ru.zip"));assertTrue(ru.size>0);assertEquals(64,ru.sha256!!.length)
    }
    @Test fun testBothClientsHttpPlayerHttpsAndQrDismissal() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        val engine=ClientCatalog.engine(context)
        val html="""<!doctype html><body>loading<script>fetch('/localbox/status').then(r=>r.json()).then(r=>document.body.textContent='LOCALBOX_HTTP_OK '+location.protocol)</script></body>"""
        fun zip(): InputStream {
            val output=ByteArrayOutputStream()
            ZipOutputStream(output).use { z -> for((name,contents) in listOf("bundle/index.html" to html,"bundle/main/fixture.js" to "fixture")) { z.putNextEntry(ZipEntry(name));z.write(contents.toByteArray());z.closeEntry() } }
            return output.toByteArray().inputStream()
        }
        ClientImport.install(zip(),engine,"client",requireMain=true)
        ClientImport.install(zip(),engine,"client-ru",requireMain=true)
        ClientCatalog.activate(context,ClientCatalog.Source.RUSSIAN)
        assertTrue(ClientCatalog.ready(context,ClientCatalog.Source.ENGLISH))
        val prefs=context.getSharedPreferences("localbox",0)
        prefs.edit().putInt("gamePort",5557).putInt("webPort",8080).putInt("httpsPort",8443).putBoolean("httpsEnabled",true).putBoolean("showQr",true).remove("dismissedQr").commit()
        File(engine,"web-tls.json").writeText("""{"enabled":true,"port":8443}""")
        context.assets.open("games.json").use { input -> File(engine,"games.json").outputStream().use { input.copyTo(it) } }
        NativeServer.load();assertNull(NativeServer.start(engine.absolutePath,"127.0.0.1",5557,8080));ServerService.running=true
        var player: PlayerActivity?=null
        var host: Socket?=null
        try {
            val connection=URL("http://127.0.0.1:5557/api/v2/rooms").openConnection() as HttpURLConnection
            connection.requestMethod="POST";connection.doOutput=true;connection.setRequestProperty("Content-Type","application/json")
            connection.outputStream.use { it.write("""{"userId":"android-fixture-host","appTag":"test"}""".toByteArray()) }
            val body=JSONObject(connection.inputStream.bufferedReader().use { it.readText() }).getJSONObject("body");connection.disconnect()
            host=Socket("127.0.0.1",5557)
            host.getOutputStream().write(("GET /api/v2/rooms/${body.getString("code")}/play?role=host&host-token=${body.getString("token")}&user-id=android-fixture-host HTTP/1.1\r\nHost: 127.0.0.1:5557\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").toByteArray())
            val reader=host.getInputStream().bufferedReader();assertTrue(reader.readLine().contains("101"));while(reader.readLine().isNotEmpty()) { }
            var room=RoomQr.room();val deadline=System.currentTimeMillis()+5000
            while(room==null && System.currentTimeMillis()<deadline) { Thread.sleep(50);room=RoomQr.room() }
            assertTrue(RoomQr.visible(context,room));RoomQr.dismiss(context,room!!);assertFalse(RoomQr.visible(context,room))
            prefs.edit().remove("dismissedQr").commit();assertTrue(RoomQr.visible(context,room))
            assertTrue(room.getString("joinUrl").startsWith("https://127.0.0.1:8443/"))
            assertEquals(480,RoomQr.bitmap(room.getString("joinUrl")).width)
            val trust=KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null);setCertificateEntry("fixture",File(engine,"tls/server-cert.pem").inputStream().use { CertificateFactory.getInstance("X.509").generateCertificate(it) }) }
            val tm=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(trust) }
            val ssl=SSLContext.getInstance("TLS").apply { init(null,tm.trustManagers,null) }
            val tls=URL("https://127.0.0.1:8443/localbox/status").openConnection() as HttpsURLConnection
            tls.sslSocketFactory=ssl.socketFactory
            assertTrue(JSONObject(tls.inputStream.bufferedReader().use { it.readText() }).getBoolean("running"));tls.disconnect()
            player=instrumentation.startActivitySync(Intent(context,PlayerActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as PlayerActivity
            var text=""
            val pageDeadline=System.currentTimeMillis()+15000
            while(!text.contains("LOCALBOX_HTTP_OK") && System.currentTimeMillis()<pageDeadline) {
                val latch=CountDownLatch(1)
                instrumentation.runOnMainSync { player.findViewById<WebView>(R.id.playerWeb).evaluateJavascript("document.body.textContent") { value -> text=value;latch.countDown() } }
                assertTrue(latch.await(3,TimeUnit.SECONDS));if(!text.contains("LOCALBOX_HTTP_OK")) Thread.sleep(150)
            }
            assertTrue(text,text.contains("LOCALBOX_HTTP_OK http:"))
            android.util.Log.i("LocalBoxClientTest","PASS: EN+RU imports, selected client, HTTP WebView fetch, real HTTPS with own certificate, QR dismissal")
        } finally {
            player?.let { p -> instrumentation.runOnMainSync { p.finish() } }
            host?.close();ServerService.running=false;NativeServer.stop()
        }
    }
}
