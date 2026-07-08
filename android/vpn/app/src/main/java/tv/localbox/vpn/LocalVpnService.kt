package tv.localbox.vpn

//
// Локальный VPN, который ПОДМЕНЯЕТ DNS: на запрос домена Jackbox отвечает заданным IP,
// остальные домены форвардит настоящему DNS (1.1.1.1). Так немодифицированная игра
// подключается к «ecast.jackboxgames.com» и т.п., но по факту идёт на твой сервер.
//
// Схема: VpnService отдаёт системе адрес DNS = SENTINEL и маршрутит через TUN ТОЛЬКО его.
// Значит через нас идут лишь DNS-пакеты; сам игровой трафик (TCP на твой IP) идёт обычной сетью.
//
// ВАЖНО (честно): это подмена «домен → IP», НЕ порт и НЕ TLS.
//  • Сервер должен отвечать на том порту, что использует игра. Termux без root не займёт 80/443 —
//    для старых Flash-игр это обычно http; если игра лезет на 443, нужен порт-форвард/переключение.
//  • Если игра ходит по https/wss с проверкой сертификата на домен Jackbox — подмена IP не пройдёт
//    (сертификат не совпадёт). Работает для игр по http (старые паки).
//

import android.app.*
import android.content.Intent
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
        const val CHANNEL = "localboxvpn"
        private const val SENTINEL = "10.111.0.1"   // «наш» DNS-адрес внутри TUN
        private const val VPN_ADDR = "10.111.0.2"
        private const val UPSTREAM = "1.1.1.1"       // куда форвардим не-Jackbox запросы

        private val SUFFIXES = listOf("jackboxgames.com", "jackbox.tv", "jackbox.ru", "jackbox.fun")
        fun isJackbox(host: String): Boolean {
            val h = host.lowercase()
            if (SUFFIXES.any { h == it || h.endsWith(".$it") }) return true
            return h.contains("jackbox")
        }
    }

    private var tun: ParcelFileDescriptor? = null
    @Volatile private var running = false
    private var targetIp = ByteArray(4)

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stop(); return START_NOT_STICKY
        }
        val ipStr = intent?.getStringExtra(EXTRA_IP)?.substringBefore(":")?.trim() ?: return START_NOT_STICKY
        val parsed = parseIp(ipStr) ?: run { stop(); return START_NOT_STICKY }
        targetIp = parsed
        startForeground(1, notif("Домены Jackbox → $ipStr"))
        startVpn()
        return START_STICKY
    }

    private fun startVpn() {
        if (running) return
        val b = Builder()
            .setSession("LocalBox VPN")
            .addAddress(VPN_ADDR, 32)
            .addDnsServer(SENTINEL)
            .addRoute(SENTINEL, 32)     // через TUN идёт ТОЛЬКО DNS к sentinel
        b.setBlocking(true)
        tun = b.establish() ?: return
        running = true
        thread(name = "localbox-vpn") { loop() }
    }

    private fun loop() {
        val fd = tun!!.fileDescriptor
        val input = FileInputStream(fd)
        val output = FileOutputStream(fd)
        val buf = ByteArray(32767)
        while (running) {
            val n = try { input.read(buf) } catch (e: Exception) { break }
            if (n <= 0) continue
            val resp = try { handle(buf, n) } catch (e: Exception) { null } ?: continue
            try { output.write(resp) } catch (e: Exception) { break }
        }
    }

    // Обрабатывает один IP-пакет. Возвращает готовый ответный пакет или null.
    private fun handle(pkt: ByteArray, len: Int): ByteArray? {
        if (len < 28) return null
        val version = (pkt[0].toInt() and 0xF0) ushr 4
        if (version != 4) return null              // IPv6 не трогаем
        val ihl = (pkt[0].toInt() and 0x0F) * 4
        if (pkt[9].toInt() and 0xFF != 17) return null   // только UDP
        val dstPort = u16(pkt, ihl + 2)
        if (dstPort != 53) return null              // только DNS

        val dns = pkt.copyOfRange(ihl + 8, len)
        val q = parseQuestion(dns) ?: return null
        val (name, qtype, qEnd) = q

        val dnsResp: ByteArray = if (isJackbox(name)) {
            if (qtype == 1) buildDns(dns, qEnd, targetIp)       // A → наш IP
            else buildDns(dns, qEnd, null)                       // AAAA и пр. → пусто (клиент возьмёт A)
        } else {
            forward(dns) ?: return null                          // остальное — настоящему DNS
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

    private fun parseIp(s: String): ByteArray? {
        val parts = s.split(".")
        if (parts.size != 4) return null
        val out = ByteArray(4)
        for (i in 0..3) {
            val v = parts[i].toIntOrNull() ?: return null
            if (v !in 0..255) return null
            out[i] = v.toByte()
        }
        return out
    }

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
        try { tun?.close() } catch (e: Exception) {}
        tun = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() { running = false; try { tun?.close() } catch (e: Exception) {}; super.onDestroy() }
    override fun onRevoke() { stop() }

    private fun notif(text: String): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java)
                .createNotificationChannel(NotificationChannel(CHANNEL, "LocalBox VPN", NotificationManager.IMPORTANCE_LOW))
        }
        val pi = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("LocalBox VPN активен")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .setContentIntent(pi)
            .build()
    }
}
