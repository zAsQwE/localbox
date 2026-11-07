package tv.localbox.vpn

// Локальный VPN только для выбранного приложения. DNS Jackbox получает fake-IP,
// TCP к этому IP переносится на локальный порт сервера. Остальные приложения
// используют обычную сеть. TLS передаётся без изменений: HTTPS-игре нужен
// совместимый патч или поддерживаемая настройка адреса сервера.

import android.app.*
import android.content.Intent
import android.content.Context
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import kotlin.concurrent.thread

class LocalVpnService : VpnService() {

    companion object {
        const val ACTION_START = "tv.localbox.vpn.START"
        const val ACTION_STOP = "tv.localbox.vpn.STOP"
        const val EXTRA_IP = "ip"
        const val EXTRA_PACKAGE = "package"
        @Volatile var active = false
        /** Why redirected traffic could not be served (shown in the app), or null. */
        @Volatile var problem: String? = null
        @Volatile var problemPort = 0
        const val TLS_PROBLEM = "Игра подключается по HTTPS/WSS и проверяет сертификат Jackbox — VPN это не обходит. " +
            "Используйте «Патч из установленной игры»: копия игры подключится к LocalBox без VPN."
        fun requestStop(context: Context) {
            // Android binds an active VpnService itself: stopService alone does
            // not call onDestroy until that binding is released. Close TUN first.
            if(active) context.startService(Intent(context,LocalVpnService::class.java).setAction(ACTION_STOP))
            else context.stopService(Intent(context,LocalVpnService::class.java))
        }
        const val CHANNEL = "localboxvpn"
        private const val SENTINEL = "10.111.0.1"   // «наш» DNS-адрес внутри TUN
        private const val VPN_ADDR = "10.111.0.2"    // адрес TUN-интерфейса
        private const val PROXY_IP = "10.111.0.3"    // fake-IP: DNS заворачивает сюда домены Jackbox,
                                                     // а весь TCP к нему перехватывает TcpProxy
        private const val UPSTREAM = "1.1.1.1"       // куда форвардим не-Jackbox запросы

        private val SUFFIXES = listOf("jackboxgames.com", "jackbox.tv", "jackbox.ru", "jackbox.fun")
        fun isJackbox(host: String): Boolean {
            val h = host.lowercase()
            if (SUFFIXES.any { h == it || h.endsWith(".$it") }) return true
            return false
        }
    }

