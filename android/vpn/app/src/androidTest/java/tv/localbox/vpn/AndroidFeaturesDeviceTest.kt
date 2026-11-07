package tv.localbox.vpn

import android.content.Intent
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicReference

class AndroidFeaturesDeviceTest {
    private val instrumentation=InstrumentationRegistry.getInstrumentation()
    private val context=instrumentation.targetContext
    private fun onMain(action: ()->Unit) = instrumentation.runOnMainSync(action)
    private fun waitFor(message: String,condition: ()->Boolean) {
        val deadline=System.currentTimeMillis()+20000
        while(!condition()) { if(System.currentTimeMillis()>deadline) fail(message);Thread.sleep(50) }
    }
    @Test fun testSearchBothLabelsAndPackages() {
        val activity=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val dialog=AtomicReference<AlertDialog>()
        val picked=AtomicReference<InstalledApps.App>()
        try {
            onMain { dialog.set(InstalledApps.show(activity,"Test") { picked.set(it) }) }
            fun count(): Int { var result=0;onMain { result=dialog.get().findViewById<ListView>(R.id.installedList)!!.adapter.count };return result }
            waitFor("installed apps were not loaded") { count()>0 }
            var app: InstalledApps.App?=null
            onMain { app=dialog.get().findViewById<ListView>(R.id.installedList)!!.adapter.getItem(0) as InstalledApps.App }
            onMain { dialog.get().findViewById<EditText>(R.id.installedSearch)!!.setText("__no_such_localbox_app__") };assertEquals(0,count())
            onMain { dialog.get().findViewById<EditText>(R.id.installedSearch)!!.setText(app!!.label.uppercase()) };assertTrue(count()>0)
            onMain {
                dialog.get().findViewById<EditText>(R.id.installedSearch)!!.setText(app!!.packageName.uppercase())
                val list=dialog.get().findViewById<ListView>(R.id.installedList)!!
                assertTrue(list.adapter.count>0)
                list.performItemClick(list.getChildAt(0),0,list.adapter.getItemId(0))
            }
            assertEquals(app!!.packageName,picked.get().packageName)
        } finally { onMain { dialog.get()?.dismiss();activity.finish() } }
    }
    @Test fun testStartupDimmingRealOfflineSpeechAndVpnStop() {
        val prefs=context.getSharedPreferences("localbox",0)
        prefs.edit().putInt("gamePort",5557).putInt("webPort",8080).putBoolean("httpsEnabled",false).putBoolean("ttsEnabled",true).putBoolean("useVpn",false).commit()
        val activity=instrumentation.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        try {
            onMain {
                val button=activity.findViewById<Button>(R.id.serverToggle)
                assertTrue(button.isEnabled);button.performClick()
                assertFalse(button.isEnabled);assertTrue(button.alpha<0.6f);assertEquals("Запускается…",button.text.toString())
            }
            waitFor("server start: ${ServerService.error}") { ServerService.running && !ServerService.busy }
            waitFor("server button did not return to enabled state") { var enabled=false;onMain { enabled=activity.findViewById<Button>(R.id.serverToggle).isEnabled };enabled }
            waitFor("Android TTS initialization timed out") { !JSONObject(NativeServer.status()).getJSONObject("tts").getString("message").contains("Подготовка") && !JSONObject(NativeServer.status()).getJSONObject("tts").getString("message").startsWith("Проверяю") }
            val tts=JSONObject(NativeServer.status()).getJSONObject("tts")
            val connection=URL("http://127.0.0.1:5557/tts/generate").openConnection() as HttpURLConnection
            connection.requestMethod="POST";connection.doOutput=true;connection.readTimeout=50000;connection.setRequestProperty("Content-Type","application/json")
            connection.outputStream.use { it.write("""{"text":"Hello! This is LocalBox offline speech.","rate":"110%"}""".toByteArray()) }
            if(tts.getBoolean("ready")) {
                assertEquals(200,connection.responseCode)
                val result=JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                assertTrue(result.getBoolean("success"))
                val wav=URL(result.getString("url")).readBytes()
                assertTrue(wav.size>44);assertEquals("RIFF",String(wav,0,4));assertEquals("WAVE",String(wav,8,4))
                assertTrue(wav.drop(44).any { it!=0.toByte() })
                android.util.Log.i("LocalBoxFeaturesTest","PASS: actual Android offline voice created ${wav.size} byte WAV through HTTP API")
            } else {
                assertEquals(503,connection.responseCode)
                android.util.Log.i("LocalBoxFeaturesTest","PASS: unavailable TTS reports ${tts.getString("message")}; synthesis not tested on this device")
            }
            connection.disconnect()
            // Grant only the disposable emulator app's VPN app-op from the test shell.
            instrumentation.uiAutomation.executeShellCommand("appops set ${context.packageName} ACTIVATE_VPN allow").use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes() }
            prefs.edit().putString("gamePackage",context.packageName).commit()
            onMain {
                activity.findViewById<CheckBox>(R.id.useVpn).isChecked=true
                activity.findViewById<Button>(R.id.vpnToggle).performClick()
            }
            waitFor("VPN did not start") { LocalVpnService.active }
            onMain { activity.findViewById<CheckBox>(R.id.useVpn).isChecked=false }
            waitFor("VPN did not stop after unchecking") { !LocalVpnService.active }
            assertTrue(ServerService.running);assertFalse(prefs.getBoolean("useVpn",true))
            prefs.edit().putBoolean("ttsEnabled",false).commit()
            waitFor("TTS did not turn off") { !JSONObject(NativeServer.status()).getJSONObject("tts").getBoolean("ready") }
            android.util.Log.i("LocalBoxFeaturesTest","PASS: immediate dimming, real VPN started/stopped, game server remained active, TTS disabled live")
        } finally {
            onMain { LocalVpnService.requestStop(context);context.stopService(Intent(context,ServerService::class.java));activity.finish() }
            waitFor("server did not stop") { !ServerService.running && !ServerService.busy }
        }
    }
}
