package tv.localbox.vpn

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Test
import org.junit.Assert.*
import android.util.Log
import dalvik.system.DexClassLoader
import org.json.JSONObject
import java.io.File
import java.lang.reflect.Proxy
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.zip.ZipFile

/** Opt-in integration: supply a private fixture APK to the disposable emulator first. */
@Suppress("DEPRECATION")
class ApkPatchDeviceTest {
    @Test fun testInstalledGameSnapshotAndSplitExport() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val pkg="com.jackboxgames.JackboxPartyLoaderFulmRU"
        val selected=ApkSelection.installed(context,pkg)
        assertEquals(pkg,selected.packageName)
        val app=context.packageManager.getApplicationInfo(pkg,0)
        assertEquals(1+(app.splitSourceDirs?.size ?: 0),selected.files.size)
        assertTrue(ApkPatch.analyze(selected.files).supported)
        assertEquals(ApkPatch.sha256(File(app.sourceDir).readBytes()),ApkPatch.sha256(selected.base.readBytes()))
        val split=File(context.filesDir,"fixture-split.apk")
        assertTrue("Provide the test-only split manifest APK",split.isFile)
        val parts=ApkSelection(listOf(selected.base,split),selected.packageName,selected.label)
        val result=ApkPatch.create(context,parts,5557)
        assertTrue(result.split)
        val export=File(context.cacheDir,"fixture-export.zip")
        export.outputStream().use { result.export(it) }
        ZipFile(export).use { zip -> assertNotNull(zip.getEntry("base.apk"));assertNotNull(zip.getEntry("fixture-split.apk")) }
        val certs=result.files.map { file -> com.android.apksig.ApkVerifier.Builder(file).setMinCheckedPlatformVersion(24).build().verify().signerCertificates.first().encoded }
        assertArrayEquals(certs.first(),certs.last())
        assertEquals(2,ApkResult.current(context)!!.files.size)
        assertEquals(result.port,ApkResult.current(context)!!.port)
        Log.i("LocalBoxPatchTest","PASS: installed APK snapshot, multipart patch/signing, ZIP export and saved result")
    }

    @Test fun testExactApkPatchAndRealBlobcastClient() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val original = File(context.filesDir, "fixture-original.apk")
        assertTrue("Provide fixture-original.apk in the test emulator app's private files directory", original.isFile)
        assertTrue(ApkPatch.supported(context, original))
        val originalHash = ApkPatch.sha256(original.readBytes())
        val selection = ApkSelection.document(context,original.inputStream())
        val result = ApkPatch.create(context, selection, 5557) { Log.i("LocalBoxPatchTest", it) }
        val output=result.files.first()
        assertEquals(originalHash, ApkPatch.sha256(original.readBytes()))
        ZipFile(original).use { before -> ZipFile(output).use { after ->
            for (entry in before.entries()) {
                if (entry.name.startsWith("META-INF/") || entry.name in listOf("classes.dex", "AndroidManifest.xml", "assets/config.jet", "assets/games/PartyPack/jbg.config.jet")) continue
                assertTrue("Unrelated entry changed: ${entry.name}", before.getInputStream(entry).use { it.readBytes() }
                    .contentEquals(after.getInputStream(after.getEntry(entry.name)).use { it.readBytes() }))
            }
            val config = JSONObject(after.getInputStream(after.getEntry("assets/config.jet")).bufferedReader().use { it.readText() })
            assertEquals("127.0.0.1:5557", config.getString("serverUrl"))
        } }
        val parsed = context.packageManager.getPackageArchiveInfo(output.absolutePath, 0)!!
        assertTrue(parsed.applicationInfo!!.flags and android.content.pm.ApplicationInfo.FLAG_USES_CLEARTEXT_TRAFFIC != 0)
        // Exercise the actual patched Java client, not a replacement implementation.
        assertTrue(output.setReadOnly())
        val loader = DexClassLoader(output.absolutePath, context.codeCacheDir.absolutePath, null, context.classLoader)
        val delegateClass = loader.loadClass("com.jackboxgames.blobcast.IBlobCastClientDelegate")
        val clientClass = loader.loadClass("com.jackboxgames.blobcast.BlobCastClient")
        val ready = CountDownLatch(1)
        val callbacks = java.util.Collections.synchronizedList(mutableListOf<String>())
        val delegate = Proxy.newProxyInstance(loader, arrayOf(delegateClass)) { _, method, args ->
            callbacks.add(method.name)
            Log.i("LocalBoxPatchTest", "${method.name}: ${args?.toList()}")
            if (method.name == "clientCreatedRoom") ready.countDown()
            when (method.name) { "hashCode" -> 1; "equals" -> false; "toString" -> "LocalBox test delegate"; else -> null }
        }
        val directory = File(context.filesDir, "patch-test-engine").apply { mkdirs() }
        context.assets.open("games.json").use { input -> File(directory, "games.json").outputStream().use { input.copyTo(it) } }
        NativeServer.load()
        assertNull(NativeServer.start(directory.absolutePath, "127.0.0.1", 5557, 8080))
        var client: Any? = null
        try {
            client = clientClass.constructors.single().newInstance(delegate, "http://upstream.invalid/room", "localbox-fixture", "fixture-android-host", true)
            clientClass.getMethod("createRoom", JSONObject::class.java).invoke(client, JSONObject().put("maxPlayers", 8))
            assertTrue("Room was not created: $callbacks", ready.await(20, TimeUnit.SECONDS))
            val room = JSONObject(NativeServer.status()).getJSONObject("room")
            assertEquals(4, room.getString("code").length)
            assertTrue(room.getBoolean("qrVisible"))
            clientClass.getMethod("lockRoom").invoke(client)
            val deadline = System.currentTimeMillis() + 5000
            while (JSONObject(NativeServer.status()).getJSONObject("room").getBoolean("qrVisible") && System.currentTimeMillis() < deadline) Thread.sleep(50)
            assertFalse(JSONObject(NativeServer.status()).getJSONObject("room").getBoolean("qrVisible"))
            Log.i("LocalBoxPatchTest", "PASS: on-device signing, manifest, original Java Blobcast discovery + WebSocket + CreateRoom + LockRoom")
        } finally {
            client?.let { clientClass.getMethod("disconnectFromService").invoke(it) }
            NativeServer.stop()
        }
    }
}
