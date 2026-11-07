"use strict";

// PKCS#10 request for mkcert. Node's native crypto generates the key and signs;
// the small DER encoder only describes the subject and requested SAN extension.
const fs = require("node:fs");
const crypto = require("node:crypto");

function der(tag, bytes) {
    const size = bytes.length;
    const length = size < 128 ? Buffer.from([size]) : (() => {
        const hex = size.toString(16).padStart(Math.ceil(size.toString(16).length / 2) * 2, "0");
        const value = Buffer.from(hex, "hex");
        return Buffer.concat([Buffer.from([0x80 | value.length]), value]);
    })();
    return Buffer.concat([Buffer.from([tag]), length, bytes]);
}
const seq = (...parts) => der(0x30, Buffer.concat(parts));
const oid = hex => der(0x06, Buffer.from(hex, "hex"));

function main() {
    const [csrFile, keyFile] = process.argv.slice(2);
    const request = JSON.parse(fs.readFileSync(0, "utf8"));
    if (!csrFile || !keyFile || typeof request.commonName !== "string" || !Array.isArray(request.sans) || !request.sans.length) {
        throw Error("Invalid LocalBox CSR request");
    }
    const sans = request.sans.map(entry => {
        if (typeof entry.dns === "string" && /^[A-Za-z0-9._-]+$/.test(entry.dns)) {
            return der(0x82, Buffer.from(entry.dns, "ascii"));
        }
        if (typeof entry.ipHex === "string" && /^(?:[a-f0-9]{8}|[a-f0-9]{32})$/.test(entry.ipHex)) {
            return der(0x87, Buffer.from(entry.ipHex, "hex"));
        }
        throw Error("Invalid LocalBox subject alternative name");
    });
    const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
    const subject = seq(der(0x31, seq(oid("550403"), der(0x0c, Buffer.from(request.commonName, "utf8")))));
    const sanExtension = seq(oid("551d11"), der(0x04, seq(...sans)));
    const extensionRequest = seq(oid("2a864886f70d01090e"), der(0x31, seq(sanExtension)));
    const info = seq(Buffer.from([0x02, 0x01, 0x00]), subject,
        publicKey.export({ type: "spki", format: "der" }), der(0xa0, extensionRequest));
    const signature = crypto.sign("sha256", info, privateKey);
    const csr = seq(info, seq(oid("2a864886f70d01010b"), der(0x05, Buffer.alloc(0))),
        der(0x03, Buffer.concat([Buffer.from([0]), signature])));
    const base64 = csr.toString("base64").match(/.{1,64}/g).join("\n");
    fs.writeFileSync(keyFile, privateKey.export({ type: "pkcs8", format: "pem" }), { mode: 0o600, flag: "wx" });
    fs.writeFileSync(csrFile, `-----BEGIN CERTIFICATE REQUEST-----\n${base64}\n-----END CERTIFICATE REQUEST-----\n`, { flag: "wx" });
}

try { main(); }
catch (error) { console.error(error.message); process.exitCode = 1; }
