package main

//
// LocalBox Go-сервер — обработка WebSocket-соединений Ecast (роли, welcome, диспетчер опкодов).
// Порт server/lib/ws.js. Типы сущностей: object/text/number/doodle. text-map (CRDT) и TTS
// в этой Android-сборке НЕ поддержаны (см. README).
//

import (
	"encoding/json"
	"strings"

	"github.com/gorilla/websocket"
)

var nextEcastID = 1000000

// не отвечаем "ok" на эти опкоды (они сами шлют ответ)
var noOk = map[string]bool{
	"object/get": true, "text/get": true, "number/get": true, "doodle/get": true,
	"room/get-audience": true, "room/exit": true, "echo": true,
}

func buildContent(typ, action string, p map[string]interface{}) map[string]interface{} {
	switch typ {
	case "object":
		val := p["val"]
		if val == nil {
			val = map[string]interface{}{}
		}
		return map[string]interface{}{"val": val}
	case "text":
		val := p["val"]
		if val == nil {
			val = ""
		}
		c := map[string]interface{}{"val": val}
		if action == "create" && p["accept"] != nil {
			c["accept"] = p["accept"]
		}
		return c
	case "number":
		if action == "create" || action == "set" {
			val := p["val"]
			if val == nil {
				val = float64(0)
			}
			restr := map[string]interface{}{
				"increment": orDefault(p["increment"], float64(0)),
				"type":      orDefault(p["type"], "int"),
			}
			if p["max"] != nil {
				restr["max"] = p["max"]
			}
			if p["min"] != nil {
				restr["min"] = p["min"]
			}
			return map[string]interface{}{"val": val, "restrictions": restr}
		}
		return map[string]interface{}{"val": p["val"]}
	case "doodle":
		if action == "create" {
			size := p["size"]
			if size == nil {
				size = map[string]interface{}{"width": 0, "height": 0}
			}
			return map[string]interface{}{"val": map[string]interface{}{
				"colors": p["colors"], "lines": []interface{}{}, "live": toBool(p["live"]),
				"maxLayer": orDefault(p["maxLayer"], float64(0)), "maxPoints": orDefault(p["maxPoints"], float64(0)),
				"size": size, "weights": p["weights"],
			}}
		}
		return map[string]interface{}{"val": p["val"]}
	}
	return map[string]interface{}{"val": p["val"]}
}
func orDefault(v, def interface{}) interface{} {
	if v == nil {
		return def
	}
	return v
}

