package tv.localbox.vpn

import android.content.Context
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import java.io.File
import java.util.Locale

/** Uses only offline voices without Android's notInstalled feature. Never installs voice data. */
class AndroidSpeech(context: Context, private val onReady: (AndroidSpeech)->Unit) {
    private val handler=Handler(Looper.getMainLooper())
    private var engine: TextToSpeech?=null
    private var closed=false
    private var activeId=""
    private var completion: ((String)->Unit)?=null
    private val timeout=Runnable { engine?.stop();finish("Движок TTS не ответил вовремя") }
    var voices: List<Voice> = emptyList();private set
    var message="Проверяю офлайн-голоса Android…";private set
    val ready get()=voices.isNotEmpty() && !closed
    init {
        try {
            engine=TextToSpeech(context.applicationContext) { status -> handler.post {
                if(!closed) {
                    voices=if(status==TextToSpeech.SUCCESS) runCatching {
                        engine?.voices.orEmpty().filter { !it.isNetworkConnectionRequired && !it.features.orEmpty().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) }
                            .sortedWith(compareBy({ it.locale.language!="ru" },{ it.locale.displayName },{ it.name }))
                    }.getOrDefault(emptyList()) else emptyList()
                    message=if(voices.isEmpty()) "В Android нет установленных офлайн-голосов. Озвучка недоступна; LocalBox ничего не скачивает." else "Офлайн-голосов Android: ${voices.size}"
                    onReady(this)
                }
            } }
            engine?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) { }
                override fun onDone(utteranceId: String?) { deliver(utteranceId,"") }
                @Deprecated("Android callback") override fun onError(utteranceId: String?) { deliver(utteranceId,"Ошибка синтеза речи") }
                override fun onError(utteranceId: String?,errorCode: Int) { deliver(utteranceId,"Ошибка TTS ($errorCode)") }
                override fun onStop(utteranceId: String?,interrupted: Boolean) { deliver(utteranceId,"Озвучка остановлена") }
            })
            handler.postDelayed({ if(!closed && message.startsWith("Проверяю")) { message="Системный движок TTS не ответил";onReady(this) } },15000)
        } catch(failure: Exception) {
            message="Системная озвучка недоступна: ${failure.message}"
            handler.post { if(!closed) onReady(this) }
        }
    }
    fun voice(name: String): Voice? = voices.firstOrNull { it.name==name }
        ?: voices.firstOrNull { it.locale.language=="ru" }
        ?: voices.firstOrNull { it.locale.language==Locale.getDefault().language }
        ?: voices.firstOrNull()
    private fun select(name: String,rate: Float): String? {
        val selected=voice(name) ?: return message
        if(engine?.setVoice(selected)!=TextToSpeech.SUCCESS) return "Не удалось включить офлайн-голос ${selected.name}"
        if(engine?.setSpeechRate(rate.coerceIn(0.5f,2f))!=TextToSpeech.SUCCESS) return "Не удалось настроить скорость речи"
        return null
    }
    fun synthesize(id: String,text: String,name: String,rate: Float,file: File,done: (String)->Unit) {
        if(completion!=null) { done("Движок озвучки занят");return }
        val error=select(name,rate)
        if(error!=null) { done(error);return }
        activeId=id;completion=done
        handler.postDelayed(timeout,40000)
        val result=runCatching { engine?.synthesizeToFile(text.take(TextToSpeech.getMaxSpeechInputLength()),Bundle(),file,id) }.getOrNull()
        if(result!=TextToSpeech.SUCCESS) finish("Не удалось создать аудио офлайн-голосом")
    }
    fun preview(name: String): String? {
        val error=select(name,1f);if(error!=null) return error
        val russian=voice(name)?.locale?.language=="ru"
        val result=engine?.speak(if(russian) "Привет! Это проверка озвучки LocalBox." else "Hello! This is the LocalBox voice preview.",TextToSpeech.QUEUE_FLUSH,Bundle(),"preview")
        return if(result==TextToSpeech.SUCCESS) null else "Не удалось воспроизвести голос"
    }
    private fun deliver(id: String?,error: String) { handler.post { if(id==activeId && !closed) finish(error) } }
    private fun finish(error: String) {
        handler.removeCallbacks(timeout)
        val callback=completion;completion=null;activeId="";callback?.invoke(error)
    }
    fun close() {
        closed=true;handler.removeCallbacksAndMessages(null)
        finish("Озвучка остановлена");engine?.stop();engine?.shutdown();engine=null
    }
}

/** Polls the native queue on the main thread; the actual synthesis is asynchronous in Android. */
class ServerSpeech(private val context: Context) {
    private val handler=Handler(Looper.getMainLooper())
    private var speech: AndroidSpeech?=null
    private var closed=false
    private var working=false
    private val poll=object : Runnable {
        override fun run() {
            if(closed) return
            val prefs=context.getSharedPreferences("localbox",0)
            val engine=speech
            val enabled=prefs.getBoolean("ttsEnabled",true)
            NativeServer.speechState(enabled && engine?.ready==true,if(!enabled) "Озвучка выключена в настройках" else engine?.message ?: "Подготовка озвучки…")
            if(enabled && engine?.ready==true && !working) {
                val request=NativeServer.speechNext()
                if(request.isNotEmpty()) {
                    val job=org.json.JSONObject(request)
                    working=true
                    engine.synthesize(job.getString("id"),job.getString("text"),prefs.getString("ttsVoice","").orEmpty(),job.optDouble("rate",1.0).toFloat(),File(job.getString("file"))) { error ->
                        NativeServer.speechDone(job.getString("id"),error);working=false
                    }
                }
            }
            handler.postDelayed(this,150)
        }
    }
    fun start() { speech=AndroidSpeech(context) { };handler.post(poll) }
    fun stop() {
        closed=true;handler.removeCallbacksAndMessages(null)
        NativeServer.speechState(false,"Сервер остановлен")
        speech?.close();speech=null
    }
}
