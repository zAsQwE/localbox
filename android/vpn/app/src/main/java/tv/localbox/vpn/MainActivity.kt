package tv.localbox.vpn

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.widget.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    companion object { @Volatile var inForeground=false }
    private val handler = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val prefs by lazy { getSharedPreferences("localbox", Context.MODE_PRIVATE) }
    private var joined = ""
    private var lastQr = ""
    private var importBusy = false
    private var serverPending = false
    private var roomInfo: JSONObject?=null
    private var settingsDialog: AppSettings?=null
    private val patchedResult get() = ApkResult.current(this)
    private lateinit var feedback: TextView
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val allowInstaller = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (Build.VERSION.SDK_INT < 26 || packageManager.canRequestPackageInstalls()) installPatched()
        else feedback.text = "Установка из LocalBox не разрешена. APK можно сохранить отдельным файлом"
    }
    private val exportPatch = registerForActivityResult(ActivityResultContracts.CreateDocument("application/vnd.android.package-archive")) { uri -> exportResult(uri) }
    private val exportSplits = registerForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri -> exportResult(uri) }
    private val overlayPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        prefs.edit().putBoolean("overlayQr",Settings.canDrawOverlays(this)).apply()
        feedback.text=if(Settings.canDrawOverlays(this)) "QR поверх игры включён" else "Разрешение на показ поверх игры не выдано"
    }
    private val prepareVpn = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (it.resultCode == RESULT_OK && prefs.getBoolean("useVpn",false)) startVpn()
        else feedback.text = "VPN-перенаправление выключено"
    }
    private val importZip = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) background("Импортирую веб-клиент…") {
            val source=ClientCatalog.Source.entries.firstOrNull { it.directory==prefs.getString("importDirectory","") } ?: ClientCatalog.active(this)
            val result = ClientImport.install(contentResolver.openInputStream(uri) ?: error("Не удалось открыть ZIP"), ClientCatalog.engine(this),source.directory)
            ClientCatalog.activate(this,source)
            "$result. Веб-клиент готов"
        }
    }
    private val inspectApk = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) background("Читаю APK…") {
            inspectSelection(ApkSelection.document(this,contentResolver.openInputStream(uri) ?: error("Не удалось открыть APK")))
        }
    }
    private val poll = object : Runnable {
        override fun run() { refresh(); handler.postDelayed(this, 1000) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()
        setContentView(R.layout.activity_main)
        feedback = findViewById(R.id.status)
        findViewById<EditText>(R.id.gamePort).setText(prefs.getInt("gamePort", 5555).toString())
        findViewById<EditText>(R.id.webPort).setText(prefs.getInt("webPort", 8080).toString())
        findViewById<Button>(R.id.serverToggle).setOnClickListener { toggleServer() }
        findViewById<Button>(R.id.chooseGame).setOnClickListener { chooseGame() }
        findViewById<Button>(R.id.launchGame).setOnClickListener {
            val pkg = prefs.getString("gamePackage", "") ?: ""
            val launch = packageManager.getLaunchIntentForPackage(pkg)
            if (launch == null) feedback.text = "Сначала выберите установленную игру"
            else if (!ServerService.running) feedback.text = "Сначала запустите сервер"
            else if (pkg == prefs.getString("patchedPackage", "") && prefs.getInt("gamePort", 5555) != prefs.getInt("patchedPort", 5555))
                feedback.text = "Копия APK настроена на порт ${prefs.getInt("patchedPort", 5555)}. Выберите этот порт сервера или создайте патч заново"
            else startActivity(launch)
        }
        findViewById<Button>(R.id.settings).setOnClickListener { openSettings() }
        findViewById<Button>(R.id.importClient).setOnClickListener { openSettings() }
        findViewById<Button>(R.id.closeQr).setOnClickListener { roomInfo?.let { RoomQr.dismiss(this,it) };refresh() }
        findViewById<Button>(R.id.showQr).setOnClickListener { prefs.edit().remove("dismissedQr").putBoolean("showQr",true).apply();refresh() }
        findViewById<Button>(R.id.shareClient).setOnClickListener {
            if(joined.isNotEmpty()) startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,"LocalBox\n$joined"),"Ссылка для игроков"))
        }
        findViewById<Button>(R.id.inspectApk).setOnClickListener {
            if (!importBusy) inspectApk.launch(arrayOf("application/vnd.android.package-archive", "application/octet-stream"))
        }
        findViewById<Button>(R.id.patchInstalled).setOnClickListener { chooseInstalledForPatch() }
        findViewById<Button>(R.id.patchApk).setOnClickListener { createPatch() }
        findViewById<Button>(R.id.patchResult).setOnClickListener { showPatchResult() }
        findViewById<Button>(R.id.patchResult).visibility = if (patchedResult != null) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.openClient).setOnClickListener {
            if(ServerService.running) startActivity(Intent(this,PlayerActivity::class.java).putExtra("code",roomInfo?.optString("code")))
        }
        findViewById<TextView>(R.id.joinUrl).setOnLongClickListener {
            if (joined.isNotEmpty()) {
                (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("LocalBox", joined))
                feedback.text = "Адрес скопирован"
            }
            true
        }
        findViewById<Button>(R.id.vpnToggle).setOnClickListener {
            if (LocalVpnService.active) {
                findViewById<CheckBox>(R.id.useVpn).isChecked=false
            } else if (!ServerService.running) feedback.text = "Сначала запустите сервер"
            else if (!findViewById<CheckBox>(R.id.useVpn).isChecked) feedback.text = "Включите экспериментальный VPN галочкой"
            else if (prefs.getString("gamePackage", "").isNullOrEmpty()) feedback.text = "Выберите установленную игру"
            else {
                val permission = VpnService.prepare(this)
                if (permission != null) prepareVpn.launch(permission) else startVpn()
            }
        }
        findViewById<CheckBox>(R.id.patchSeparate).apply {
            isChecked=prefs.getBoolean("patchSeparate",true)
            setOnCheckedChangeListener { _,enabled -> prefs.edit().putBoolean("patchSeparate",enabled).apply() }
        }
        findViewById<CheckBox>(R.id.useVpn).apply {
            isChecked=prefs.getBoolean("useVpn",false)
            setOnCheckedChangeListener { _,enabled ->
                prefs.edit().putBoolean("useVpn",enabled).apply()
                if(!enabled) {
                    LocalVpnService.requestStop(this@MainActivity)
                    feedback.text="VPN-перенаправление выключено"
                }
                refresh()
            }
        }
        findViewById<Button>(R.id.patchApk).visibility = if (ApkSelection.current(this) != null) View.VISIBLE else View.GONE
        val selected = prefs.getString("gameLabel", "")
        if (!selected.isNullOrEmpty()) findViewById<Button>(R.id.chooseGame).text = selected
    }

    override fun onResume() { super.onResume();inForeground=true; handler.post(poll) }
    override fun onPause() { inForeground=false;handler.removeCallbacks(poll); super.onPause() }
    override fun onDestroy() { settingsDialog?.close();worker.shutdown(); super.onDestroy() }

    private fun toggleServer() {
        if (serverPending || ServerService.busy || importBusy || ClientDownloadService.active) return
        if (ServerService.running) {
            stopService(Intent(this, ServerService::class.java))
            return
        }
        val game = findViewById<EditText>(R.id.gamePort).text.toString().toIntOrNull()
        val web = findViewById<EditText>(R.id.webPort).text.toString().toIntOrNull()
        val error = Ports.error(game, web)
        if (error != null) { feedback.text = error; return }
        prefs.edit().putInt("gamePort", game!!).putInt("webPort", web!!).apply()
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        serverPending=true;ServerService.error="";refresh()
        try {
            ContextCompat.startForegroundService(this, Intent(this, ServerService::class.java).setAction(ServerService.START)
                .putExtra("host", lanAddress()).putExtra("gamePort", game).putExtra("webPort", web))
        } catch(failure: Exception) { serverPending=false;ServerService.error=failure.message ?: "Не удалось запустить службу";refresh() }
    }

    private fun refresh() {
        val running = ServerService.running
        if(running || ServerService.busy || ServerService.error.isNotEmpty()) serverPending=false
        val starting=serverPending || (ServerService.busy && !running)
        findViewById<TextView>(R.id.serverStatus).text = if(starting) "Запускаю сервер…" else if(ServerService.busy) "Останавливаю сервер…" else if (running) "Сервер работает" else if (ServerService.error.isNotEmpty()) "Ошибка запуска: ${ServerService.error}" else "Сервер остановлен"
        findViewById<Button>(R.id.serverToggle).apply {
            text = if(starting) "Запускается…" else if(ServerService.busy) "Останавливается…" else if (running) "Остановить сервер" else "Запустить сервер"
            isEnabled = !starting && !ServerService.busy && !importBusy && !ClientDownloadService.active
            alpha=if(isEnabled) 1f else 0.45f
        }
        findViewById<EditText>(R.id.gamePort).isEnabled = !running && !ServerService.busy
        findViewById<EditText>(R.id.webPort).isEnabled = !running && !ServerService.busy
        findViewById<Button>(R.id.vpnToggle).text = if (LocalVpnService.active) "Выключить перенаправление" else "Включить перенаправление"
        findViewById<Button>(R.id.vpnToggle).isEnabled=LocalVpnService.active || (running && prefs.getBoolean("useVpn",false))
        findViewById<CheckBox>(R.id.useVpn).apply { val enabled=prefs.getBoolean("useVpn",false);if(isChecked!=enabled) isChecked=enabled }
        findViewById<TextView>(R.id.vpnStatus).text=LocalVpnService.problem?.takeIf { LocalVpnService.active } ?: if(LocalVpnService.active) "VPN-перенаправление работает" else "VPN-перенаправление выключено"
        findViewById<Button>(R.id.openClient).isEnabled = running
        findViewById<Button>(R.id.shareClient).isEnabled = running
        findViewById<TextView>(R.id.portsSummary).text="Игра ${prefs.getInt("gamePort",5555)} · HTTP ${prefs.getInt("webPort",8080)}"+if(prefs.getBoolean("httpsEnabled",false)) " · HTTPS ${prefs.getInt("httpsPort",8443)}" else ""
        val readyCopy=patchedResult
        findViewById<Button>(R.id.patchResult).apply {
            visibility=if(readyCopy!=null) View.VISIBLE else View.GONE
            if(readyCopy!=null) text="Готовая копия: ${readyCopy.label}"
        }
        if (ServerService.error.isNotEmpty()) feedback.text = ServerService.error
        val info = if (running) try { JSONObject(NativeServer.status()) } catch (_: Throwable) { null } else null
        val room = info?.optJSONObject("room")
        roomInfo=room
        joined = if (running) room?.optString("joinUrl") ?: info?.optString("joinUrl").orEmpty() else ""
        findViewById<TextView>(R.id.joinUrl).text = joined.ifEmpty { "Адрес появится после запуска" }
        findViewById<TextView>(R.id.roomCode).text = if (room != null) "${room.optString("code")} · ${room.optInt("playerCount")}/${room.optInt("maxPlayers")}" else "Комната ещё не создана"
        val clientReady = ClientCatalog.ready(this)
        findViewById<TextView>(R.id.clientInfo).text = if(ClientDownloadService.active) ClientDownloadService.status else if (clientReady) "${ClientCatalog.active(this).title} · готов" else "Скачайте клиент в настройках или импортируйте ZIP"
        val image = findViewById<ImageView>(R.id.qr)
        val show = running && RoomQr.visible(this,room)
        findViewById<TextView>(R.id.qrUrl).text=joined
        findViewById<View>(R.id.qrPanel).visibility = if (show) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.showQr).visibility = if(running && clientReady && room!=null && room.optBoolean("qrVisible") && !show) View.VISIBLE else View.GONE
        if (show && joined != lastQr) {
            image.setImageBitmap(RoomQr.bitmap(joined))
            lastQr = joined
        }
    }

    private fun openSettings() {
        settingsDialog?.close()
        settingsDialog=AppSettings(this,{ game,web ->
            findViewById<EditText>(R.id.gamePort).setText(game.toString());findViewById<EditText>(R.id.webPort).setText(web.toString());refresh()
        },{ source ->
            if(importBusy || ServerService.running || ServerService.busy) { feedback.text="Остановите сервер перед загрузкой клиента" }
            else if(!ClientDownloadService.active) {
                if(Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(this,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                ContextCompat.startForegroundService(this,Intent(this,ClientDownloadService::class.java).putExtra("source",source.directory))
            }
        },{ source ->
            prefs.edit().putString("importDirectory",source.directory).apply()
            if(!importBusy && !ClientDownloadService.active && !ServerService.running && !ServerService.busy) importZip.launch(arrayOf("application/zip","application/octet-stream","application/x-zip-compressed"))
        },{
            overlayPermission.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,Uri.parse("package:$packageName")))
        }).also { it.open() }
    }

    private fun chooseGame() {
        InstalledApps.show(this,"Установленная игра") { app ->
                prefs.edit().putString("gamePackage", app.packageName).putString("gameLabel", app.label).apply()
                findViewById<Button>(R.id.chooseGame).text = app.label
                LocalVpnService.requestStop(this)
        }
    }

    /** Games built for Android 7+ trust only system CAs: their HTTPS/WSS cannot be redirected. */
    private fun vpnHint(pkg: String): String = try {
        val info = packageManager.getApplicationInfo(pkg, 0)
        if (info.targetSdkVersion >= 24) ". Если игра подключается по HTTPS (как Jackbox 7 и новее), VPN не поможет — нужен патч APK." else ""
    } catch (_: Exception) { "" }

    private fun startVpn() {
        if(!prefs.getBoolean("useVpn",false) || !ServerService.running || prefs.getString("gamePackage","").isNullOrEmpty()) return
        ContextCompat.startForegroundService(this, Intent(this, LocalVpnService::class.java)
            .setAction(LocalVpnService.ACTION_START)
            .putExtra(LocalVpnService.EXTRA_IP, "127.0.0.1:${prefs.getInt("gamePort", 5555)}")
            .putExtra(LocalVpnService.EXTRA_PACKAGE, prefs.getString("gamePackage", "")))
        feedback.text = "Запрашиваю перенаправление выбранной игры" + vpnHint(prefs.getString("gamePackage", "").orEmpty())
    }

    private fun inspectSelection(selection: ApkSelection): String {
        val analysis=ApkPatch.analyze(selection.files)
        val report=ApkInspection.inspect(this,selection,analysis)
        updateUi {
            findViewById<TextView>(R.id.apkInfo).text=report
            findViewById<Button>(R.id.patchApk).visibility=if(analysis.supported) View.VISIBLE else View.GONE
        }
        return analysis.reason
    }

    private fun chooseInstalledForPatch() {
        if(importBusy) return
        InstalledApps.show(this,"Из какой игры сделать копию?") { app ->
            background("Копирую APK установленной игры…") { inspectSelection(ApkSelection.installed(this,app.packageName)) }
        }
    }

    private fun exportResult(uri: Uri?) {
        if(uri==null) return
        val result=patchedResult ?: return
        background("Сохраняю копию игры…") {
            (contentResolver.openOutputStream(uri) ?: error("Не удалось записать файл")).use { result.export(it) }
            "Сохранено: ${result.downloadName}"
        }
    }

    private fun createPatch() {
        if(importBusy) return
        val port=findViewById<EditText>(R.id.gamePort).text.toString().toIntOrNull()
        if(port==null || port !in 1024..65535) { feedback.text="Укажите порт игры от 1024 до 65535";return }
        val source=ApkSelection.current(this) ?: run { feedback.text="Выберите APK или установленную игру";return }
        background("Готовлю копию игры…") {
            val result=ApkPatch.create(this,source,port,prefs.getBoolean("patchSeparate",true)) { message -> updateUi { feedback.text=message } }
            prefs.edit().putInt("patchedPort",port).putString("patchedPackage",result.packageName)
                .putString("gamePackage",result.packageName).putString("gameLabel",result.label).apply()
            updateUi {
                findViewById<Button>(R.id.chooseGame).text=result.label
                findViewById<Button>(R.id.patchResult).visibility=View.VISIBLE
                showPatchResult()
            }
            "Копия готова для 127.0.0.1:$port. Исходная игра не изменена"+if(result.separate) ". Копия встанет рядом с ней" else ""
        }
    }

    private fun showPatchResult() {
        val result=patchedResult ?: run { feedback.text="Сначала создайте патч игры";return }
        AlertDialog.Builder(this).setTitle("APK с подключением к LocalBox")
            .setMessage("${result.label}\n${result.packageName}\n\nКопия настроена на порт ${result.port}. ${if(result.split) "Все ${result.files.size} части будут установлены вместе. При сохранении получится ZIP с APK." else "Загрузка данных игр сохранена."}\n\n${if(result.separate) "Копия ставится рядом с оригиналом под именем «${result.label}»: удалять игру не нужно. Данные игры (загрузки, сохранения) у копии свои, при первом запуске она может заново скачать файлы." else "Копия заменяет оригинал: то же имя пакета, но новая подпись, поэтому Android не обновит ею игру. Удалите оригинал перед установкой, сохранив его данные."}")
            .setPositiveButton("Установить копию") { _, _ ->
                if (Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls())
                    allowInstaller.launch(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                else installPatched()
            }
            .setNeutralButton("Сохранить копию") { _, _ -> if(result.split) exportSplits.launch(result.downloadName) else exportPatch.launch(result.downloadName) }
            .setNegativeButton("Закрыть", null).show()
    }

    private fun installPatched() {
        val result=patchedResult ?: run { feedback.text="Копия игры не найдена";return }
        if(result.split) {
            background("Передаю все APK установщику Android…") { ApkInstall.split(this,result);"Подтвердите установку в окне Android" }
            return
        }
        val uri=FileProvider.getUriForFile(this,"$packageName.files",result.files.first())
        try { startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)) }
        catch(_: android.content.ActivityNotFoundException) { feedback.text="Установщик Android не найден. Сохраните APK отдельным файлом" }
    }

    private fun updateUi(action: () -> Unit) {
        runOnUiThread { if(!isDestroyed && !isFinishing) action() }
    }

    private fun background(message: String, work: () -> String) {
        if (importBusy) return
        importBusy = true
        feedback.text = message
        refresh()
        worker.execute {
            val result = try { synchronized(ApkWork) { work() } } catch (error: Exception) { error.message ?: "Ошибка чтения файла" }
            updateUi { importBusy = false; feedback.text = result; refresh() }
        }
    }

    private fun lanAddress(): String = try {
        NetworkInterface.getNetworkInterfaces().toList().filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }.filterIsInstance<Inet4Address>()
            .firstOrNull { it.isSiteLocalAddress && !it.hostAddress.orEmpty().startsWith("10.111.") }?.hostAddress ?: "127.0.0.1"
    } catch (_: Exception) { "127.0.0.1" }
}