func aclStrings(v interface{}) []string {
	arr, ok := v.([]interface{})
	if !ok {
		return nil
	}
	out := []string{}
	for _, x := range arr {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// serveEcast — жизненный цикл одного Ecast-соединения.
func serveEcast(conn *websocket.Conn, code string, query map[string]string) {
	engineMu.Lock()
	nextEcastID++
	c := &Client{id: nextEcastID, conn: conn, roomCode: code, server: "ecast"}
	room := getRoom(code)
	if room == nil {
		c.sendError(nil, nil, 2013, "")
		engineMu.Unlock()
		conn.Close()
		return
	}
	role := query["role"]
	if role != "host" && role != "player" && role != "moderator" && role != "audience" {
		c.sendError(room, nil, 2014, "")
		engineMu.Unlock()
		conn.Close()
		return
	}
	userID := query["user-id"]
	if userID == "" {
		userID = itoa(randInt(1000000, 9999999))
	}
	c.userID = userID
	c.role = role

	deny := func(code int) {
		c.sendError(room, nil, code, "")
		engineMu.Unlock()
		conn.Close()
	}
	switch role {
	case "host":
		if query["host-token"] != room.token {
			deny(1002)
			return
		}
		c.isHost = true
	case "player":
		reconnect := room.findByUserID(userID) != nil
		if query["name"] == "" {
			deny(2019)
			return
		}
		if contains(room.banned, userID) {
			deny(2023)
			return
		}
		if room.locked && !reconnect {
			deny(2009)
			return
		}
		if room.isFull() && !reconnect {
			deny(2010)
			return
		}
	case "audience":
		if !room.audienceEnabled {
			deny(2023)
			return
		}
	}

	room.connect(c, userID, query["name"], role, "ecast")
	logf("[ecast] %s вошёл в комнату %s", role, code)
	engineMu.Unlock()

	conn.SetReadLimit(4 << 20)
	for {
		_, data, err := conn.ReadMessage()
		if err != nil {
			break
		}
		dbg("[ec< %d] %.240s", c.id, string(data))
		var msg map[string]interface{}
		if json.Unmarshal(data, &msg) != nil {
			engineMu.Lock()
			c.sendError(getRoom(c.roomCode), nil, 2001, "")
			engineMu.Unlock()
			continue
		}
		op, _ := msg["opcode"].(string)
		if op == "" {
			engineMu.Lock()
			c.sendError(getRoom(c.roomCode), nil, 2002, "")
			engineMu.Unlock()
			continue
		}
		if _, ok := msg["params"].(map[string]interface{}); !ok {
			engineMu.Lock()
			c.sendError(getRoom(c.roomCode), msg["seq"], 2004, "")
			engineMu.Unlock()
			continue
		}
		engineMu.Lock()
		dispatch(c, msg)
		engineMu.Unlock()
	}

	engineMu.Lock()
	if r := getRoom(c.roomCode); r != nil {
		r.disconnect(c)
	}
	engineMu.Unlock()
	conn.Close()
}

func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}

func dispatch(c *Client, msg map[string]interface{}) {
	room := getRoom(c.roomCode)
	if room == nil {
		c.sendError(nil, msg["seq"], 2024, "")
		return
	}
	op, _ := msg["opcode"].(string)
	seq := msg["seq"]
	p, _ := msg["params"].(map[string]interface{})
	typ := strings.SplitN(op, "/", 2)[0]
	parts := strings.Split(op, "/")
	action := parts[len(parts)-1]
	ok := true

	switch op {
	case "room/lock":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		room.locked = true
	case "room/exit":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		c.sendEcast(room, map[string]interface{}{"opcode": "room/exit", "result": map[string]interface{}{"cause": 5}}, seq)
		c.conn.Close()
		return
	case "room/get-audience":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		c.sendEcast(room, map[string]interface{}{"opcode": "room/get-audience", "result": map[string]interface{}{"connections": room.audienceCount}}, seq)
		return
	case "room/start-audience":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		room.audienceEnabled = true
	case "client/send":
		if p["to"] == nil {
			c.sendError(room, seq, 2004, "")
			return
		}
		to, _ := toInt(p["to"])
		room.sendTo(to, map[string]interface{}{"opcode": "client/send",
			"result": map[string]interface{}{"from": p["from"], "body": p["body"]}}, nil, c.userID)
	case "client/kick":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		id, _ := toInt(p["id"])
		if target := room.players[id]; target != nil {
			if toBool(p["ban"]) {
				room.banned = append(room.banned, target.userID)
			}
			room.sendTo(target.profileID, map[string]interface{}{"opcode": "room/exit", "result": map[string]interface{}{"cause": 5}}, nil, "")
			room.sendToHost(map[string]interface{}{"opcode": "client/kicked", "result": map[string]interface{}{
				"id": target.profileID, "role": target.role, "reason": p["reason"], "banned": toBool(p["ban"])}})
			delete(room.players, target.profileID)
		}
	case "drop":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		key := str(p["key"])
		e := room.entities[key]
		if e == nil {
			c.sendError(room, seq, 2005, "no known entity with key "+key)
			return
		}
		acl := e.ACL
		room.drop(key)
		room.sendByAcl(acl, map[string]interface{}{"opcode": "drop", "result": map[string]interface{}{"key": key}}, true)
	case "echo":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		room.sendToAll(map[string]interface{}{"opcode": "echo", "result": map[string]interface{}{"message": p["message"]}})
	case "lock":
		key := str(p["key"])
		e := room.entities[key]
		if e == nil {
			c.sendError(room, seq, 2005, "no known entity with key "+key)
			return
		}
		// пометку locked храним в Extra (на нашей стороне ACL достаточно)
		from := interface{}(nil)
		if room.host != nil {
			from = room.host.profileID
		}
		room.sendByAcl(e.ACL, map[string]interface{}{"opcode": "lock", "result": map[string]interface{}{"key": key, "from": from}}, true)
	case "game/started", "game/metric", "game/ended", "text/filter":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
	case "artifact/create":
		if p["blob"] == nil || p["appId"] == nil || p["categoryId"] == nil {
			c.sendError(room, seq, 2004, "")
			return
		}
		artifactID := artifactCreate(str(p["categoryId"]), p["blob"])
		resp := map[string]interface{}{"opcode": "artifact", "result": map[string]interface{}{
			"artifactId": artifactID, "categoryId": p["categoryId"], "rootId": "jbg-blobcast-artifacts",
			"key": orDefault(p["key"], ""), "isProfane": false, "isTextFlagged": false}}
		c.sendEcast(room, resp, seq)
		room.sendByAcl([]Rule{{To: "all"}}, resp, false)
		return
	default:
		if typ == "object" || typ == "text" || typ == "number" || typ == "doodle" {
			res := handleEntity(c, room, msg, typ, action)
			if res == 0 {
				return // ошибка уже отправлена
			}
		} else {
			// Неизвестный опкод (external-request/create, audience/count-group/*) — отвечаем ok,
			// как johnbox. Ошибка 2003 заставляла игру считать запрос отклонённым.
			logf("[ws] неизвестный опкод от %s: %s → ok", roleOr(c.role), op)
			c.sendOk(room, seq)
			return
		}
	}
	if ok && !noOk[op] {
		c.sendOk(room, seq)
	}
}

func roleOr(r string) string {
	if r == "" {
		return "?"
	}
	return r
}

// handleEntity возвращает 1 при успехе, 0 если ошибка уже отправлена.
func handleEntity(c *Client, room *Room, msg map[string]interface{}, typ, action string) int {
	p, _ := msg["params"].(map[string]interface{})
	seq := msg["seq"]
	key := str(p["key"])
	if key == "" {
		c.sendError(room, seq, 2004, "")
		return 0
	}
	role := c.role
	profileID := c.profileID
	e := room.entities[key]

	if action == "get" {
		if e == nil {
			c.sendError(room, seq, 2005, "no known entity with key "+key)
			return 0
		}
		if !c.isHost && !(aclVisible(e.ACL, role, profileID) && aclReadable(e.ACL, role, profileID)) {
			c.sendError(room, seq, 2023, "")
			return 0
		}
		c.sendEcast(room, map[string]interface{}{"opcode": typ, "result": room.getBody(key)}, seq)
		return 1
	}

	if action == "create" || action == "set" {
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return 0
		}
		if action == "create" && e != nil {
			c.sendError(room, seq, 2006, "")
			return 0
		}
		content := buildContent(typ, action, p)
		if action == "create" {
			room.createEntity(typ, key, aclStrings(p["acl"]), content)
		} else {
			room.setEntity(typ, key, aclStrings(p["acl"]), content)
		}
	} else {
		if e == nil {
			c.sendError(room, seq, 2005, "no known entity with key "+key)
			return 0
		}
		if !c.isHost && aclLockedFor(e.ACL, role, profileID) {
			c.sendError(room, seq, 2028, "")
			return 0
		}
		switch {
		case typ == "doodle" && action == "stroke":
			line := map[string]interface{}{"color": orDefault(p["color"], "#ffffff"), "weight": orDefault(p["weight"], float64(0)),
				"layer": orDefault(p["layer"], float64(0)), "points": orDefault(p["points"], []interface{}{}), "brush": p["brush"]}
			if valMap, ok := e.Val.(map[string]interface{}); ok {
				lines, _ := valMap["lines"].([]interface{})
				valMap["lines"] = append(lines, line)
			}
			e.Version++
			e.From = profileID
		case typ == "doodle" && action == "undo":
			if valMap, ok := e.Val.(map[string]interface{}); ok {
				lines, _ := valMap["lines"].([]interface{})
				if len(lines) > 0 {
					valMap["lines"] = lines[:len(lines)-1]
				}
			}
			e.Version++
			e.From = profileID
		case action == "increment":
			room.incrementEntity(key, timesOrVal(p), profileID)
		case action == "decrement":
			room.decrementEntity(key, timesOrVal(p), profileID)
		case action == "update":
			room.updateEntity(key, buildContent(typ, action, p), profileID)
		default:
			c.sendError(room, seq, 2003, "")
			return 0
		}
	}

	if !(typ == "doodle" && action != "create") {
		room.notify(key, !c.isHost, profileID)
	}
	return 1
}

func timesOrVal(p map[string]interface{}) interface{} {
	if p["times"] != nil {
		return p["times"]
	}
	return p["val"]
}
