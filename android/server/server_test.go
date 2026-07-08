package main

//
// Интеграционный дымовой тест Go-сервера: реальный HTTP+WS сервер, живые Ecast-клиенты.
// Проверяет создание комнаты, welcome хоста/игрока, синхронизацию сущностей, client/send.
// Запуск: go test ./...
//

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func wsURL(ts *httptest.Server, path string) string {
	return "ws" + strings.TrimPrefix(ts.URL, "http") + path
}

func dial(t *testing.T, url string) *websocket.Conn {
	t.Helper()
	d := websocket.Dialer{Subprotocols: []string{"ecast-v0"}, HandshakeTimeout: 3 * time.Second}
	c, _, err := d.Dial(url, nil)
	if err != nil {
		t.Fatalf("dial %s: %v", url, err)
	}
	return c
}

func send(t *testing.T, c *websocket.Conn, m map[string]interface{}) {
	t.Helper()
	b, _ := json.Marshal(m)
	if err := c.WriteMessage(websocket.TextMessage, b); err != nil {
		t.Fatalf("write: %v", err)
	}
}

// readUntil читает сообщения, пока не встретит нужный opcode (или таймаут).
func readUntil(t *testing.T, c *websocket.Conn, opcode string) map[string]interface{} {
	t.Helper()
	c.SetReadDeadline(time.Now().Add(3 * time.Second))
	for {
		_, data, err := c.ReadMessage()
		if err != nil {
			t.Fatalf("ждал opcode %q, ошибка чтения: %v", opcode, err)
		}
		var m map[string]interface{}
		if json.Unmarshal(data, &m) != nil {
			continue
		}
		if m["opcode"] == opcode {
			return m
		}
	}
}

func result(m map[string]interface{}) map[string]interface{} {
	r, _ := m["result"].(map[string]interface{})
	return r
}

func TestEcastCore(t *testing.T) {
	// изоляция глобального состояния
	rooms = map[string]*Room{}
	games = newGames()
	serverURL = "localhost"
	clientDir = ""

	ts := httptest.NewServer(http.HandlerFunc(rootHandler))
	defer ts.Close()

	// 1. создать комнату
	body := map[string]interface{}{"userId": "h1", "appTag": "quiplash2", "appId": "app-x"}
	bb, _ := json.Marshal(body)
	resp, err := http.Post(ts.URL+"/api/v2/rooms", "application/json", strings.NewReader(string(bb)))
	if err != nil {
		t.Fatalf("POST rooms: %v", err)
	}
	var roomResp struct {
		OK   bool `json:"ok"`
		Body struct {
			Code, Token, Host string
		} `json:"body"`
	}
	json.NewDecoder(resp.Body).Decode(&roomResp)
	if !roomResp.OK || len(roomResp.Body.Code) != 4 {
		t.Fatalf("плохой ответ создания комнаты: %+v", roomResp)
	}
	code, token := roomResp.Body.Code, roomResp.Body.Token
	t.Logf("комната %s", code)

	// 2. хост подключается
	host := dial(t, wsURL(ts, "/api/v2/rooms/"+code+"/play?role=host&host-token="+token+"&user-id=h1"))
	defer host.Close()
	hw := readUntil(t, host, "client/welcome")
	if result(hw)["secret"] != token {
		t.Fatalf("welcome хоста без корректного secret: %+v", result(hw))
	}

	// 3. хост создаёт сущность, видимую всем
	send(t, host, map[string]interface{}{"opcode": "object/create", "seq": 1,
		"params": map[string]interface{}{"key": "prompt", "acl": []interface{}{"r *"}, "val": map[string]interface{}{"q": "hi"}}})
	if readUntil(t, host, "ok") == nil {
		t.Fatal("нет ok на object/create")
	}

	// 4. игрок подключается и видит сущность в welcome
	player := dial(t, wsURL(ts, "/api/v2/rooms/"+code+"/play?role=player&name=Bob&user-id=p1"))
	defer player.Close()
	pw := readUntil(t, player, "client/welcome")
	ents, _ := result(pw)["entities"].(map[string]interface{})
	if ents["prompt"] == nil {
		t.Fatalf("игрок не увидел 'prompt' в welcome: %+v", ents)
	}
	if result(pw)["id"] == nil || result(pw)["id"].(float64) < 1 {
		t.Fatalf("у игрока нет profileId: %+v", result(pw))
	}

	// 5. хост обновляет сущность → игрок получает object
	send(t, host, map[string]interface{}{"opcode": "object/update", "seq": 2,
		"params": map[string]interface{}{"key": "prompt", "val": map[string]interface{}{"q": "final"}}})
	upd := readUntil(t, player, "object")
	got, _ := result(upd)["val"].(map[string]interface{})
	if got["q"] != "final" {
		t.Fatalf("игрок получил неверное обновление: %+v", got)
	}

	// 6. игрок шлёт client/send хосту (профиль хоста = 1)
	send(t, player, map[string]interface{}{"opcode": "client/send", "seq": 3,
		"params": map[string]interface{}{"to": 1, "from": result(pw)["id"], "body": map[string]interface{}{"hello": "host"}}})
	cs := readUntil(t, host, "client/send")
	cb, _ := result(cs)["body"].(map[string]interface{})
	if cb["hello"] != "host" {
		t.Fatalf("хост не получил client/send: %+v", result(cs))
	}

	t.Log("Ecast core OK")
}

