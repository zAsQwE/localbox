package tv.localbox.vpn

import android.content.Context
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.widget.*
import androidx.appcompat.widget.AppCompatButton as Button
import androidx.appcompat.widget.AppCompatCheckBox as CheckBox
import androidx.appcompat.widget.AppCompatSpinner as Spinner
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

class AppSettings(private val activity: AppCompatActivity,private val onApply: (Int,Int)->Unit,
                  private val download: (ClientCatalog.Source)->Unit,private val importZip: (ClientCatalog.Source)->Unit,
                  private val requestOverlay: ()->Unit) {
    private val prefs=activity.getSharedPreferences("localbox",Context.MODE_PRIVATE)
    private val handler=Handler(Looper.getMainLooper())
    private val body=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(4),dp(20),dp(12)) }
    private val game=EditText(activity).apply { inputType=InputType.TYPE_CLASS_NUMBER;setText(prefs.getInt("gamePort",5555).toString());contentDescription="Порт игры" }
    private val web=EditText(activity).apply { inputType=InputType.TYPE_CLASS_NUMBER;setText(prefs.getInt("webPort",8080).toString());contentDescription="Порт сайта" }
    private val https=CheckBox(activity).apply { text="HTTPS для сайта игроков";isChecked=prefs.getBoolean("httpsEnabled",false) }
    private val secure=EditText(activity).apply { inputType=InputType.TYPE_CLASS_NUMBER;setText(prefs.getInt("httpsPort",8443).toString());contentDescription="Порт HTTPS" }
    private val clients=Spinner(activity).apply {
        adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,ClientCatalog.Source.entries.map { it.title })
        setSelection(ClientCatalog.active(activity).ordinal)
    }
    private val status=TextView(activity).apply { setTextColor(Color.rgb(146,155,171)) }
    private val progress=ProgressBar(activity,null,android.R.attr.progressBarStyleHorizontal).apply { max=100 }
    private val cancel=Button(activity).apply { text="Отменить загрузку";setOnClickListener {
        activity.startService(android.content.Intent(activity,ClientDownloadService::class.java).setAction(ClientDownloadService.CANCEL))
    } }
    private val show=CheckBox(activity).apply { text="Показывать QR-код в лобби";isChecked=prefs.getBoolean("showQr",true)
        setOnCheckedChangeListener { _,checked -> prefs.edit().putBoolean("showQr",checked).apply() }
    }
    private val overlay=CheckBox(activity).apply { text="QR-код поверх игры" }
    private val actions=mutableListOf<Button>()
    private lateinit var dialog: AlertDialog
    private var previousActive=ClientCatalog.active(activity)
    private var speech: AndroidSpeech?=null
    private var voiceNames=emptyList<String>()
    private val tts=CheckBox(activity).apply { text="Озвучка системными офлайн-голосами";isChecked=prefs.getBoolean("ttsEnabled",true)
        setOnCheckedChangeListener { _,checked -> prefs.edit().putBoolean("ttsEnabled",checked).apply() }
    }
    private val voices=Spinner(activity).apply { isEnabled=false }
    private val ttsStatus=TextView(activity).apply { text="Проверяю офлайн-голоса Android…";setTextColor(Color.rgb(146,155,171)) }
    private val preview=Button(activity).apply { text="Проверить голос";isEnabled=false;setOnClickListener {
        speech?.preview(voiceNames.getOrNull(voices.selectedItemPosition).orEmpty())?.let { Toast.makeText(activity,it,Toast.LENGTH_LONG).show() }
    } }
    private val poll=object : Runnable {
        override fun run() {
            val active=ClientDownloadService.active
            progress.visibility=if(active) View.VISIBLE else View.GONE
            progress.isIndeterminate=ClientDownloadService.percent<0;progress.progress=ClientDownloadService.percent.coerceAtLeast(0)
            cancel.visibility=if(active) View.VISIBLE else View.GONE
            cancel.isEnabled=!ClientDownloadService.cancelRequested
            val locked=active || ServerService.running || ServerService.busy
            game.isEnabled=!locked;web.isEnabled=!locked;https.isEnabled=!locked;secure.isEnabled=!locked && https.isChecked;clients.isEnabled=!locked;actions.forEach { it.isEnabled=!locked }
            val current=ClientCatalog.active(activity)
            if(previousActive!=current) { clients.setSelection(current.ordinal);previousActive=current }
            status.text=listOfNotNull(
                "Обычный: ${if(ClientCatalog.ready(activity,ClientCatalog.Source.ENGLISH)) "скачан" else "не скачан"}. Русский: ${if(ClientCatalog.ready(activity,ClientCatalog.Source.RUSSIAN)) "скачан" else "не скачан"}.",
                ClientDownloadService.status.takeIf { it.isNotEmpty() },
                "HTTP: ${prefs.getInt("webPort",8080)}. ${if(prefs.getBoolean("httpsEnabled",false)) "HTTPS: ${prefs.getInt("httpsPort",8443)} · сертификат подписан CA LocalBox этого телефона (скачать: /localbox-ca.crt); без доверия к нему браузер покажет предупреждение." else "Чтобы открывать https://, включите HTTPS и используйте отдельный порт."}"
            ).joinToString("\n\n")
            overlay.setOnCheckedChangeListener(null)
            overlay.isChecked=prefs.getBoolean("overlayQr",false) && Settings.canDrawOverlays(activity)
            overlay.setOnCheckedChangeListener { _,checked ->
                if(checked && !Settings.canDrawOverlays(activity)) { overlay.isChecked=false;requestOverlay() }
                else prefs.edit().putBoolean("overlayQr",checked).apply()
            }
            handler.postDelayed(this,750)
        }
    }
    fun open() {
        label("Порт игры");body.addView(game)
        label("Порт сайта игроков");body.addView(web)
        body.addView(https);label("Порт HTTPS");body.addView(secure)
        label("Активный веб-клиент");body.addView(clients)
        for(source in ClientCatalog.Source.entries) {
            val button=Button(activity).apply { text=if(source==ClientCatalog.Source.ENGLISH) "Скачать client с GitHub" else "Скачать client-ru из Release";setOnClickListener { download(source) } }
            actions.add(button);body.addView(button)
        }
        val local=Button(activity).apply { text="Импортировать ZIP";setOnClickListener { importZip(ClientCatalog.Source.entries[clients.selectedItemPosition]) } };actions.add(local);body.addView(local)
        body.addView(progress);body.addView(cancel);body.addView(status)
        label("Озвучка TTS");body.addView(tts);body.addView(voices);body.addView(preview);body.addView(ttsStatus)
        label("Используются только голоса, уже установленные в Android. Голоса Piper и Silero в APK не входят.")
        label("QR-код");body.addView(show);body.addView(overlay)
        label("Крестик скрывает QR до следующей комнаты. Для окна поверх игры Android запросит отдельное разрешение.")
        val scroll=ScrollView(activity).apply { addView(body) }
        dialog=AlertDialog.Builder(activity).setTitle("Настройки").setView(scroll).setPositiveButton("Сохранить",null).setNegativeButton("Закрыть",null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val g=game.text.toString().toIntOrNull();val w=web.text.toString().toIntOrNull();val error=Ports.error(g,w)
                if(error!=null) { Toast.makeText(activity,error,Toast.LENGTH_LONG).show();return@setOnClickListener }
                val tlsPort=secure.text.toString().toIntOrNull()
                if(https.isChecked && (Ports.error(g,tlsPort)!=null || tlsPort==w)) { Toast.makeText(activity,"Для HTTPS нужен отдельный разрешённый порт, например 8443",Toast.LENGTH_LONG).show();return@setOnClickListener }
                val selected=ClientCatalog.Source.entries[clients.selectedItemPosition]
                if(!ServerService.running && !ServerService.busy && !ClientDownloadService.active) {
                    if(ClientCatalog.ready(activity,selected)) ClientCatalog.activate(activity,selected)
                    else if(selected!=ClientCatalog.active(activity)) { Toast.makeText(activity,"Сначала скачайте выбранный клиент",Toast.LENGTH_LONG).show();return@setOnClickListener }
                    prefs.edit().putInt("gamePort",g!!).putInt("webPort",w!!).putBoolean("httpsEnabled",https.isChecked).putInt("httpsPort",tlsPort ?: 8443).apply();onApply(g,w)
                }
                dialog.dismiss()
            }
            handler.post(poll)
            speech=AndroidSpeech(activity) { engine ->
                ttsStatus.text=engine.message
                voiceNames=engine.voices.map { it.name }
                voices.adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,engine.voices.map { "${it.locale.getDisplayName(java.util.Locale("ru"))} · ${it.name}" })
                voices.isEnabled=engine.ready;preview.isEnabled=engine.ready
                val preferred=engine.voice(prefs.getString("ttsVoice","").orEmpty())?.name
                voices.setSelection(voiceNames.indexOf(preferred).coerceAtLeast(0))
                voices.onItemSelectedListener=object : AdapterView.OnItemSelectedListener {
                    override fun onNothingSelected(parent: AdapterView<*>?) { }
                    override fun onItemSelected(parent: AdapterView<*>?,view: View?,position: Int,id: Long) { voiceNames.getOrNull(position)?.let { prefs.edit().putString("ttsVoice",it).apply() } }
                }
            }
        }
        dialog.setOnDismissListener { handler.removeCallbacks(poll);speech?.close();speech=null }
        dialog.show()
    }
    fun close() { if(::dialog.isInitialized) dialog.dismiss() }
    private fun label(value: String) { body.addView(TextView(activity).apply { text=value;setTextColor(Color.rgb(146,155,171));setPadding(0,dp(12),0,dp(4)) }) }
    private fun dp(value: Int)=(activity.resources.displayMetrics.density*value).toInt()
}
