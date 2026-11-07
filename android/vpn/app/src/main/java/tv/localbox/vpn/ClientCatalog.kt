package tv.localbox.vpn

import android.content.Context
import java.io.File

object ClientCatalog {
    enum class Source(val directory: String,val title: String) {
        ENGLISH("client","Обычный · jackbox.tv"), RUSSIAN("client-ru","Русский · client-ru")
    }
    fun engine(context: Context)=File(context.filesDir,"engine").apply { mkdirs() }
    fun active(context: Context): Source {
        val name=context.getSharedPreferences("localbox",0).getString("clientDirectory","client")
        return Source.entries.firstOrNull { it.directory==name } ?: Source.ENGLISH
    }
    fun ready(context: Context,source: Source=active(context))=File(engine(context),"${source.directory}/index.html").isFile
    fun activate(context: Context,source: Source) {
        require(ready(context,source)) { "Этот клиент ещё не скачан" }
        val engine=engine(context)
        val temp=File(engine,"client-choice.txt.new").apply { writeText(source.directory) }
        check(temp.renameTo(File(engine,"client-choice.txt"))) { "Не удалось выбрать клиент" }
        context.getSharedPreferences("localbox",0).edit().putString("clientDirectory",source.directory).apply()
    }
}
