package tv.localbox.vpn

import android.app.*
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import java.io.File
import java.util.concurrent.Executors

class ServerService : Service() {
    companion object {
        const val START = "tv.localbox.server.START"
        const val STOP = "tv.localbox.server.STOP"
        @Volatile var running = false
        @Volatile var busy = false
        @Volatile var error = ""
    }
    private val executor = Executors.newSingleThreadExecutor()
    private var qrOverlay: QrOverlay?=null
    private var speech: ServerSpeech?=null
    private val main=android.os.Handler(android.os.Looper.getMainLooper())
    @Volatile private var destroyed=false
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if(ClientDownloadService.active) { error="Дождитесь установки клиента";stopSelf();return START_NOT_STICKY }
        if (intent?.action != START || running || busy) return START_NOT_STICKY
        busy = true
        error = ""
        if (Build.VERSION.SDK_INT >= 26) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel("localbox-server", "Сервер LocalBox", NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, ServerService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        startForeground(2, NotificationCompat.Builder(this, "localbox-server")
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim).setContentTitle("LocalBox")
            .setContentText("Локальная игра на этом телефоне").setContentIntent(open)
            .addAction(android.R.drawable.ic_media_pause, "Остановить", stop).setOngoing(true).build())
        val host = intent.getStringExtra("host") ?: "127.0.0.1"
        val game = intent.getIntExtra("gamePort", 5555)
        val web = intent.getIntExtra("webPort", 8080)
        qrOverlay=QrOverlay(this).also { it.start() }
        executor.execute {
            try {
                val directory = File(filesDir, "engine").apply { mkdirs() }
                assets.open("games.json").use { input -> File(directory, "games.json").outputStream().use { output -> input.copyTo(output) } }
                val prefs=getSharedPreferences("localbox",0)
                File(directory,"web-tls.json").writeText(org.json.JSONObject().put("enabled",prefs.getBoolean("httpsEnabled",false)).put("port",prefs.getInt("httpsPort",8443)).toString())
                NativeServer.load()
                val failure = NativeServer.start(directory.absolutePath, host, game, web)
                if (failure != null) throw IllegalStateException(failure)
                wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "LocalBox:server").apply { acquire() }
                running = true
                main.post { if(!destroyed) speech=ServerSpeech(this).also { it.start() } }
            } catch (failure: Throwable) {
                error = failure.message ?: failure.javaClass.simpleName
                stopSelf()
            } finally { busy = false }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        destroyed=true;speech?.stop();speech=null
        qrOverlay?.stop();qrOverlay=null
        busy = true
        executor.execute {
            try { NativeServer.stop() } catch (_: Throwable) { }
            try { wakeLock?.release() } catch (_: Exception) { }
            wakeLock = null
            running = false
            busy = false
        }
        executor.shutdown()
        LocalVpnService.requestStop(this)
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
}
