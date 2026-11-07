"use strict";

const fs = require("node:fs");
const tls = require("node:tls");
const path = require("node:path");
const crypto = require("node:crypto");

function read(files, { allowExpired = false } = {}) {
    const options = { cert: fs.readFileSync(files.cert), key: fs.readFileSync(files.key) };
    const certificate = new crypto.X509Certificate(options.cert);
    // Older installations stored only a leaf with the same issuer name on every PC.
    // Send the matching issuer as well, so Firefox need not use a cached, unrelated CA.
    const caFile = files.ca || (path.basename(files.cert) === "localbox.pem" ? path.join(path.dirname(files.cert), "localbox-ca.pem") : null);
    if (caFile && fs.existsSync(caFile)) {
        const caPem = fs.readFileSync(caFile);
        const ca = new crypto.X509Certificate(caPem);
        if (!ca.ca || !certificate.checkIssued(ca) || !certificate.verify(ca.publicKey) || !ca.verify(ca.publicKey)) {
            throw Error("Сертификат HTTPS не подписан текущим LocalBox CA. Обновите сертификат в лаунчере.");
        }
        const chain = options.cert.toString().match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) || [];
        if (!chain.some(pem => new crypto.X509Certificate(pem).fingerprint256 === ca.fingerprint256)) {
            options.cert = Buffer.concat([options.cert, Buffer.from("\n"), caPem]);
        }
    }
    // Validate the complete cert/key pair before changing any listener.
    tls.createSecureContext(options);
    const now = Date.now();
    if (!allowExpired && (now < Date.parse(certificate.validFrom) || now >= Date.parse(certificate.validTo))) throw Error("Сертификат ещё не действует или уже истёк");
    return { options, stamp: crypto.createHash("sha256").update(options.cert).update(options.key).digest("hex") };
}

function publicCa(options) {
    const blocks = String(options.cert).match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) || [];
    if (!blocks.length) return null;
    const leaf = new crypto.X509Certificate(blocks[0]);
    for (const pem of blocks) {
        const ca = new crypto.X509Certificate(pem);
        if (ca.ca && ca.subject === ca.issuer && ca.verify(ca.publicKey) &&
            leaf.checkIssued(ca) && leaf.verify(ca.publicKey)) return Buffer.from(pem + "\n");
    }
    return null;
}

function watch(servers, files, { interval = 1000, log = console.log, initial, onReload } = {}) {
    let stamp = initial?.stamp || read(files).stamp;
    let lastError = "";
    function reload() {
        try {
            const next = read(files);
            if (next.stamp === stamp) return false;
            for (const server of servers) server.setSecureContext(next.options);
            if (onReload) onReload(next);
            stamp = next.stamp;
            lastError = "";
            log("[tls] Обновлён сертификат HTTPS; текущие подключения сохранены.");
            return true;
        } catch (error) {
            // A certificate and key can be replaced in two successive renames.
            // Keep the working context and retry on the next poll.
            if (error.message !== lastError) {
                lastError = error.message;
                log("[tls] Новый сертификат пока не применён: " + error.message);
            }
            return false;
        }
    }
    const timer = setInterval(reload, interval);
    timer.unref();
    const close = () => clearInterval(timer);
    for (const server of servers) server.on("close", () => { if (servers.every(item => !item.listening)) close(); });
    return { reload, close };
}

module.exports = { read, watch, publicCa };
