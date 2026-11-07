package tv.localbox.vpn

//
// Экспериментальный TCP-прокси. Совместимость с конкретной игрой проверяется отдельно.
//
// Userspace-TCP форвардер для «прозрачного прокси» VPN: перехватывает TCP-соединения к
// sentinel-IP (10.111.0.3 — на него DNS заворачивает домены Jackbox) и переносит их на
// РЕАЛЬНЫЙ адрес сервера target (напр. 127.0.0.1:9999 на этом же телефоне). Так меняется
// и хост, И ПОРТ — без root.
//
// Реализация минимальная: SYN/ACK/данные/FIN, без ретрансмиссий и окон (для localhost/LAN,
// где потерь почти нет, обычно достаточно). Поток на соединение (блокирующие сокеты).
//
// ⚠ Не лечит TLS/сертификат: для https/wss-игр хост всё равно проверит серт домена Jackbox.
// Такие соединения распознаются по ClientHello и сбрасываются с понятным сообщением (onTls).
//

import android.net.VpnService
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.ConcurrentHashMap
import kotlin.concurrent.thread
import kotlin.random.Random

class TcpProxy(
    private val vpn: VpnService,
    private val write: (ByteArray) -> Unit,   // синхронизированная запись пакета в TUN (в сервисе)
    private val targetHost: String,           // куда переносить (реальный сервер), напр. 127.0.0.1
    private val targetPort: Int,              // порт сервера, напр. 9999
    private val onTls: (Int) -> Unit = {},    // игра начала TLS: сервер LocalBox ответить на него не может
) {
    private val proxyIp = (10 shl 24) or (111 shl 16) or 3   // 10.111.0.3, см. LocalVpnService.PROXY_IP
    private val conns = ConcurrentHashMap<Long, Conn>()
    private val writeLock = Any()

    private fun key(srcIp: Int, srcPort: Int, dstPort: Int): Long =
        (srcIp.toLong() and 0xFFFFFFFFL) shl 32 or ((srcPort.toLong() shl 16) or dstPort.toLong())

    // Один IP-пакет с TCP. pkt[0..len).
    fun handle(pkt: ByteArray, len: Int) {
        if (len < 40) return
        val ihl = (pkt[0].toInt() and 0x0F) * 4
        if (ihl < 20 || ihl+20 > len || be16(pkt, 2) > len || pkt[6].toInt() and 0x3F != 0 || pkt[7].toInt() != 0) return
        val srcIp = be32(pkt, 12); val dstIp = be32(pkt, 16)
        val srcPort = be16(pkt, ihl); val dstPort = be16(pkt, ihl + 2)
        val seq = be32(pkt, ihl + 4); val ack = be32(pkt, ihl + 8)
        val dataOff = ((pkt[ihl + 12].toInt() and 0xF0) ushr 4) * 4
        if (dataOff < 20 || ihl+dataOff > len) return
        val flags = pkt[ihl + 13].toInt() and 0x3F
        val syn = flags and 0x02 != 0; val fin = flags and 0x01 != 0
        val rst = flags and 0x04 != 0; val psh = flags and 0x08 != 0
        val payloadOff = ihl + dataOff
        val payloadLen = len - payloadOff

        // Only the fake IP that DNS gives Jackbox hosts is redirected. Anything else routed into
        // the TUN (e.g. Private DNS probing 10.111.0.1:853) is refused so Android falls back at once.
        if (dstIp != proxyIp) {
            if (!rst) synchronized(writeLock) {
                writeTun(buildTcp(dstIp, srcIp, dstPort, srcPort, if (flags and 0x10 != 0) ack else 0, seq + payloadLen + (if (syn) 1 else 0) + (if (fin) 1 else 0), 0x14, null, 0))
            }
            return
        }
        val k = key(srcIp, srcPort, dstPort)
        var c = conns[k]

        if (rst) { c?.close(); conns.remove(k); return }

        if (syn && c == null) {
            if (conns.size >= 128) return
            // новое соединение: открываем реальный сокет к target и отвечаем SYN-ACK
            c = Conn(srcIp, dstIp, srcPort, dstPort, seq)
            conns[k] = c
            c.start(k)
            return
        }
        if (c == null) {
            // Соединение уже закрыто с нашей стороны: RST, чтобы игра не ждала ответа на FIN/данные.
            if (fin || payloadLen > 0) synchronized(writeLock) { writeTun(buildTcp(dstIp, srcIp, dstPort, srcPort, ack, 0, 0x04, null, 0)) }
            return
        }

        if (payloadLen > 0) {
            c.onClientData(pkt, payloadOff, payloadLen, seq)
        }
        if (fin) {
            c.onClientFin(seq, payloadLen)
        } else if (payloadLen > 0 || psh) {
            // ACK на данные шлём внутри onClientData
        }
    }

    fun closeAll() { conns.values.forEach { it.close() }; conns.clear() }

    // ---------------- одно соединение ----------------

    private inner class Conn(
        val cliIp: Int, val srvIp: Int, val cliPort: Int, val srvPort: Int, cliIsn: Int,
    ) {
        @Volatile private var mySeq = Random.nextInt()   // наш seq (сервер→клиент)
        @Volatile private var theirNext = cliIsn + 1     // ждём от клиента (ack, что шлём)
        private var sock: Socket? = null
        @Volatile private var closed = false
        @Volatile private var firstData = true

        fun start(k: Long) {
            thread(name = "lbx-tcp") {
                try {
                    val s = Socket()
                    sock = s
                    vpn.protect(s)
                    s.connect(InetSocketAddress(targetHost, targetPort), 5000)
                    if (closed) { s.close(); return@thread }
                    // Confirm SYN only after the protected upstream is ready; otherwise
                    // the client's first HTTP/TLS bytes can be silently discarded.
                    sendCtrl(0x12, mySeq, theirNext)
                    mySeq += 1
                    val inp = s.getInputStream()
                    val buf = ByteArray(1400)
                    while (!closed) {
                        val n = inp.read(buf)
                        if (n < 0) {
                            // Сервер закрыл соединение: сообщаем игре FIN, иначе она ждёт конца ответа.
                            if (!closed) { sendCtrl(0x11, mySeq, theirNext); mySeq += 1 }
                            break
                        }
                        sendData(buf, n)              // сервер→клиент
                    }
                } catch (e: Exception) {
                    // не удалось — RST клиенту
                    sendCtrl(0x04, mySeq, theirNext)
                } finally {
                    close(); conns.remove(k)
                }
            }
        }

        fun onClientData(pkt: ByteArray, off: Int, l: Int, seq: Int) {
            if (seq != theirNext) {
                sendCtrl(0x10, mySeq, theirNext)
                return
            }
            if (firstData) {
                firstData = false
                // TLS ClientHello (0x16 0x03 ..): игра проверяет сертификат домена Jackbox.
                // HTTP-порт LocalBox не может на него ответить, а подменить сертификат нельзя.
                if (l >= 3 && pkt[off].toInt() == 0x16 && pkt[off + 1].toInt() == 0x03) {
                    onTls(srvPort)
                    sendCtrl(0x14, mySeq, seq + l)    // RST+ACK
                    close()
                    return
                }
            }
            // пишем в сокет и подтверждаем
            try { sock?.getOutputStream()?.apply { write(pkt, off, l); flush() } ?: return } catch (_: Exception) { close(); return }
            theirNext = seq + l
            sendCtrl(0x10, mySeq, theirNext)          // ACK
        }

        fun onClientFin(seq: Int, payloadLen: Int) {
            theirNext = seq + payloadLen + 1          // FIN занимает 1
            sendCtrl(0x11, mySeq, theirNext)          // FIN+ACK
            mySeq += 1
            close()
        }

        fun sendData(data: ByteArray, n: Int) {
            synchronized(writeLock) {
                val pkt = buildTcp(srvIp, cliIp, srvPort, cliPort, mySeq, theirNext, 0x18, data, n) // PSH+ACK
                writeTun(pkt)
                mySeq += n
            }
        }
        fun sendCtrl(flags: Int, seq: Int, ack: Int) {
            synchronized(writeLock) {
                val pkt = buildTcp(srvIp, cliIp, srvPort, cliPort, seq, ack, flags, null, 0)
                writeTun(pkt)
            }
        }
        fun close() {
            if (closed) return
            closed = true
            try { sock?.close() } catch (_: Exception) {}
        }
    }

    private fun writeTun(pkt: ByteArray) {
        try { write(pkt) } catch (_: Exception) {}
    }

    // ---------------- сборка IP+TCP ----------------

    private fun buildTcp(srcIp: Int, dstIp: Int, srcPort: Int, dstPort: Int,
                         seq: Int, ack: Int, flags: Int, data: ByteArray?, dataLen: Int): ByteArray {
        val tcpLen = 20 + dataLen
        val total = 20 + tcpLen
        val o = ByteArray(total)
        // IP
        o[0] = 0x45; o[2] = (total ushr 8).toByte(); o[3] = total.toByte()
        o[6] = 0x40; o[8] = 64; o[9] = 6                 // TTL, proto TCP
        wbe32(o, 12, srcIp); wbe32(o, 16, dstIp)
        val ick = cksum(o, 0, 20, 0)
        o[10] = (ick ushr 8).toByte(); o[11] = ick.toByte()
        // TCP
        val t = 20
        wbe16(o, t, srcPort); wbe16(o, t + 2, dstPort)
        wbe32(o, t + 4, seq); wbe32(o, t + 8, ack)
        o[t + 12] = 0x50                                 // data offset 20 (5<<4)
        o[t + 13] = flags.toByte()
        wbe16(o, t + 14, 0xFFFF)                         // window
        if (data != null && dataLen > 0) System.arraycopy(data, 0, o, t + 20, dataLen)
        // TCP checksum (псевдо-заголовок + TCP + данные)
        val tck = tcpChecksum(o, srcIp, dstIp, t, tcpLen)
        o[t + 16] = (tck ushr 8).toByte(); o[t + 17] = tck.toByte()
        return o
    }

    private fun tcpChecksum(b: ByteArray, srcIp: Int, dstIp: Int, tcpOff: Int, tcpLen: Int): Int {
        var sum = 0L
        // псевдо-заголовок
        sum += (srcIp ushr 16 and 0xFFFF).toLong(); sum += (srcIp and 0xFFFF).toLong()
        sum += (dstIp ushr 16 and 0xFFFF).toLong(); sum += (dstIp and 0xFFFF).toLong()
        sum += 6L                                        // proto TCP
        sum += tcpLen.toLong()
        var i = tcpOff; var rem = tcpLen
        while (rem > 1) { sum += (((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)).toLong(); i += 2; rem -= 2 }
        if (rem > 0) sum += ((b[i].toInt() and 0xFF) shl 8).toLong()
        while (sum shr 16 != 0L) sum = (sum and 0xFFFF) + (sum shr 16)
        return (sum.inv() and 0xFFFF).toInt()
    }

    private fun cksum(b: ByteArray, off: Int, len: Int, seed: Long): Int {
        var sum = seed; var i = off; var rem = len
        while (rem > 1) { sum += (((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)).toLong(); i += 2; rem -= 2 }
        if (rem > 0) sum += ((b[i].toInt() and 0xFF) shl 8).toLong()
        while (sum shr 16 != 0L) sum = (sum and 0xFFFF) + (sum shr 16)
        return (sum.inv() and 0xFFFF).toInt()
    }

    private fun be16(b: ByteArray, o: Int) = ((b[o].toInt() and 0xFF) shl 8) or (b[o + 1].toInt() and 0xFF)
    private fun be32(b: ByteArray, o: Int) =
        ((b[o].toInt() and 0xFF) shl 24) or ((b[o + 1].toInt() and 0xFF) shl 16) or
        ((b[o + 2].toInt() and 0xFF) shl 8) or (b[o + 3].toInt() and 0xFF)
    private fun wbe16(b: ByteArray, o: Int, v: Int) { b[o] = (v ushr 8).toByte(); b[o + 1] = v.toByte() }
    private fun wbe32(b: ByteArray, o: Int, v: Int) {
        b[o] = (v ushr 24).toByte(); b[o + 1] = (v ushr 16).toByte(); b[o + 2] = (v ushr 8).toByte(); b[o + 3] = v.toByte()
    }
}
