package main

//
// LocalBox Go-сервер — Blobcast (старый протокол, socket.io 0.9) поверх той же Room/entity-store.
// Порт server/lib/blobcast-ws.js + blobcast.js. Транспорт: '1::' connect, '2:::' heartbeat,
// '5:::{json}' событие, '0::' disconnect.
//

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

var nextBlobID = 5000000

// serveBlobcast — жизненный цикл одного Blobcast-соединения (socket.io 0.9).
func serveBlobcast(conn *websocket.Conn) {
	engineMu.Lock()
	nextBlobID++
	c := &Client{id: nextBlobID, conn: conn, server: "blobcast"}
	engineMu.Unlock()

	c.writeText("1::") // socket.io: соединение установлено
	stop := make(chan struct{})
	go func() {
		t := time.NewTicker(10 * time.Second)
		defer t.Stop()
		for {
			select {
			case <-stop:
				return
			case <-t.C:
				c.writeText("2:::")
			}
		}
	}()

	cleanup := func() {
		engineMu.Lock()
		if r := getRoom(c.roomCode); r != nil {
			r.disconnect(c)
		}
		engineMu.Unlock()
	}

	conn.SetReadLimit(4 << 20)
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			break
		}
		s := string(data)
		if debug && strings.HasPrefix(s, "5") {
			dbg("[bc< %d] %.240s", c.id, s)
		}
		parts := strings.SplitN(s, ":", 3)
		if len(parts) < 3 {
			c.writeText("-1::")
			continue
		}
		switch parts[0] {
		case "0":
			cleanup()
			conn.Close()
			close(stop)
			return
		case "2":
			continue // heartbeat от клиента
		case "5":
			idx := strings.Index(s, "5:::")
			if idx < 0 {
				c.writeText("-1::")
				continue
			}
			var msg map[string]interface{}
			if json.Unmarshal([]byte(s[idx+4:]), &msg) != nil {
				c.writeText("-1::")
				continue
			}
			var args []interface{}
			if a, ok := msg["args"].([]interface{}); ok {
				args = a
			} else if msg["args"] != nil {
				args = []interface{}{msg["args"]}
			}
			for _, raw := range args {
				arg, _ := raw.(map[string]interface{})
				if arg == nil {
					continue
				}
				action := str(arg["action"])
				engineMu.Lock()
				fn := blobActions[action]
				okAction := true
				if fn != nil {
					okAction = fn(c, arg)
				}
				engineMu.Unlock()
				if fn != nil && !okAction {
					c.writeText("-1::")
				}
				// неизвестные действия молча игнорируем
			}
		default:
			c.writeText("-1::")
		}
	}
	cleanup()
	conn.Close()
	select {
	case <-stop:
	default:
		close(stop)
	}
}

type blobAction func(c *Client, msg map[string]interface{}) bool

