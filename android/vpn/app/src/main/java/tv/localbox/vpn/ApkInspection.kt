package tv.localbox.vpn

import android.content.Context
import java.util.zip.ZipFile

object ApkInspection {
    fun inspect(context: Context,source: ApkSelection,analysis: ApkPatch.Analysis): String {
        val info=context.packageManager.getPackageArchiveInfo(source.base.absolutePath,0) ?: error("Не удалось прочитать APK")
        val entries=source.files.flatMap { file -> ZipFile(file).use { it.entries().toList().map { e -> e.name } } }
        val engine=when {
            entries.any { it.endsWith("/libil2cpp.so") } -> "Unity IL2CPP"
            entries.any { it.endsWith("/Assembly-CSharp.dll") } -> "Unity Mono"
            entries.any { it.endsWith(".swf") } -> "Flash / Scaleform"
            else -> "Java или нативный движок"
        }
        val abis=entries.filter { it.startsWith("lib/") && it.endsWith(".so") }.map { it.split('/')[1] }.distinct().joinToString().ifEmpty { "Java" }
        return "${source.label}\nПакет: ${source.packageName}\nВерсия: ${info.versionName}\nДвижок: $engine\nАрхитектуры: $abis\nФайлов APK: ${source.files.size}\n\n${analysis.reason}"
    }
}
