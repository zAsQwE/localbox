"use strict";
//
// LocalBox server — общий реестр игр и адрес сервера (нужен и Ecast, и Blobcast).
//

const state = {
    serverUrl: "localhost",
    games: { appTags: {}, appIds: {}, maxPlayers: {}, minPlayers: {} },

    // Регистрирует игру (auto-register неизвестных). Возвращает appTag.
    register(p) {
        const tag = p.appTag || (p.appId && this.games.appIds[p.appId]) || p.appId;
        if (!tag) return null;
        if (!this.games.appTags[tag]) {
            this.games.appTags[tag] = p.appId || tag;
            if (p.appId) this.games.appIds[p.appId] = tag;
            if (this.games.maxPlayers[tag] == null) this.games.maxPlayers[tag] = p.maxPlayers || 8;
            if (this.games.minPlayers[tag] == null) this.games.minPlayers[tag] = p.minPlayers || 1;
        }
        return tag;
    },
};

module.exports = state;
