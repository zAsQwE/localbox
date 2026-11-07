package tv.localbox.vpn

import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.TextWatcher
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

/** Both selection flows share the same searchable launcher-app list. */
object InstalledApps {
    data class App(val label: String, val packageName: String) {
        override fun toString() = "$label\n$packageName"
    }
    fun show(activity: AppCompatActivity, title: String, selected: (App)->Unit): AlertDialog {
        val content=LinearLayout(activity).apply {
            orientation=LinearLayout.VERTICAL
            val margin=(20*resources.displayMetrics.density).toInt()
            setPadding(margin,0,margin,0)
        }
        val search=EditText(activity).apply {
            id=R.id.installedSearch;hint="Название приложения или пакет";isSingleLine=true
            inputType=android.text.InputType.TYPE_CLASS_TEXT
        }
        val empty=TextView(activity).apply { text="Загружаю приложения…" }
        val list=ListView(activity).apply { id=R.id.installedList;emptyView=empty }
        content.addView(search);content.addView(empty)
        val height=minOf((350*activity.resources.displayMetrics.density).toInt(),(activity.resources.displayMetrics.heightPixels*0.45).toInt())
        content.addView(list,LinearLayout.LayoutParams(-1,height))
        var apps=emptyList<App>()
        var filtered=emptyList<App>()
        val adapter=ArrayAdapter<App>(activity,android.R.layout.simple_list_item_1,mutableListOf())
        list.adapter=adapter
        fun filter() {
            val query=search.text.toString().trim()
            filtered=apps.filter { it.label.contains(query,true) || it.packageName.contains(query,true) }
            adapter.clear();adapter.addAll(filtered);adapter.notifyDataSetChanged()
            empty.text=if(apps.isEmpty()) "Нет доступных приложений" else "Ничего не найдено"
        }
        search.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) { }
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { filter() }
            override fun afterTextChanged(s: Editable?) { }
        })
        val dialog=AlertDialog.Builder(activity).setTitle(title).setView(content).setNegativeButton("Отмена",null).create()
        list.setOnItemClickListener { _,_,position,_ -> filtered.getOrNull(position)?.let { dialog.dismiss();selected(it) } }
        dialog.show()
        Thread({
            val result=runCatching {
                activity.packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER),0)
                    .filter { it.activityInfo.packageName!=activity.packageName }.distinctBy { it.activityInfo.packageName }
                    .map { App(it.loadLabel(activity.packageManager).toString(),it.activityInfo.packageName) }
                    .sortedWith(compareBy({ !it.packageName.contains("jackbox",true) },{ it.label.lowercase() }))
            }
            Handler(Looper.getMainLooper()).post {
                if(dialog.isShowing && !activity.isDestroyed) {
                    apps=result.getOrDefault(emptyList());filter()
                    if(result.isFailure) empty.text="Не удалось получить список приложений"
                }
            }
        },"localbox-apps").start()
        return dialog
    }
}
