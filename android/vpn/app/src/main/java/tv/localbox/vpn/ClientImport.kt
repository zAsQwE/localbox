package tv.localbox.vpn

import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.util.zip.ZipInputStream

object ClientImport {
    fun copyLimited(input: InputStream, output: OutputStream, limit: Long): Long {
        val buffer = ByteArray(65536)
        var copied = 0L
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            copied += count
            require(copied <= limit) { "Файл слишком большой или не хватает свободного места" }
            output.write(buffer, 0, count)
        }
        return copied
    }

    fun destination(base: File, name: String): File {
        require(!name.contains('\\') && !name.startsWith('/')) { "Недопустимый путь в ZIP" }
        val file = File(base, name).canonicalFile
        require(file.path.startsWith(base.canonicalPath + File.separator)) { "ZIP выходит за пределы папки клиента" }
        return file
    }

    fun install(input: InputStream, engine: File, directory: String = "client", cancelled: () -> Boolean = { false }, progress: (String) -> Unit = {}, requireMain: Boolean = false): String {
        require(directory in setOf("client", "client-ru"))
        engine.mkdirs()
        val stage = File(engine, "$directory-import").apply { deleteRecursively(); mkdirs() }
        val previous = File(engine, "$directory-previous")
        val target = File(engine, directory)
        val budget = (engine.usableSpace - 128L*1024*1024).coerceAtMost(6L*1024*1024*1024)
        require(budget > 0) { "Недостаточно свободного места" }
        var bytes = 0L
        var files = 0
        try {
            ZipInputStream(input).use { zip ->
                while (true) {
                    ClientDownload.checkCancelled(cancelled)
                    val entry = zip.nextEntry ?: break
                    require(++files <= 150000) { "Слишком много файлов в ZIP" }
                    val output = destination(stage, entry.name)
                    if (entry.isDirectory) output.mkdirs()
                    else {
                        output.parentFile?.mkdirs()
                        output.outputStream().use { bytes += copyLimited(zip, it, budget-bytes) }
                    }
                    zip.closeEntry()
                    if (files % 250 == 0) progress("Распаковка: $files файлов, ${bytes / (1024*1024)} МБ")
                }
            }
            val indexes = stage.walkTopDown().maxDepth(5).filter { it.isFile && it.name == "index.html" }.toList()
            val index = indexes.minByOrNull { it.relativeTo(stage).path.count { ch -> ch == File.separatorChar } }
                ?: error("В ZIP не найден index.html. Выберите архив веб-клиента")
            val source = index.parentFile!!
            require(!requireMain || File(source, "main").isDirectory) { "В архиве клиента нет папки main" }
            ClientDownload.checkCancelled(cancelled)
            previous.deleteRecursively()
            if (target.exists()) require(target.renameTo(previous)) { "Не удалось сохранить предыдущий клиент" }
            try {
                require(source.renameTo(target)) { "Не удалось разместить веб-клиент" }
            } catch (error: Exception) {
                previous.renameTo(target)
                throw error
            }
            previous.deleteRecursively()
            return "Добавлено файлов: $files"
        } finally { stage.deleteRecursively() }
    }
}
