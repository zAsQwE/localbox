"use strict";

// A game base changed from main/pp7/quiplash3 to main/pp7-quiplash3.
// Keep the actual filename: different hashes must never be substituted.
function layoutPaths(relative) {
    const nested = relative.match(/^main\/(pp\d+|ppad)\/([^/]+)(\/.*)$/);
    if (nested) return [relative, `main/${nested[1]}-${nested[2]}${nested[3]}`];
    const flat = relative.match(/^main\/(pp\d+|ppad)-([^/]+)(\/.*)$/);
    if (flat) return [relative, `main/${flat[1]}/${flat[2]}${flat[3]}`];
    return [relative];
}

module.exports = { layoutPaths };
