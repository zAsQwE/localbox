package tv.localbox.vpn

import android.app.*
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class ClientDownloadService : Service() {
    companion object {
        const val CANCEL="tv.localbox.client.CANCEL"
        @Volatile var active=false
        @Volatile var status=""
        @Volatile var percent=-1
        @Volatile var cancelRequested=false
    }
    private val worker=Executors.newSingleThreadExecutor()
    private val cancelled=AtomicBoolean(false)
    private var lastNotification=0L
    @Volatile private var destroyed=false
    override fun onBind(intent: Intent?): IBinder?=null
    override fun onStartCommand(intent: Intent?,flags: Int,startId: Int): Int {
        if(intent?.action==CANCEL) { if(!active) { stopSelf();return START_NOT_STICKY };cancelRequested=true;cancelled.set(true);status="Останавливаю загрузку…";return START_NOT_STICKY }
        if(active) return START_NOT_STICKY
        if(ServerService.running || ServerService.busy) { status="Остановите сервер перед заменой клиента";stopSelf();return START_NOT_STICKY }
        val source=ClientCatalog.Source.entries.firstOrNull { it.directory==intent?.getStringExtra("source") }
            ?: run { stopSelf();return START_NOT_STICKY }
        active=true;cancelRequested=false;cancelled.set(false);status="Проверяю GitHub…";percent=-1
        if(Build.VERSION.SDK_INT>=26) getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("localbox-client","Загрузка клиента",NotificationManager.IMPORTANCE_LOW))
        startForeground(3,notification())
        worker.execute {
            val file=File(cacheDir,"client-download.zip.part")
            try {
                synchronized(ApkWork) {
                    val plan=ClientDownload.plan(source)
                    ClientDownload.checkCancelled { cancelled.get() }
                    ClientDownload.verifyPlan(plan)
                    require(cacheDir.usableSpace>plan.size+128L*1024*1024) { "Недостаточно места для скачивания клиента" }
                    val target=File(ClientCatalog.engine(this),source.directory)
                    val marker=File(target,".localbox-source.json")
                    val existing=try { JSONObject(marker.readText()).optString("revision") } catch(_: Exception) { "" }
                    if(existing==plan.revision && ClientCatalog.ready(this,source)) {
                        ClientCatalog.activate(this,source);report("Последняя версия клиента уже установлена")
                    } else {
                        report("Скачиваю ${source.title}…")
                        ClientDownload.download(plan,file,{cancelled.get()}) { size,total ->
                            percent=if(total>0) (size*100/total).toInt() else -1
                            report("${source.title}: ${if(percent>=0) "$percent% · " else ""}${size/(1024*1024)} МБ")
                        }
                        percent=-1;report("Распаковываю клиент…")
                        ClientImport.install(file.inputStream(),ClientCatalog.engine(this),source.directory,{cancelled.get()},{report(it)},true)
                        marker.writeText(JSONObject().put("revision",plan.revision).put("url",plan.url).toString())
                        ClientCatalog.activate(this,source)
                        report("${source.title} установлен и выбран")
                    }
                }
            } catch(_: CancellationException) { report("Загрузка отменена. Прежний клиент сохранён") }
            catch(e: Exception) { report("Не удалось установить клиент: ${e.message}") }
            finally { file.delete();active=false;percent=-1;stopSelf() }
        }
        return START_NOT_STICKY
    }
    private fun report(value: String) {
        status=value
        val now=System.currentTimeMillis()
        if(!destroyed && active && now-lastNotification>=1000) { getSystemService(NotificationManager::class.java).notify(3,notification());lastNotification=now }
    }
    private fun notification(): Notification {
        val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
        val stop=PendingIntent.getService(this,0,Intent(this,ClientDownloadService::class.java).setAction(CANCEL),PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this,"localbox-client").setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("LocalBox · веб-клиент").setContentText(status).setContentIntent(open).setOngoing(true)
            .setProgress(100,percent.coerceAtLeast(0),percent<0).addAction(android.R.drawable.ic_menu_close_clear_cancel,"Отменить",stop).build()
    }
    override fun onDestroy() { destroyed=true;cancelled.set(true);worker.shutdown();stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy() }
}
