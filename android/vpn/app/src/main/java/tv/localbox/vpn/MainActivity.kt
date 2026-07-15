package tv.localbox.vpn

//
// Экран: ввод IP сервера → «Включить». Запрашивает разрешение на VPN (системный диалог),
// затем запускает LocalVpnService, который заворачивает домены Jackbox на этот IP.
//

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var ipEdit: EditText
    private lateinit var status: TextView
    private lateinit var prefs: SharedPreferences

    private val prepareVpn = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        if (res.resultCode == RESULT_OK) startVpn()
        else status.text = "Разрешение на VPN не выдано."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        ipEdit = findViewById(R.id.ip)
        status = findViewById(R.id.status)

        // сохранённый IP: подставляем последний введённый
        prefs = getSharedPreferences("localbox", Context.MODE_PRIVATE)
        prefs.getString("ip", null)?.let { if (it.isNotBlank()) ipEdit.setText(it) }

        findViewById<Button>(R.id.start).setOnClickListener {
            val ip = ipEdit.text.toString().trim()
            if (ip.isEmpty()) { toast("Впиши IP сервера"); return@setOnClickListener }
            prefs.edit().putString("ip", ip).apply()   // сохраняем IP
            ensureNotifPermission()
            val prep = VpnService.prepare(this)
            if (prep != null) prepareVpn.launch(prep) else startVpn()
        }
        findViewById<Button>(R.id.stop).setOnClickListener {
            startService(Intent(this, LocalVpnService::class.java).setAction(LocalVpnService.ACTION_STOP))
            status.text = "VPN остановлен."
        }
    }

    private fun startVpn() {
        val ip = ipEdit.text.toString().trim()
        val i = Intent(this, LocalVpnService::class.java)
            .setAction(LocalVpnService.ACTION_START)
            .putExtra(LocalVpnService.EXTRA_IP, ip)
        ContextCompat.startForegroundService(this, i)
        status.text = "VPN включён: домены Jackbox → $ip"
    }

    private fun ensureNotifPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
}
