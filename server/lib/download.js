"use strict";

const fs = require("fs");
const path = require("path");
const https = require("https");
const { pipeline } = require("stream/promises");
const { randomBytes } = require("crypto");

// Publish only complete downloads. Unique temporary files also permit concurrent requests.
async function download(options, destination) {
    const tmp = destination + "." + randomBytes(8).toString("hex") + ".part";
    try {
        await fs.promises.mkdir(path.dirname(destination), { recursive: true });
        const response = await new Promise((resolve, reject) => {
            const req = https.get(options, resolve);
            req.on("error", reject);
            req.setTimeout(20000, () => req.destroy(new Error("download timeout")));
        });
        if (response.statusCode !== 200) {
            response.resume();
            return { ok: false, status: response.statusCode };
        }
        if (/text\/html/i.test(response.headers["content-type"] || "") && !/\.html?$/i.test(destination)) {
            response.resume();
            return { ok: false, error: "HTML received instead of an asset" };
        }
        await pipeline(response, fs.createWriteStream(tmp));
        await fs.promises.rename(tmp, destination);
        return { ok: true };
    } catch (e) {
        return { ok: false, error: e.message };
    } finally {
        await fs.promises.unlink(tmp).catch(() => {});
    }
}

module.exports = download;