func TestAudienceLive(t *testing.T) {
	rooms = map[string]*Room{}
	games = newGames()
	serverURL = "localhost"
	clientDir = ""

	ts := httptest.NewServer(http.HandlerFunc(rootHandler))
	defer ts.Close()

	body, _ := json.Marshal(map[string]interface{}{"userId": "h1", "appTag": "trivia", "appId": "t"})
	resp, _ := http.Post(ts.URL+"/api/v2/rooms", "application/json", strings.NewReader(string(body)))
	var rr struct {
		Body struct{ Code, Token string } `json:"body"`
	}
	json.NewDecoder(resp.Body).Decode(&rr)
	code, token := rr.Body.Code, rr.Body.Token

	host := dial(t, wsURL(ts, "/api/v2/rooms/"+code+"/play?role=host&host-token="+token+"&user-id=h1"))
	defer host.Close()
	readUntil(t, host, "client/welcome")

	// включаем зрителей
	send(t, host, map[string]interface{}{"opcode": "room/start-audience", "seq": 1, "params": map[string]interface{}{}})
	readUntil(t, host, "ok")

	// сущность, видимая зрителям
	send(t, host, map[string]interface{}{"opcode": "object/create", "seq": 2,
		"params": map[string]interface{}{"key": "q", "acl": []interface{}{"r *"}, "val": map[string]interface{}{"n": 1}}})
	readUntil(t, host, "ok")

	// зритель заходит и видит сущность
	aud := dial(t, wsURL(ts, "/api/v2/audience/"+code+"/play?role=audience&user-id=a1"))
	defer aud.Close()
	aw := readUntil(t, aud, "client/welcome")
	ents, _ := result(aw)["entities"].(map[string]interface{})
	if ents["q"] == nil {
		t.Fatalf("зритель не увидел сущность: %+v", ents)
	}

	// живое обновление доходит до зрителя (через троттлинг ~150мс)
	send(t, host, map[string]interface{}{"opcode": "object/update", "seq": 3,
		"params": map[string]interface{}{"key": "q", "val": map[string]interface{}{"n": 2}}})
	upd := readUntil(t, aud, "object")
	got, _ := result(upd)["val"].(map[string]interface{})
	if got["n"].(float64) != 2 {
		t.Fatalf("зритель не получил живое обновление: %+v", got)
	}
	t.Log("Audience live OK")
}
