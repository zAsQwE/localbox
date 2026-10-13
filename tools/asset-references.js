"use strict";

const path = require("node:path");
const { layoutPaths } = require("../server/lib/client-paths.js");
const EXTENSIONS = new Set([
    ".html", ".js", ".mjs", ".css", ".json", ".jet", ".map", ".webmanifest",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".ogg", ".wav", ".m4a", ".mp4", ".webm",
]);
const TEXT = new Set([".html", ".js", ".mjs", ".css", ".json", ".jet", ".webmanifest"]);

// Both client generations describe controllers as {file, css, base}. Read literals only:
// never evaluate JavaScript supplied by a downloaded client.
function bundleReferences(source) {
    const paths = [];
    const remainder = source.replace(/\{[^{}]*\}/g, (object) => {
        const property = (name) => object.match(new RegExp('(?:^|[,\\s{])(?:["\']?' + name + '["\']?)\\s*:\\s*(["\'])([^"\']+)\\1'))?.[2];
        const base = property("base"), file = property("file");
        if (!base || !file || !/^main\//.test(base) || /[\\\0]|(?:^|\/)\.\.?(?:\/|$)/.test(base + "/" + file)) return object;
        paths.push(base.replace(/\/+$/, "") + "/" + file);
        const css = object.match(/(?:^|[,\s{])["']?css["']?\s*:\s*\[([^\]]*)\]/)?.[1] || "";
        for (const match of css.matchAll(/["']([^"']+)["']/g)) paths.push(base.replace(/\/+$/, "") + "/" + match[1]);
        return " "; // Do not interpret file/css fragments as paths relative to the root script.
    });
    return { paths, remainder };
}

// Read dependencies from the downloaded build. Asset hashes can differ between translations.
function references(source, relative, host) {
    const ext = path.posix.extname(relative).toLowerCase();
    if (!TEXT.has(ext)) return [];
    const origin = new URL("https://" + host);
    const base = new URL("/" + relative, origin);
    const candidates = [];
    if (ext === ".css") {
        source = source.replace(/\/\*[\s\S]*?\*\//g, "");
        for (const match of source.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi)) candidates.push(match[1] ?? match[2] ?? match[3]);
        for (const match of source.matchAll(/@import\s+["']([^"']+)["']/gi)) candidates.push(match[1]);
    } else if (ext === ".html") {
        for (const match of source.matchAll(/\b(?:src|href)\s*=\s*["']([^"']+)["']/gi)) candidates.push(match[1]);
    } else {
        const bundles = bundleReferences(source);
        candidates.push(...bundles.paths);
        source = bundles.remainder;
        // Quoted asset paths, including new URL("main/...", self.location) and dynamic imports.
        for (const match of source.matchAll(/["'`]([^"'`\r\n]+)["'`]/g)) candidates.push(match[1].replace(/\\\//g, "/"));
    }
    const out = new Set();
    for (let candidate of candidates) {
        candidate = candidate.trim();
        if (!candidate || /[\\\0{}<>]/.test(candidate) || /^(?:data|blob|javascript):/i.test(candidate)) continue;
        try {
            // Some controller scripts build these relative to the site's root, not the script URL.
            const siteRelative = ext !== ".css" && /^(?:main|mods|the_box|general)\//.test(candidate);
            const url = new URL(candidate, siteRelative ? origin : base);
            if (url.origin !== origin.origin) continue;
            const name = decodeURIComponent(url.pathname).replace(/^\/+/, "");
            if (/[\\\0:]/.test(name) || name.split("/").some((part) => part.startsWith("."))) continue;
            // Controller bundles mention SPA entry pages as navigation targets, not asset imports.
            if ((ext === ".js" || ext === ".mjs") && /\.html?$/i.test(name)) continue;
            if (!EXTENSIONS.has(path.posix.extname(name).toLowerCase())) continue;
            out.add(name);
        } catch { /* Ignore incomplete templates and invalid URLs. */ }
    }
    return [...out];
}

module.exports = { references, layoutPaths, TEXT };
