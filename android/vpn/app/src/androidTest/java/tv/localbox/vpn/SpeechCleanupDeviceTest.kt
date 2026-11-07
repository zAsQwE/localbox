package tv.localbox.vpn

import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.net.HttpURLConnection
import java.net.Socket
import java.net.URL

class SpeechCleanupDeviceTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private val base="http://127.0.0.1:5557"
    private fun waitFor(message: String,condition: ()->Boolean) {
        val deadline=System.currentTimeMillis()+20000
        while(!condition()) { if(System.currentTimeMillis()>deadline) fail(message);Thread.sleep(50) }
    }
    private fun post(path: String,body: String): JSONObject {
        val connection=URL(base+path).openConnection() as HttpURLConnection
        try {
            connection.requestMethod="POST";connection.doOutput=true;connection.readTimeout=50000
            connection.setRequestProperty("Content-Type","application/json")
            connection.outputStream.use { it.write(body.toByteArray()) }
            assertEquals(200,connection.responseCode)
            return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
        } finally { connection.disconnect() }
    }
    private fun status(url: String): Int {
        val connection=URL(url).openConnection() as HttpURLConnection
        return try { connection.responseCode } finally { connection.disconnect() }
    }
    private fun send(socket: Socket,opcode: String) {
        val data="""{"opcode":"$opcode","params":{}}""".toByteArray()
        assertTrue(data.size<126)
        // A real masked client WebSocket frame, independent of production JNI.
        socket.getOutputStream().apply {
            write(byteArrayOf(0x81.toByte(),(0x80 or data.size).toByte(),1,2,3,4))
            write(ByteArray(data.size) { (data[it].toInt() xor (it%4+1)).toByte() });flush()
        }
    }
    @Test fun testOfflineSpeechRemovedAfterPartyAndHostExit() {
        val engine=ClientCatalog.engine(context)
        File(engine,"web-tls.json").writeText("""{"enabled":false,"port":8443}""")
        context.assets.open("games.json").use { input -> File(engine,"games.json").outputStream().use { input.copyTo(it) } }
        context.getSharedPreferences("localbox",0).edit().putBoolean("ttsEnabled",true).commit()
        NativeServer.load();assertNull(NativeServer.start(engine.absolutePath,"127.0.0.1",5557,8080))
        val speech=ServerSpeech(context)
        var host: Socket?=null
        try {
            instrumentation.runOnMainSync { speech.start() }
            waitFor("Offline Android voice unavailable") { JSONObject(NativeServer.status()).getJSONObject("tts").getBoolean("ready") }
            val body=post("/api/v2/rooms","""{"userId":"tts-cleanup-host","appTag":"rapbattle"}""").getJSONObject("body")
            val socket=Socket("127.0.0.1",5557);host=socket
            socket.soTimeout=5000
            socket.getOutputStream().write(("GET /api/v2/rooms/${body.getString("code")}/play?role=host&host-token=${body.getString("token")}&user-id=tts-cleanup-host HTTP/1.1\r\nHost: 127.0.0.1:5557\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").toByteArray())
            val reader=socket.getInputStream().bufferedReader();assertTrue(reader.readLine().contains("101"));while(reader.readLine().isNotEmpty()) { }
            waitFor("Host not connected") { !JSONObject(NativeServer.status()).isNull("room") }
            fun generate(): String {
                val result=post("/tts/generate","""{"text":"Hello! This is a LocalBox party recording."}""")
                assertTrue(result.getBoolean("success"))
                val url=result.getString("url");val wav=URL(url).readBytes()
                assertTrue(wav.size>44);assertEquals("RIFF",String(wav,0,4));assertEquals("WAVE",String(wav,8,4))
                assertTrue(wav.drop(44).any { it!=0.toByte() })
                return url
            }
            val first=generate()
            send(socket,"game/ended")
            waitFor("Finished party WAV remains accessible") { status(first)==404 }
            send(socket,"game/started")
            waitFor("Replay did not start") { !JSONObject(NativeServer.status()).getJSONObject("room").getBoolean("qrVisible") }
            val replay=generate();assertNotEquals(first,replay);assertEquals(404,status(first))
            socket.close();host=null
            waitFor("Host exit left replay WAV") { status(replay)==404 }
            assertTrue(File(engine,"storage/tts").listFiles().orEmpty().isEmpty())
            android.util.Log.i("LocalBoxSpeechCleanupTest","PASS: real offline WAV, game/ended cleanup, isolated replay, host exit removed all party files")
        } finally {
            host?.close();instrumentation.runOnMainSync { speech.stop() };NativeServer.stop()
        }
    }
}