var blobActions = map[string]blobAction{
	"CreateRoom": func(c *Client, msg map[string]interface{}) bool {
		if c.isHost || c.isPlayer {
			return false
		}
		opts, _ := msg["options"].(map[string]interface{})
		if opts == nil {
			opts = map[string]interface{}{}
		}
		tag := register(map[string]interface{}{"appId": msg["appId"], "appTag": games.AppIds[str(msg["appId"])]})
		room := newRoom(map[string]interface{}{
			"appTag": tag, "appId": msg["appId"], "userId": msg["userId"],
			"forceRoomId": opts["forceRoomId"], "maxPlayers": opts["maxPlayers"], "minPlayers": opts["minPlayers"],
			"audienceEnabled": opts["audienceEnabled"], "password": opts["password"],
		}, serverURL, games)
		addRoom(room)
		c.roomCode = room.code
		c.userID = str(msg["userId"])
		c.isHost = true
		room.connect(c, str(msg["userId"]), "", "host", "blobcast")
		room.setEntity("object", "bc:room", []string{"r *"}, map[string]interface{}{"val": map[string]interface{}{}})
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "CreateRoom", "success": true, "roomId": room.code})
		logf("[blobcast] room %s for %s host userId: %s", room.code, tag, str(msg["userId"]))
		return true
	},
	"JoinRoom": func(c *Client, msg map[string]interface{}) bool {
		if c.isHost || c.isPlayer {
			return false
		}
		room := getRoom(str(msg["roomId"]))
		if room == nil {
			return false
		}
		c.userID = str(msg["userId"])
		joinType := str(msg["joinType"])
		if joinType == "" {
			joinType = "player"
		}
		if joinType != "player" {
			return false // зрители — позже
		}
		known := room.findByUserID(c.userID) != nil
		if room.locked && !known {
			return false
		}
		if room.isFull() && !known {
			return false
		}
		room.connect(c, c.userID, str(msg["name"]), "player", "blobcast")
		c.roomCode = str(msg["roomId"])
		c.isPlayer = true
		logf("[blobcast] игрок вошёл в комнату %s (%s)", c.roomCode, str(msg["name"]))
		if self := room.findByUserID(c.userID); self != nil {
			if b := room.get("bc:room"); b != nil {
				room.sendTo(self.profileID, map[string]interface{}{"opcode": "object", "result": b}, nil, "")
			}
			ckey := "bc:customer:" + c.userID
			if b := room.get(ckey); b != nil {
				room.sendTo(self.profileID, map[string]interface{}{"opcode": "object", "result": b}, nil, "")
			}
		}
		return true
	},
	"SetRoomBlob": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isHost || room == nil {
			return false
		}
		room.updateEntity("bc:room", map[string]interface{}{"val": msg["blob"]}, 0)
		room.notify("bc:room", false, 0)
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "SetRoomBlob", "success": true})
		return true
	},
	"SetCustomerBlob": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isHost || room == nil {
			return false
		}
		key := "bc:customer:" + str(msg["customerUserId"])
		if room.get(key) == nil {
			acl := []string{"r *"}
			if target := room.findByUserID(str(msg["customerUserId"])); target != nil {
				acl = []string{"r id:" + itoa(target.profileID)}
			}
			room.setEntity("object", key, acl, map[string]interface{}{"val": map[string]interface{}{}})
		}
		room.updateEntity(key, map[string]interface{}{"val": msg["blob"]}, 0)
		room.notify(key, false, 0)
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "SetCustomerBlob", "success": true})
		return true
	},
	"LockRoom": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isHost || room == nil {
			return false
		}
		room.locked = true
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "LockRoom", "success": true, "roomId": c.roomCode})
		return true
	},
	"StartSession": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isHost || room == nil {
			return false
		}
		module := str(msg["module"])
		resp := map[string]interface{}{}
		switch module {
		case "audience":
			room.audienceEnabled = true
			resp = map[string]interface{}{"count": room.audienceCount}
		}
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "StartSession", "module": module,
			"name": msg["name"], "success": true, "response": resp})
		return true
	},
	"GetSessionStatus": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isHost || room == nil {
			return false
		}
		module := str(msg["module"])
		resp := map[string]interface{}{}
		if module == "audience" {
			resp = map[string]interface{}{"count": room.audienceCount}
		} else if module == "comment" {
			resp = map[string]interface{}{"comments": []interface{}{}}
		}
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "GetSessionStatus", "module": module,
			"name": msg["name"], "success": true, "response": resp})
		return true
	},
	"StopSession": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isHost || room == nil {
			return false
		}
		module := str(msg["module"])
		if name := str(msg["name"]); name != "" {
			room.drop(name)
		}
		c.sendBlob(map[string]interface{}{"type": "Result", "action": "StopSession", "module": module,
			"name": msg["name"], "success": true, "response": map[string]interface{}{}})
		return true
	},
	"SendMessageToRoomOwner": func(c *Client, msg map[string]interface{}) bool {
		room := getRoom(c.roomCode)
		if !c.isPlayer || room == nil {
			return false
		}
		self := room.findByUserID(c.userID)
		if self == nil || room.host == nil {
			return false
		}
		room.send(self.profileID, room.host.profileID, msg["message"])
		return true
	},
}

