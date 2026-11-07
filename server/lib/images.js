"use strict";

// Ecast ImageEntity: a signed PUT,
// image/submit, then image/moderate yields a local download URL.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const express = require("express");
const u = require("./util.js");

const MAX_BYTES = 8 * 1024 * 1024;
function mime(bytes) {
    if (bytes.length < 12) return null;
    if (bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return "image/png";
    if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return "image/jpeg";
    if (bytes.toString("ascii", 0, 4) === "RIFF" && bytes.toString("ascii", 8, 12) === "WEBP") return "image/webp";
    if (/^GIF8[79]a$/.test(bytes.toString("ascii", 0, 6))) return "image/gif";
    return null;
}

class ImageStore {
    constructor(directory = path.join(__dirname, "../storage/images")) {
        this.directory = directory;
        this.uploads = new Map();
    }
    body(entity) {
        return { uploadDetails: entity.uploadDetails, moderationDetails: entity.moderationDetails,
            readyForModeration: entity.readyForModeration };
    }
    remove(entity, erase = true) {
        if (!entity || !entity.imageRecord) return;
        const record = entity.imageRecord;
        this.uploads.delete(record.token);
        if (erase) for (const suffix of [".bin", ".json"]) {
            try { fs.unlinkSync(path.join(this.directory, record.id + suffix)); } catch (error) { if (error.code !== "ENOENT") throw error; }
        }
    }
    closeRoom(room) {
        // Revoke all upload capabilities. Published downloads remain usable in
        // post-game galleries, just like the existing artifact store.
        for (const record of this.uploads.values()) if (record.room === room) this.uploads.delete(record.token);
    }
    handle(client, room, msg) {
        const { opcode, params: p, seq } = msg;
        if (typeof p.key !== "string" || !p.key || p.key.length > 512) return client.sendError(seq, 2004);
        let entity = room.entities[p.key];
        const action = opcode.slice(6);
        if (!["create", "get", "submit", "moderate", "delete"].includes(action)) return client.sendError(seq, 2003);
        if (action === "create") {
            if (!client.isHost) return client.sendError(seq, 2023);
            if (entity) return client.sendError(seq, 2006);
            if ((p.acl != null && (!Array.isArray(p.acl) || p.acl.some(rule => typeof rule !== "string"))) ||
                (p.prefix != null && (typeof p.prefix !== "string" || p.prefix.length > 512)) ||
                (p.mimeType != null && !["image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"].includes(p.mimeType))) return client.sendError(seq, 2004);
            if (Object.values(room.entities).filter(item => item.type === "image").length >= 128) return client.sendError(seq, 2004, "too many images");
            const id = crypto.randomBytes(16).toString("hex"), token = crypto.randomBytes(24).toString("hex");
            // The host downloads moderated images with its own HTTP stack: use the scheme it
            // reached us by. Controllers get their own address via network.stringify.
            const origin = /^https?:\/\//.test(room.serverUrl) ? room.serverUrl : (room.hostScheme || "https") + "://" + room.serverUrl;
            room.createEntity("image", p.key, p.acl ?? ["rw *"], {
                uploadDetails: { uploadUrl: origin + "/localbox/images/upload/" + token, mimeType: p.mimeType || "image/jpeg" },
                moderationDetails: null, readyForModeration: false,
            });
            entity = room.entities[p.key];
            const record = { id, token, room, entity, key: p.key, origin, uploaded: false };
            entity.imageRecord = record;
            this.uploads.set(token, record);
        } else {
            if (!entity) return client.sendError(seq, 2005);
            if (entity.type !== "image") return client.sendError(seq, 2004);
            if (!client.isHost) {
                if (action === "get") {
                    if (!u.aclReadable(entity.acl, client.role, client.profileId)) return client.sendError(seq, 2023);
                } else if (entity.locked || u.aclLockedFor(entity.acl, client.role, client.profileId)) return client.sendError(seq, 2028);
            }
            if (["delete", "moderate"].includes(action) && !client.isHost && client.role !== "moderator") return client.sendError(seq, 2023);
            if (action === "submit") {
                if (typeof p.success !== "boolean") return client.sendError(seq, 2004);
                if (p.success && !entity.imageRecord.uploaded) return client.sendError(seq, 2004, "image has not been uploaded");
                entity.readyForModeration = p.success;
                entity.version++;
                entity.from = client.profileId;
            } else if (action === "moderate") {
                if (!entity.readyForModeration || !entity.imageRecord.uploaded) return client.sendError(seq, 2004, "image is not ready");
                const record = entity.imageRecord;
                // LocalBox has no remote moderation service: make the submitted
                // image available to the host/moderator without a cloud upload.
                entity.moderationDetails = { downloadUrl: record.origin + "/storage/images/" + record.id + "/image.png" };
                entity.version++;
                entity.from = client.profileId;
            } else if (action === "delete") {
                this.remove(entity);
                const acl = entity.acl;
                room.drop(p.key);
                room.sendByAcl(acl, { opcode: "drop", result: { key: p.key } });
                return client.sendOk(seq);
            }
        }
        client.sendEcast({ opcode: "image", result: room.getBody(p.key) }, seq);
        if (action !== "get") room.notify(p.key, !client.isHost, client.profileId);
    }
    mount(app) {
        const raw = express.raw({ type: () => true, limit: MAX_BYTES });
        app.put("/localbox/images/upload/:token", (req, res, next) => {
            const record = this.uploads.get(req.params.token);
            if (!record || record.room.closed || record.room.entities[record.key] !== record.entity) return res.sendStatus(404);
            if (record.entity.locked) return res.sendStatus(423);
            if (record.uploaded) return res.sendStatus(412);
            if (record.busy) return res.sendStatus(409);
            record.busy = true;
            const release = () => { record.busy = false; };
            res.once("close", release);
            raw(req, res, error => {
                if (error) { release(); return res.status(error.status === 413 ? 413 : 400).send({ error: error.status === 413 ? "Изображение больше 8 МБ." : "Не удалось получить изображение." }); }
                // The room may have closed or the entity been deleted while its
                // body was being received. Never resurrect a revoked upload.
                if (!this.uploads.has(record.token) || record.room.closed) return res.sendStatus(410);
                const bytes = req.body;
                const type = Buffer.isBuffer(bytes) && mime(bytes);
                if (!type) return res.status(415).send({ error: "expected a PNG, JPEG, WebP or GIF image" });
                try {
                    fs.mkdirSync(this.directory, { recursive: true });
                    fs.writeFileSync(path.join(this.directory, record.id + ".bin"), bytes, { flag: "wx", mode: 0o600 });
                    fs.writeFileSync(path.join(this.directory, record.id + ".json"), JSON.stringify({ type }), { mode: 0o600 });
                    record.uploaded = true;
                    res.status(201).end();
                } catch (failure) { next(failure); }
            });
        });
        app.get("/storage/images/:id/image.png", (req, res) => {
            if (!/^[a-f0-9]{32}$/.test(req.params.id)) return res.sendStatus(404);
            let meta;
            try { meta = JSON.parse(fs.readFileSync(path.join(this.directory, req.params.id + ".json"), "utf8")); }
            catch { return res.sendStatus(404); }
            res.type(meta.type).set({ "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" });
            res.sendFile(path.join(this.directory, req.params.id + ".bin"));
        });
    }
}

const images = new ImageStore();
module.exports = images;
module.exports.ImageStore = ImageStore;
module.exports.mime = mime;
