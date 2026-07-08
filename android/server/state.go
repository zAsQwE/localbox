package main

//
// LocalBox Go-сервер — реестр игр (appId <-> appTag + лимиты) и глобальное состояние.
// Порт server/lib/state.js. Неизвестные игры авто-регистрируются при создании комнаты.
//

type Games struct {
	AppTags    map[string]string `json:"appTags"`    // appTag -> appId
	AppIds     map[string]string `json:"appIds"`     // appId  -> appTag
	MaxPlayers map[string]int    `json:"maxPlayers"` // appTag -> max
	MinPlayers map[string]int    `json:"minPlayers"` // appTag -> min
}

func newGames() *Games {
	return &Games{
		AppTags: map[string]string{}, AppIds: map[string]string{},
		MaxPlayers: map[string]int{}, MinPlayers: map[string]int{},
	}
}

var games = newGames()
var serverURL = "localhost"

// register — авто-регистрация игры из параметров запроса. Возвращает итоговый appTag.
func register(p map[string]interface{}) string {
	appID := str(p["appId"])
	appTag := str(p["appTag"])
	if appTag == "" && appID != "" {
		appTag = games.AppIds[appID]
	}
	if appTag == "" {
		appTag = appID
	}
	if appTag != "" && appID != "" {
		games.AppTags[appTag] = appID
		games.AppIds[appID] = appTag
	}
	if v, ok := toInt(p["maxPlayers"]); ok && v > 0 {
		games.MaxPlayers[appTag] = v
	}
	if v, ok := toInt(p["minPlayers"]); ok && v > 0 {
		games.MinPlayers[appTag] = v
	}
	return appTag
}