// ---------------- HTTP-маршруты Blobcast ----------------

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// blobcastHTTP пытается обработать HTTP-запрос Blobcast. Возвращает true, если обработал.
func blobcastHTTP(w http.ResponseWriter, req *http.Request) bool {
	path := req.URL.Path
	switch {
	case path == "/crossdomain.xml":
		w.Header().Set("Content-Type", "application/xml")
		w.Write([]byte("<!DOCTYPE cross-domain-policy SYSTEM \"http://www.macromedia.com/xml/dtds/cross-domain-policy.dtd\">\n<cross-domain-policy>\n\t<allow-access-from domain=\"*\" to-ports=\"*\" />\n</cross-domain-policy>"))
		return true
	case path == "/socket.io/1" || path == "/socket.io/1/":
		// Любой метод: Steam-хост шлёт GET, Android/AIR-версия — POST /socket.io/1/ .
		// Только транспорт websocket (только его мы поддерживаем через upgrade).
		token := makeToken(24)
		w.Header().Set("Content-Type", "text/plain")
		w.Header().Set("Set-Cookie", "socket.io.sid="+token+"; Max-Age=3600")
		w.Write([]byte(token + ":60:60:websocket"))
		return true
	case path == "/room" && req.Method == "GET":
		writeJSON(w, 200, map[string]interface{}{"create": true, "server": serverURL})
		return true
	case strings.HasPrefix(path, "/room/") && req.Method == "GET":
		code := strings.TrimPrefix(path, "/room/")
		engineMu.Lock()
		room := getRoom(code)
		if room == nil {
			engineMu.Unlock()
			writeJSON(w, 404, map[string]interface{}{"success": false, "error": "Invalid Room Code"})
			return true
		}
		joinAs := "player"
		if room.isFull() || room.locked {
			if room.findByUserID(req.URL.Query().Get("userId")) != nil {
				joinAs = "player"
			} else if room.audienceEnabled {
				joinAs = "audience"
			} else {
				joinAs = "full"
			}
		}
		body := map[string]interface{}{
			"roomid": room.code, "server": serverURL, "apptag": room.appTag, "appid": room.appID,
			"numAudience": room.audienceCount, "audienceEnabled": room.audienceEnabled, "joinAs": joinAs,
			"requiresPassword": room.password != "",
		}
		engineMu.Unlock()
		writeJSON(w, 200, body)
		return true
	case path == "/accessToken" && req.Method == "POST":
		b := readBody(req)
		for _, f := range []string{"roomId", "appId", "userId"} {
			if b[f] == nil {
				writeJSON(w, 400, map[string]interface{}{"success": false, "error": "missing required parameter: " + f})
				return true
			}
		}
		engineMu.Lock()
		room := getRoom(str(b["roomId"]))
		engineMu.Unlock()
		if room == nil {
			writeJSON(w, 400, map[string]interface{}{"success": false, "error": "can't create access token for non-existent room"})
			return true
		}
		if room.hostUserID != str(b["userId"]) {
			logf("[accessToken] userId не совпал (host=%s, req=%s) — токен всё равно выдан", room.hostUserID, str(b["userId"]))
		}
		writeJSON(w, 200, map[string]interface{}{"success": true, "accessToken": room.token})
		return true
	case path == "/artifact" && req.Method == "POST":
		b := readBody(req)
		for _, f := range []string{"appId", "categoryId", "userId", "blob"} {
			if b[f] == nil {
				writeJSON(w, 400, map[string]interface{}{"success": false, "error": "missing required parameter: " + f})
				return true
			}
		}
		id := artifactCreate(str(b["categoryId"]), b["blob"])
		writeJSON(w, 200, map[string]interface{}{"success": true, "artifactId": id, "categoryId": b["categoryId"], "rootId": "jbg-blobcast-artifacts"})
		return true
	case strings.HasPrefix(path, "/artifact/") && req.Method == "GET":
		seg := strings.Split(strings.TrimPrefix(path, "/artifact/"), "/")
		if len(seg) == 2 {
			if blob := artifactGet(seg[0], seg[1]); blob != nil {
				w.Header().Set("Content-Type", "application/json")
				w.Write(blob)
				return true
			}
			writeJSON(w, 404, map[string]interface{}{"success": false, "error": "The specified key does not exist."})
			return true
		}
	case path == "/storage/content" && req.Method == "POST":
		b := readBody(req)
		for _, f := range []string{"appId", "categoryId", "userId"} {
			if b[f] == nil {
				writeJSON(w, 400, map[string]interface{}{"success": false, "error": "missing required parameter: " + f})
				return true
			}
		}
		dir := filepath.Join(storageDir, "content")
		_ = os.MkdirAll(dir, 0o755)
		id := makeCode() + makeCode()
		doc := map[string]interface{}{"appId": b["appId"], "blob": b["blob"], "categoryId": b["categoryId"],
			"creator": orDefault(b["creator"], map[string]interface{}{}), "metadata": orDefault(b["metadata"], map[string]interface{}{}),
			"userId": b["userId"], "createdTime": time.Now().UnixMilli(), "downloads": 0}
		data, _ := json.Marshal(doc)
		_ = os.WriteFile(filepath.Join(dir, id+".json"), data, 0o644)
		out := map[string]interface{}{"success": true, "contentId": id}
		for k, v := range doc {
			out[k] = v
		}
		writeJSON(w, 200, out)
		return true
	}
	return false
}

func readBody(req *http.Request) map[string]interface{} {
	m := map[string]interface{}{}
	if req.Body != nil {
		_ = json.NewDecoder(req.Body).Decode(&m)
	}
	return m
}
