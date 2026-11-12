"use strict";

const net = require("net");

// Controllers can use a different address and port from the game's host.
function address(request, fallback = "localhost") {
    return { host: request.headers.host || fallback, secure: !!request.socket.encrypted };
}

function origin(request, fallback) {
    const { host, secure } = address(request, fallback);
    return `${secure ? "https" : "http"}://${host}`;
}

function stringify(value, client, serverUrl) {
    // Keep the game's configured address; only controllers need the guest's tunnel address.
    if (!client.localboxAddress || client.isHost || client.role === "host") return JSON.stringify(value);
    const { host, secure } = client.localboxAddress;
    return JSON.stringify(value, (_key, item) => {
        if (typeof item !== "string" || !/^https?:\/\//.test(item)) return item;
        try {
            const url = new URL(item);
            if (url.host !== new URL("https://" + serverUrl).host ||
                !/^\/(?:tts|render|storage|artifact|localbox\/images)(?:\/|$)/.test(url.pathname)) return item;
            return `${secure ? "https" : "http"}://${host}${url.pathname}${url.search}${url.hash}`;
        } catch { return item; }
    });
}

// «Свои» адреса: loopback, RFC 1918, link-local, CGNAT/Tailscale (100.64/10), Hamachi (25/8),
// Radmin VPN (26/8), IPv6 ULA/link-local.
function isPrivateAddress(ip) {
    let a = String(ip || "").replace(/^\[|\]$/g, "").toLowerCase();
    if (a.startsWith("::ffff:")) a = a.slice(7);
    if (net.isIPv4(a)) {
        const [x, y] = a.split(".").map(Number);
        return x === 10 || x === 127 || (x === 172 && y >= 16 && y <= 31) || (x === 192 && y === 168) ||
            (x === 169 && y === 254) || (x === 100 && y >= 64 && y <= 127) || x === 25 || x === 26;
    }
    if (net.isIPv6(a)) return a === "::1" || /^f[cd]/.test(a) || /^fe[89ab]/.test(a);
    return false;
}

// Локальный ли адрес сервера (serverUrl): частный IP, localhost или имя .local.
function isLocalHost(host) {
    const h = String(host || "").replace(/:\d+$/, "").replace(/^\[|\]$/g, "").toLowerCase();
    return h === "localhost" || h.endsWith(".local") || isPrivateAddress(h);
}

// Origin с этого же хоста, из локальной сети или из явного списка — прочим CORS не даём.
function trustedOrigin(value, request, extra = new Set()) {
    try {
        const url = new URL(value);
        if (url.host === request.headers.host || extra.has(url.origin)) return true;
        return url.hostname === "localhost" || isPrivateAddress(url.hostname);
    } catch { return false; }
}

module.exports = { address, origin, stringify, isPrivateAddress, isLocalHost, trustedOrigin };
