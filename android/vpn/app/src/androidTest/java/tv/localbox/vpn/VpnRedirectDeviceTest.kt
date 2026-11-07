package tv.localbox.vpn

import android.content.Intent
import android.util.Base64
import android.widget.Button
import android.widget.CheckBox
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.Socket
import java.net.URL
import kotlin.random.Random

/** The VPN redirect end to end: this app is the "game", its traffic goes through the TUN. */
class VpnRedirectDeviceTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private fun onMain(action: () -> Unit) = instrumentation.runOnMainSync(action)
    private fun waitFor(message: String, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 20000
        while (!condition()) { if (System.currentTimeMillis() > deadline) fail(message); Thread.sleep(50) }
    }
    private fun log(text: String) = android.util.Log.i("LocalBoxVpnTest", text)

    private fun post(url: String, body: String): Pair<Int, String> {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = "POST"; c.doOutput = true; c.connectTimeout = 8000; c.readTimeout = 8000
        c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(body.toByteArray()) }
        val code = c.responseCode
        val text = (if (code < 400) c.inputStream else c.errorStream).bufferedReader().use { it.readText() }
        c.disconnect()
        return code to text
    }

    @Test fun testJackboxHostsAreRedirectedToTheLocalServer() {
        val prefs = context.getSharedPreferences("localbox", 0)
        prefs.edit().putInt("gamePort", 5557).putInt("webPort", 8080).putBoolean("httpsEnabled", false)
            .putBoolean("ttsEnabled", false).putBoolean("useVpn", false).commit()
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        try {
            onMain { activity.findViewById<Button>(R.id.serverToggle).performClick() }
            waitFor("server start: ${ServerService.error}") { ServerService.running && !ServerService.busy }
            instrumentation.uiAutomation.executeShellCommand("appops set ${context.packageName} ACTIVATE_VPN allow")
                .use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes() }
            prefs.edit().putString("gamePackage", context.packageName).commit()
            onMain {
                activity.findViewById<CheckBox>(R.id.useVpn).isChecked = true
                activity.findViewById<Button>(R.id.vpnToggle).performClick()
            }
            waitFor("VPN did not start") { LocalVpnService.active }
            Thread.sleep(1500) // let Android switch this app's network to the VPN

            val resolved = InetAddress.getByName("ecast.jackboxgames.com").hostAddress
            log("DNS ecast.jackboxgames.com -> $resolved")
            assertEquals("10.111.0.3", resolved)

            // REST over plain HTTP: as a game whose address was not patched would do.
            val (code, text) = post("http://ecast.jackboxgames.com/api/v2/rooms",
                """{"userId":"vpn-host","appTag":"quiplash3","appId":"37c1627d-4b01-4f45-b95f-80197cd4403c"}""")
            log("POST rooms via VPN -> $code $text")
            assertEquals(200, code)
            val body = JSONObject(text).getJSONObject("body")
            val room = body.getString("code"); val token = body.getString("token")

            // Several requests in a row (keep-alive / new connections).
            repeat(5) {
                val c = URL("http://ecast.jackboxgames.com/api/v2/rooms/$room").openConnection() as HttpURLConnection
                c.connectTimeout = 8000; c.readTimeout = 8000
                assertEquals(200, c.responseCode); c.inputStream.readBytes(); c.disconnect()
            }

            // Large response: many segments must arrive in order without retransmission.
            val big = "x".repeat(400_000)
            val (echoCode, echo) = post("http://ecast.jackboxgames.com/tts/generate", """{"text":"$big"}""")
            log("large POST via VPN -> $echoCode (${echo.length} bytes back)")

            // WebSocket (host), plain ws:// on port 80.
            Socket("ecast.jackboxgames.com", 80).use { s ->
                s.soTimeout = 8000
                val key = Base64.encodeToString(Random.nextBytes(16), Base64.NO_WRAP)
                s.getOutputStream().write(("GET /api/v2/rooms/$room/play?role=host&name=x&format=json&user-id=vpn-host&host-token=$token HTTP/1.1\r\n" +
                    "Host: ecast.jackboxgames.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
                    "Sec-WebSocket-Key: $key\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: ecast-v0\r\n\r\n").toByteArray())
                val reader = BufferedReader(InputStreamReader(s.getInputStream()))
                val status = reader.readLine()
                log("WS handshake via VPN -> $status")
                assertTrue(status, status.contains("101"))
            }

            // HTTPS: TLS is passed through unchanged, so the plain-HTTP game port cannot answer it.
            val https = runCatching {
                val c = URL("https://ecast.jackboxgames.com/api/v2/rooms/$room").openConnection() as HttpURLConnection
                c.connectTimeout = 5000; c.readTimeout = 5000; c.responseCode
            }
            log("HTTPS via VPN -> ${https.exceptionOrNull() ?: https.getOrNull()}")
            assertTrue(https.isFailure)
            waitFor("TLS was not reported to the user") { LocalVpnService.problem == LocalVpnService.TLS_PROBLEM }
            assertEquals(443, LocalVpnService.problemPort)

            // Server closes the connection (HTTP/1.0 style): the client must see EOF, not hang.
            Socket("ecast.jackboxgames.com", 80).use { s ->
                s.soTimeout = 8000
                s.getOutputStream().write("GET /api/v2/rooms/$room HTTP/1.1\r\nHost: ecast.jackboxgames.com\r\nConnection: close\r\n\r\n".toByteArray())
                val all = s.getInputStream().readBytes()   // returns only on FIN
                log("Connection: close via VPN -> ${all.size} bytes, EOF received: ${String(all).lineSequence().first()}")
                assertTrue(String(all).startsWith("HTTP/1.1 ")) // the room may be gone after the host socket closed
            }
            log("PASS: VPN DNS + REST + WS redirect")
        } finally {
            onMain { LocalVpnService.requestStop(context); context.stopService(Intent(context, ServerService::class.java)); activity.finish() }
            waitFor("server did not stop") { !ServerService.running && !ServerService.busy }
        }
    }
}
