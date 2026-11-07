package tv.localbox.vpn

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Serializes disk operations across Activity recreation. */
object ApkWork

data class ApkSelection(val files: List<File>,val packageName: String,val label: String) {
    val base get()=files.first()
    companion object {
        fun current(context: Context): ApkSelection? = try {
            val directory=File(context.cacheDir,"selected-game")
            val meta=JSONObject(File(directory,"source.json").readText())
            val names=meta.getJSONArray("files")
            val files=(0 until names.length()).map { i -> safeFile(directory,names.getString(i)) }
            if(files.isEmpty() || files.any { !it.isFile }) null else ApkSelection(files,meta.getString("package"),meta.getString("label"))
        } catch(_: Exception) { null }

        fun document(context: Context,input: InputStream): ApkSelection = stage(context) { directory ->
            val base=File(directory,"base.apk")
            input.use { src -> base.outputStream().use { ClientImport.copyLimited(src,it,2L*1024*1024*1024) } }
            val info=context.packageManager.getPackageArchiveInfo(base.absolutePath,0) ?: error("Это не читаемый APK")
            info.applicationInfo?.apply { sourceDir=base.absolutePath;publicSourceDir=base.absolutePath }
            ApkSelection(listOf(base),info.packageName,info.applicationInfo?.loadLabel(context.packageManager)?.toString() ?: info.packageName)
        }
        fun installed(context: Context,packageName: String): ApkSelection = stage(context) { directory ->
            val info=context.packageManager.getPackageInfo(packageName,0)
            val app=info.applicationInfo ?: error("Игра недоступна")
            val source=listOf(File(app.sourceDir))+(app.splitSourceDirs?.map { File(it) } ?: emptyList())
            require(directory.usableSpace>source.sumOf { it.length() }+64L*1024*1024) { "Недостаточно места для копии игры" }
            val files=source.mapIndexed { index,file ->
                val size=file.length();val time=file.lastModified()
                require(file.isFile && file.canRead()) { "Android не разрешил прочитать APK этой игры" }
                val target=File(directory,if(index==0) "base.apk" else "split_$index.apk")
                file.inputStream().use { input -> target.outputStream().use { ClientImport.copyLimited(input,it,2L*1024*1024*1024) } }
                check(size==file.length() && time==file.lastModified()) { "Игра обновилась во время копирования. Выберите её ещё раз" }
                target
            }
            check(context.packageManager.getPackageInfo(packageName,0).lastUpdateTime==info.lastUpdateTime) { "Игра обновилась во время копирования" }
            ApkSelection(files,packageName,app.loadLabel(context.packageManager).toString())
        }
        private fun stage(context: Context,copy: (File)->ApkSelection): ApkSelection {
            val target=File(context.cacheDir,"selected-game")
            val staging=File(context.cacheDir,"selected-game-new").apply { deleteRecursively();mkdirs() }
            try {
                val selected=copy(staging)
                File(staging,"source.json").writeText(JSONObject().put("package",selected.packageName).put("label",selected.label)
                    .put("files",JSONArray(selected.files.map { it.name })).toString())
                val previous=File(context.cacheDir,"selected-game-old").apply { deleteRecursively() }
                if(target.exists()) check(target.renameTo(previous)) { "Не удалось заменить выбранный APK" }
                if(!staging.renameTo(target)) { previous.renameTo(target);error("Не удалось сохранить выбранный APK") }
                previous.deleteRecursively()
                return current(context) ?: error("Не удалось прочитать выбранный APK")
            } finally { staging.deleteRecursively() }
        }
    }
}

/** [packageName] is the copy's package; [originalPackage] the game it was made from (equal when installed over it). */
data class ApkResult(val directory: File,val files: List<File>,val packageName: String,val label: String,val port: Int,val originalPackage: String=packageName) {
    val separate get()=packageName!=originalPackage
    val split get()=files.size>1
    val downloadName get()="LocalBox-$packageName.${if(split) "zip" else "apk"}"
    fun export(output: java.io.OutputStream) {
        if(!split) files.first().inputStream().use { it.copyTo(output) }
        else ZipOutputStream(output).use { zip ->
            for(file in files) { zip.putNextEntry(ZipEntry(file.name));file.inputStream().use { it.copyTo(zip) };zip.closeEntry() }
            zip.putNextEntry(ZipEntry("LocalBox.txt"));zip.write("$label\n$packageName\nLocalBox port: $port\nInstall all APK files together, or use LocalBox to install this prepared set.\n".toByteArray());zip.closeEntry()
        }
    }
    fun saveMetadata() { File(directory,"result.json").writeText(JSONObject().put("package",packageName).put("original",originalPackage).put("label",label).put("port",port).put("files",JSONArray(files.map { it.name })).toString()) }
    companion object {
        fun current(context: Context): ApkResult? = read(File(context.filesDir,"patched/current"))
        fun read(directory: File): ApkResult? = try {
            val meta=JSONObject(File(directory,"result.json").readText());val names=meta.getJSONArray("files")
            val files=(0 until names.length()).map { safeFile(directory,names.getString(it)) }
            if(files.isEmpty() || files.any { !it.isFile }) null else ApkResult(directory,files,meta.getString("package"),meta.getString("label"),meta.getInt("port"),meta.optString("original",meta.getString("package")))
        } catch(_: Exception) { null }
    }
}
private fun safeFile(directory: File,name: String): File {
    require(name.matches(Regex("[a-zA-Z0-9_.-]+\\.apk")))
    return File(directory,name)
}
