package tv.localbox.vpn

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.widget.Toast

object ApkInstall {
    fun split(context: Context,result: ApkResult) {
        val installer=context.packageManager.packageInstaller
        val params=PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(result.packageName);setSize(result.files.sumOf { it.length() })
            if(Build.VERSION.SDK_INT>=31) setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
        }
        val id=installer.createSession(params)
        try {
            installer.openSession(id).use { session ->
                for(file in result.files) session.openWrite(file.name,0,file.length()).use { output ->
                    file.inputStream().use { it.copyTo(output) };session.fsync(output)
                }
                val flags=PendingIntent.FLAG_UPDATE_CURRENT or if(Build.VERSION.SDK_INT>=31) PendingIntent.FLAG_MUTABLE else 0
                val callback=PendingIntent.getBroadcast(context,id,Intent(context,InstallResultReceiver::class.java),flags)
                session.commit(callback.intentSender)
            }
        } catch(error: Exception) { installer.abandonSession(id);throw error }
    }
}
class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context,intent: Intent) {
        when(intent.getIntExtra(PackageInstaller.EXTRA_STATUS,PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION") val confirm=intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if(confirm!=null) context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            PackageInstaller.STATUS_SUCCESS -> Toast.makeText(context,"Копия игры установлена",Toast.LENGTH_LONG).show()
            else -> Toast.makeText(context,"Установка не завершена: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()}",Toast.LENGTH_LONG).show()
        }
    }
}
