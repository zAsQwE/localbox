"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function plainText(value) {
    return String(value || " ").replace(/<[^>]*>/g, " ")
        .replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (whole, entity) => {
            const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
            if (entity[0] !== "#") return named[entity.toLowerCase()] || whole;
            const number = entity[1].toLowerCase() === "x" ? parseInt(entity.slice(2), 16) : Number(entity.slice(1));
            return number > 0 && number <= 0x10ffff ? String.fromCodePoint(number) : " ";
        }).normalize("NFC").replace(/\s+/g, " ").trim().slice(0, 900) || " ";
}

/** One CPU job at a time. Requested speech jumps ahead of queued predictions. */
class SpeechCache {
    constructor({ directory, signature, render, maxPending = 64, maxFiles = 512, maxBytes = 256 * 1024 * 1024 }) {
        Object.assign(this, { directory, signature, render, maxPending, maxFiles, maxBytes });
        this.jobs = new Map(); this.queue = []; this.active = null; this.closed = false;
        this.lastPrune = 0;
    }
    createOwner() { return { id: crypto.randomBytes(16).toString("hex"), closed: false }; }
    key(text, rate, owner = null) {
        const prefix = owner ? "match-" + owner.id + "-" : "";
        return prefix + "cached-" + crypto.createHash("sha256").update(JSON.stringify([this.signature, text, rate])).digest("hex");
    }
    cached(key) {
        for (const ext of [".mp3", ".wav"]) {
            try {
                const stat = fs.statSync(path.join(this.directory, key + ext));
                if (stat.isFile() && stat.size > 44 && Date.now() - stat.mtimeMs < 7 * 86400000) return key + ext;
            } catch { /* no cached audio */ }
        }
        return null;
    }
    request(text, rate, { background = false, scope = null, owner = null } = {}) {
        if (this.closed) return Promise.reject(new Error("TTS остановлен"));
        if (owner && owner.closed) return Promise.reject(new Error("Партия завершена"));
        text = plainText(text);
        const key = this.key(text, rate, owner), existing = this.jobs.get(key);
        if (existing) {
            if (!background) existing.foreground = true;
            if (scope) existing.scopes.add(scope);
            return existing.promise;
        }
        const hit = this.cached(key);
        if (hit) return Promise.resolve(hit);
        if (this.queue.length >= this.maxPending) {
            const victim = !background && this.queue.find((job) => !job.foreground);
            if (victim) this.remove(victim, "Предзагрузка уступила место озвучке");
            else return Promise.reject(new Error("Очередь TTS заполнена"));
        }
        const job = { key, text, rate, owner, foreground: !background, scopes: new Set(scope ? [scope] : []) };
        job.promise = new Promise((resolve, reject) => { job.resolve = resolve; job.reject = reject; });
        this.jobs.set(key, job); this.queue.push(job);
        setImmediate(() => this.pump());
        return job.promise;
    }
    remove(job, reason) {
        this.queue = this.queue.filter((item) => item !== job);
        this.jobs.delete(job.key); job.reject(new Error(reason));
    }
    cancelScope(scope) {
        for (const job of [...this.queue]) {
            job.scopes.delete(scope);
            if (!job.foreground && !job.scopes.size) this.remove(job, "Предзагрузка комнаты отменена");
        }
    }
    async unlink(file, attempt = 0) {
        try { await fs.promises.unlink(file); }
        catch (error) {
            if (error.code === "ENOENT") return;
            // Windows may briefly keep the audio stream or antivirus handle open.
            if (["EBUSY", "EPERM", "EACCES"].includes(error.code) && attempt < 5) {
                await new Promise((resolve) => setTimeout(resolve, 50 * 2 ** attempt));
                return this.unlink(file, attempt + 1);
            }
            throw error;
        }
    }
    async removeAudio(name) {
        // Include a partial WAV left by a failed engine or MP3 conversion.
        const base = path.basename(name, path.extname(name));
        await Promise.all([".wav", ".mp3"].map((ext) => this.unlink(path.join(this.directory, base + ext))));
    }
    releaseOwner(owner) {
        if (!owner) return Promise.resolve();
        if (owner.cleanup) return owner.cleanup;
        owner.closed = true;
        for (const job of [...this.queue]) if (job.owner === owner) this.remove(job, "Партия завершена");
        const pending = this.active && this.active.owner === owner ? this.active.promise.catch(() => {}) : Promise.resolve();
        owner.cleanup = pending.then(async () => {
            const prefix = "match-" + owner.id + "-";
            const names = await fs.promises.readdir(this.directory).catch((error) => {
                if (error.code !== "ENOENT") throw error;
                return [];
            });
            await Promise.all(names.filter((name) => name.startsWith(prefix) && /^(?:cached-[a-f\d]{64}|temp-[a-f\d]{16})\.(mp3|wav)$/.test(name.slice(prefix.length)))
                .map((name) => this.unlink(path.join(this.directory, name))));
        });
        return owner.cleanup;
    }
    async pump() {
        if (this.active || this.closed || !this.queue.length) return;
        const urgent = this.queue.findIndex((job) => job.foreground);
        const job = this.queue.splice(urgent < 0 ? 0 : urgent, 1)[0];
        this.active = job;
        try {
            const result = await this.render(job.text, job.rate, job);
            let name = result.file;
            if (job.owner && job.owner.closed) {
                await this.removeAudio(name);throw new Error("Партия завершена");
            }
            if (result.cacheable || job.owner) {
                const ext = path.extname(name);
                if (![".mp3", ".wav"].includes(ext)) throw new Error("Некорректный формат TTS");
                const destination = result.cacheable ? job.key + ext : "match-" + job.owner.id + "-temp-" + crypto.randomBytes(8).toString("hex") + ext;
                await fs.promises.rename(path.join(this.directory, name), path.join(this.directory, destination));
                name = destination;
            }
            // releaseOwner can run while rename awaits the filesystem.
            if (job.owner && job.owner.closed) {
                await this.removeAudio(name);throw new Error("Партия завершена");
            }
            job.resolve(name);
        } catch (error) { job.reject(error); }
        finally {
            this.jobs.delete(job.key); this.active = null;
            if (Date.now() - this.lastPrune > 60000) {
                this.lastPrune = Date.now(); this.prune().catch(() => {});
            }
            setImmediate(() => this.pump());
        }
    }
    async prune() {
        const names = await fs.promises.readdir(this.directory).catch(() => []);
        const files = [];
        for (const name of names) {
            if (!/^(?:(?:match-[a-f\d]{32}-)?cached-[a-f\d]{64}|match-[a-f\d]{32}-temp-[a-f\d]{16})\.(mp3|wav)$/.test(name)) continue;
            try { const stat = await fs.promises.stat(path.join(this.directory, name)); if (stat.isFile()) files.push({ name, size: stat.size, time: stat.mtimeMs }); } catch { }
        }
        files.sort((a, b) => a.time - b.time);
        let total = files.reduce((sum, file) => sum + file.size, 0), count = files.length;
        for (const file of files) {
            if (count <= this.maxFiles && total <= this.maxBytes && Date.now() - file.time < 7 * 86400000) break;
            await fs.promises.unlink(path.join(this.directory, file.name)).catch(() => {});
            total -= file.size; count--;
        }
    }
    close() {
        this.closed = true;
        for (const job of [...this.queue]) this.remove(job, "TTS остановлен");
    }
}

module.exports = { SpeechCache, plainText };
