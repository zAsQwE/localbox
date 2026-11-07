"use strict";

// Jackbox Party Pack 12 games. Supported by default; LOCALBOX_ENABLE_PACK12=0
// keeps them out of automatic registration and room creation.
const disabledGames = [
    ["debate", "ddfcd195-87c4-4406-8204-cbc207eff862"],
    ["grating-cards", "c9e20e6f-3f4f-4873-bca6-01b72eb30104", "gratingcards"],
    ["megafriends", "5d8a382d-6f60-4339-928b-df611241c29f"],
    ["reaction", "9c5f38c5-3677-497c-b808-8628805e8096", "reactiongame"],
    ["processing", "e9e566b0-4304-4935-920f-4c0aa0c7742f", "wordprocessing"],
];
const disabled = new Set(disabledGames.flat());
const message = "Jackbox Party Pack 12 is disabled on this server (LOCALBOX_ENABLE_PACK12=0).";
function enabled() { return process.env.LOCALBOX_ENABLE_PACK12 !== "0"; }
function isPack12(tag, id) {
    return [tag, id].some(value => typeof value === "string" && disabled.has(value.trim().toLowerCase()));
}
function isDisabled(tag, id) { return !enabled() && isPack12(tag, id); }
function registerGames(games) {
    if (!enabled()) return;
    const minimum = { debate: 2, "grating-cards": 3, megafriends: 3, reaction: 3, processing: 2 };
    for (const [tag, id] of disabledGames) {
        games.appTags[tag] ??= id;
        games.appIds[id] ??= tag;
        games.minPlayers[tag] ??= minimum[tag];
        games.maxPlayers[tag] ??= 8;
    }
}
module.exports = { isDisabled, isPack12, enabled, registerGames, message };
