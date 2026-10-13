"use strict";

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
                !/^\/(?:tts|render|storage|artifact)(?:\/|$)/.test(url.pathname)) return item;
            return `${secure ? "https" : "http"}://${host}${url.pathname}${url.search}${url.hash}`;
        } catch { return item; }
    });
}

module.exports = { address, origin, stringify };
