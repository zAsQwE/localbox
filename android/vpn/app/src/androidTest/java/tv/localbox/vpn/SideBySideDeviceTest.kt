package tv.localbox.vpn

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.zip.ZipFile

/**
 * The copy gets its own package, so Android installs it next to the original game.
 * Uses the private files/fixture-ecast.apk (JPP7). The host then installs both with adb:
 * `adb exec-out run-as tv.localbox.vpn cat files/patched/current/<apk>`.
 */
class SideBySideDeviceTest {
    @Test fun copyHasItsOwnPackageAndLabel() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val fixture=File(context.filesDir,"fixture-ecast.apk")
        assertTrue("Supply the private JPP7 fixture-ecast.apk",fixture.isFile)
        val source=ApkSelection.document(context,fixture.inputStream())
        val result=ApkPatch.create(context,source,5557)
        assertEquals(source.packageName+".localbox",result.packageName)
        assertEquals(source.packageName,result.originalPackage)
        assertTrue(result.separate)
        val info=context.packageManager.getPackageArchiveInfo(result.files.first().absolutePath,0)!!
        assertEquals(result.packageName,info.packageName)
        ZipFile(result.files.first()).use { zip ->
            val manifest=zip.getInputStream(zip.getEntry("AndroidManifest.xml")).readBytes()
            assertTrue(BinaryManifest.strings(manifest).any { it.first=="application" && it.second=="label" && it.third.endsWith("· LocalBox") })
        }
        // Re-patching the copy keeps its package instead of adding another suffix.
        val again=ApkPatch.create(context,ApkSelection.document(context,result.files.first().inputStream()),5558)
        assertEquals(result.packageName,again.packageName)
        android.util.Log.i("LocalBoxSideBySide","copy=${again.packageName} file=${again.files.first().name}")
    }
}