    private var tun: ParcelFileDescriptor? = null
    @Volatile private var running = false
    private val proxyIpBytes = byteArrayOf(10, 111, 0, 3)   // = PROXY_IP, ответ DNS
    private var realHost = "127.0.0.1"                       // реальный сервер (куда переносить)
    private var realPort = 5555
    private var allowedPackage = ""
    private var tcpProxy: TcpProxy? = null
    private var tunOut: FileOutputStream? = null
    private val writeLock = Any()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            getSharedPreferences("localbox",0).edit().putBoolean("useVpn",false).apply()
            stop(); return START_NOT_STICKY
        }
        if(!getSharedPreferences("localbox",0).getBoolean("useVpn",false) || !ServerService.running) {
            stop();return START_NOT_STICKY
        }
        // EXTRA_IP = адрес РЕАЛЬНОГО сервера "host[:port]" (напр. 127.0.0.1:9999 на этом же телефоне)
        val addr = intent?.getStringExtra(EXTRA_IP)?.trim() ?: return START_NOT_STICKY
        allowedPackage = intent.getStringExtra(EXTRA_PACKAGE).orEmpty()
        if (allowedPackage.isBlank()) { stopSelf(); return START_NOT_STICKY }
        realHost = addr.substringBefore(":").ifBlank { "127.0.0.1" }
        realPort = addr.substringAfter(":", "5555").toIntOrNull() ?: 5555
        startForeground(1, notif("Jackbox → $realHost:$realPort (прокси)"))
        try { startVpn() } catch (_: Exception) { stop() }
        return START_NOT_STICKY
    }

    private fun startVpn() {
        if (running) return
        problem = null
        problemPort = 0
        val b = Builder()
            .setSession("LocalBox VPN")
            .addAddress(VPN_ADDR, 32)
            .addDnsServer(SENTINEL)
            .addRoute(SENTINEL, 32)     // DNS к sentinel
            .addRoute(PROXY_IP, 32)     // TCP к fake-IP Jackbox — перехватываем прокси
        b.addAllowedApplication(allowedPackage)
        b.setBlocking(true)
        tun = b.establish() ?: run { stop(); return }
        running = true
        active = true
        thread(name = "localbox-vpn") { loop() }
    }

    private fun loop() {
        val fd = tun!!.fileDescriptor
        val input = FileInputStream(fd)
        tunOut = FileOutputStream(fd)
        val writer: (ByteArray) -> Unit = { pkt -> synchronized(writeLock) { try { tunOut?.write(pkt) } catch (_: Exception) {} } }
        tcpProxy = TcpProxy(this, writer, realHost, realPort) { port ->
            if (problem == null) {
                problemPort = port
                problem = TLS_PROBLEM
                android.util.Log.w("LocalBoxVpn", "TLS to port $port: the game needs the APK patch")
                try { getSystemService(NotificationManager::class.java).notify(1, notif("HTTPS-игра: нужен патч APK, VPN не поможет")) } catch (_: Exception) {}
            }
        }
        val buf = ByteArray(32767)
        while (running) {
            val n = try { input.read(buf) } catch (e: Exception) { break }
            if (n < 0) break
            if (n == 0) continue
            if (n < 20) continue
            val ver = (buf[0].toInt() and 0xF0) ushr 4
            if (ver != 4) continue
            when (buf[9].toInt() and 0xFF) {
                6 -> try { tcpProxy?.handle(buf, n) } catch (e: Exception) {}          // TCP → прокси (пишет сам)
                17 -> { val r = try { handleDns(buf, n) } catch (e: Exception) { null }; if (r != null) writer(r) } // DNS
            }
        }
        try { input.close() } catch (_: Exception) { }
        if (running) stop()
    }

    // Обрабатывает один DNS-пакет (UDP:53). Возвращает ответный IP-пакет или null.
    private fun handleDns(pkt: ByteArray, len: Int): ByteArray? {
        if (len < 28) return null
        val ihl = (pkt[0].toInt() and 0x0F) * 4
        if (ihl < 20 || ihl+8 > len || u16(pkt, 2) > len || pkt[6].toInt() and 0x3F != 0 || pkt[7].toInt() != 0) return null
        if (!pkt.copyOfRange(16,20).contentEquals(byteArrayOf(10,111,0,1))) return null
        val dstPort = u16(pkt, ihl + 2)
        if (dstPort != 53) return null

        val udpEnd = ihl + u16(pkt, ihl+4)
        if (udpEnd > len || udpEnd < ihl+8) return null
        val dns = pkt.copyOfRange(ihl + 8, udpEnd)
        val q = parseQuestion(dns) ?: return null
        val (name, qtype, qEnd) = q

        val dnsResp: ByteArray = if (isJackbox(name)) {
            if (qtype == 1) buildDns(dns, qEnd, proxyIpBytes)    // A → fake-IP (10.111.0.3)
            else buildDns(dns, qEnd, null)                        // AAAA → пусто
        } else {
            forward(dns) ?: return null
        }
        return buildIpUdp(pkt, ihl, dnsResp)
    }

    // Форвард запроса вышестоящему DNS через protected-сокет (мимо VPN).
    private fun forward(query: ByteArray): ByteArray? {
        return try {
            DatagramSocket().use { s ->
                protect(s)
                s.soTimeout = 4000
                val addr = InetAddress.getByName(UPSTREAM)
                s.connect(addr, 53)
                s.send(DatagramPacket(query, query.size, addr, 53))
                val resp = ByteArray(1500)
                val dp = DatagramPacket(resp, resp.size)
                s.receive(dp)
                resp.copyOf(dp.length)
            }
        } catch (e: Exception) { null }
    }

    // ---------------- разбор/сборка пакетов ----------------

    private fun u16(b: ByteArray, off: Int) = ((b[off].toInt() and 0xFF) shl 8) or (b[off + 1].toInt() and 0xFF)

    // Возвращает (имя, qtype, конец_секции_вопроса) или null.
    private fun parseQuestion(dns: ByteArray): Triple<String, Int, Int>? {
        if (dns.size < 12) return null
        var pos = 12
        val sb = StringBuilder()
        while (pos < dns.size) {
            val l = dns[pos].toInt() and 0xFF
            if (l == 0) { pos++; break }
            if (l and 0xC0 != 0) return null          // компрессия в вопросе не ожидается
            pos++
            if (pos + l > dns.size) return null
            if (sb.isNotEmpty()) sb.append('.')
            sb.append(String(dns, pos, l, Charsets.US_ASCII))
            pos += l
        }
        if (pos + 4 > dns.size) return null
        val qtype = u16(dns, pos)
        return Triple(sb.toString(), qtype, pos + 4)
    }

    // DNS-ответ: копия заголовка/вопроса + (опционально) A-запись с нашим IP.
    private fun buildDns(query: ByteArray, qEnd: Int, answerIp: ByteArray?): ByteArray {
        val out = ByteArrayOutputStream()
        out.write(query[0].toInt() and 0xFF); out.write(query[1].toInt() and 0xFF) // id
        out.write(0x81); out.write(0x80)      // QR=1, RD=1, RA=1, RCODE=0
        out.write(0x00); out.write(0x01)      // qdcount=1
        out.write(0x00); out.write(if (answerIp != null) 1 else 0) // ancount
        out.write(0x00); out.write(0x00)      // nscount
        out.write(0x00); out.write(0x00)      // arcount
        out.write(query, 12, qEnd - 12)       // секция вопроса
        if (answerIp != null) {
            out.write(0xC0); out.write(0x0C)  // указатель на имя (offset 12)
            out.write(0x00); out.write(0x01)  // type A
            out.write(0x00); out.write(0x01)  // class IN
            out.write(0x00); out.write(0x00); out.write(0x00); out.write(0x3C) // TTL=60
            out.write(0x00); out.write(0x04)  // rdlength=4
            out.write(answerIp)
        }
        return out.toByteArray()
    }

    // Оборачивает DNS-ответ в IP+UDP, меняя местами адреса/порты запроса.
    private fun buildIpUdp(req: ByteArray, ihl: Int, dns: ByteArray): ByteArray {
        val udpLen = 8 + dns.size
        val total = 20 + udpLen
        val out = ByteArray(total)
        // IP
        out[0] = 0x45; out[1] = 0
        out[2] = (total ushr 8).toByte(); out[3] = total.toByte()
        out[6] = 0x40                     // DF
        out[8] = 64; out[9] = 17          // TTL, proto=UDP
        // src = исходный dst (sentinel), dst = исходный src (устройство)
        System.arraycopy(req, 16, out, 12, 4)
        System.arraycopy(req, 12, out, 16, 4)
        val ck = checksum(out, 0, 20)
        out[10] = (ck ushr 8).toByte(); out[11] = ck.toByte()
        // UDP: src port = исходный dst (53), dst port = исходный src
        val srcPort = u16(req, ihl); val dstPort = u16(req, ihl + 2)
        out[20] = (dstPort ushr 8).toByte(); out[21] = dstPort.toByte()
        out[22] = (srcPort ushr 8).toByte(); out[23] = srcPort.toByte()
        out[24] = (udpLen ushr 8).toByte(); out[25] = udpLen.toByte()
        out[26] = 0; out[27] = 0          // UDP checksum 0 (для IPv4 допустимо)
        System.arraycopy(dns, 0, out, 28, dns.size)
        return out
    }

    private fun checksum(b: ByteArray, off: Int, len: Int): Int {
        var sum = 0L
        var i = off; var rem = len
        while (rem > 1) { sum += (((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)); i += 2; rem -= 2 }
        if (rem > 0) sum += (b[i].toInt() and 0xFF) shl 8
        while (sum shr 16 != 0L) sum = (sum and 0xFFFF) + (sum shr 16)
        return (sum.inv() and 0xFFFF).toInt()
    }

    // ---------------- сервис ----------------

    private fun stop() {
        running = false
        active = false
        try { tcpProxy?.closeAll() } catch (e: Exception) {}
        try { tun?.close() } catch (e: Exception) {}
        tun = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        running = false
        active = false
        try { tcpProxy?.closeAll() } catch (e: Exception) {}
        try { tun?.close() } catch (e: Exception) {}
        super.onDestroy()
    }
    override fun onRevoke() { stop() }

    private fun notif(text: String): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java)
                .createNotificationChannel(NotificationChannel(CHANNEL, "LocalBox VPN", NotificationManager.IMPORTANCE_LOW))
        }
        val pi = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop=PendingIntent.getService(this,2,Intent(this,LocalVpnService::class.java).setAction(ACTION_STOP),PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("LocalBox VPN активен")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .setContentIntent(pi)
            .addAction(android.R.drawable.ic_media_pause,"Выключить VPN",stop)
            .build()
    }
}
