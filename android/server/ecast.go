package main

//
// LocalBox Go-сервер — обработка WebSocket-соединений Ecast (роли, welcome, диспетчер опкодов).
// Сущности object/text/number/doodle, text-map (Yjs CRDT), голоса и счётчики зрителей.
//

import (
	"encoding/json"
	"math"
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
func serveEcast(conn *websocket.Conn, code string, query map[string]string, origin string) {
	engineMu.Lock()
	nextEcastID++
	c := &Client{id: nextEcastID, conn: conn, roomCode: code, server: "ecast", origin: origin}
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
	if prior := room.findByUserID(userID); prior != nil && prior.role != role {
		deny(2023)
		return
	}
	switch role {
	case "host":
		if query["host-token"] != room.token {
			deny(1002)
			return
		}
		c.isHost = true
	case "player":
		if room.password != "" && query["password"] != room.password {
			deny(2023)
			return
		}
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
	case "moderator":
		if room.moderatorPassword == "" || query["password"] != room.moderatorPassword {
			deny(2023)
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
	if (c.role == "audience" && room.audienceClients[c.id] != c) ||
		(c.role != "audience" && room.clientOf(c.profileID) != c) {
		c.sendError(room, msg["seq"], 2024, "")
		return
	}
	op, _ := msg["opcode"].(string)
	seq := msg["seq"]
	p, _ := msg["params"].(map[string]interface{})
	typ := strings.SplitN(op, "/", 2)[0]
	parts := strings.Split(op, "/")
	action := parts[len(parts)-1]
	ok := true
	if typ == "audience" {
		dispatchAudience(c, room, msg)
		return
	}
	if typ == "text-map" {
		dispatchTextMap(c, room, msg)
		return
	}
	if typ == "stack" {
		dispatchStack(c, room, msg)
		return
	}

	switch op {
	case "room/lock":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		room.locked = true
		room.sendToAll(map[string]interface{}{"opcode": "room/lock", "result": map[string]interface{}{}})
	case "room/unlock":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		room.locked = false
		room.sendToAll(map[string]interface{}{"opcode": "room/unlock", "result": map[string]interface{}{}})
	case "room/set-password":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		password, valid := p["password"].(string)
		if !valid || len(password) > 128 {
			c.sendError(room, seq, 2004, "")
			return
		}
		room.password = password
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
			"result": map[string]interface{}{"from": c.profileID, "body": p["body"]}}, nil, c.userID)
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
	case "object/echo", "text/echo":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		if _, exists := p["message"]; !exists {
			c.sendError(room, seq, 2004, "")
			return
		}
		if typ == "text" {
			if _, valid := p["message"].(string); !valid {
				c.sendError(room, seq, 2004, "")
				return
			}
		}
		payload := map[string]interface{}{"opcode": op, "result": map[string]interface{}{"message": p["message"]}}
		for _, player := range room.players {
			room.sendTo(player.profileID, payload, nil, "")
		}
		room.sendToAudience(payload)
		c.sendEcast(room, payload, seq)
		return
	case "lock":
		// Controllers lock their own answers/drawings on submit ("SEND"):
		// allowed for anyone who may write the entity; the host may lock anything.
		key := str(p["key"])
		e := room.entities[key]
		if e == nil {
			c.sendError(room, seq, 2005, "no known entity with key "+key)
			return
		}
		if !c.isHost {
			if aclLockedFor(e.ACL, c.role, c.profileID) {
				c.sendError(room, seq, 2023, "")
				return
			}
			if e.Locked {
				c.sendError(room, seq, 2028, "")
				return
			}
		}
		e.Locked = true
		room.sendByAcl(e.ACL, map[string]interface{}{"opcode": "lock", "result": map[string]interface{}{"key": key, "from": c.profileID}}, true)
	case "game/started", "game/metric", "game/ended", "text/filter":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		if op == "game/started" {
			room.gameStarted = true
			room.startSpeechSession()
		} else if op == "game/ended" {
			room.endSpeechSession()
		}
	case "artifact/create":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
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
	case "external-request/create":
		if !c.isHost {
			c.sendError(room, seq, 2023, "")
			return
		}
		logf("[ecast] external rendering is not available on Android")
		c.sendError(room, seq, 2003, "external rendering is not available on Android")
		return
	default:
		if typ == "object" || typ == "text" || typ == "number" || typ == "doodle" {
			res := handleEntity(c, room, msg, typ, action)
			if res == 0 {
				return // ошибка уже отправлена
			}
		} else {
			// Preserve permissive handling of unknown telemetry, but never pretend to
			// have created stateful entities or completed external rendering.
			if typ == "image" {
				c.sendError(room, seq, 2003, "image entities are not available on Android")
				return
			}
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
	if key == "" || !validACL(p["acl"]) {
		c.sendError(room, seq, 2004, "")
		return 0
	}
	role := c.role
	profileID := c.profileID
	e := room.entities[key]
	if e != nil && e.Type != typ && action != "set" {
		c.sendError(room, seq, 2004, "")
		return 0
	}
	if typ == "number" {
		for _, field := range []string{"val", "times", "increment", "min", "max"} {
			if p[field] == nil {
				continue
			}
			value, ok := toFloat(p[field])
			if !ok || math.IsNaN(value) || math.IsInf(value, 0) {
				c.sendError(room, seq, 2004, "")
				return 0
			}
		}
		min, hasMin := toFloat(p["min"])
		max, hasMax := toFloat(p["max"])
		if hasMin && hasMax && min > max {
			c.sendError(room, seq, 2004, "")
			return 0
		}
	}

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
		if !c.isHost && (e.Locked || aclLockedFor(e.ACL, role, profileID)) {
			c.sendError(room, seq, 2028, "")
			return 0
		}
		switch {
		case typ == "doodle" && action == "stroke":
			// As on the desktop server (and 1.1.x), a tap with an empty or missing
			// point list is accepted; only a non-array is invalid.
			if _, valid := p["points"].([]interface{}); p["points"] != nil && !valid {
				c.sendError(room, seq, 2004, "")
				return 0
			}
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
		case typ == "number" && action == "increment":
			if !room.incrementEntity(key, timesOrVal(p), profileID) {
				c.sendError(room, seq, 2004, "")
				return 0
			}
		case typ == "number" && action == "decrement":
			if !room.decrementEntity(key, timesOrVal(p), profileID) {
				c.sendError(room, seq, 2004, "")
				return 0
			}
		case action == "update":
			if _, exists := p["val"]; !exists {
				c.sendError(room, seq, 2004, "")
				return 0
			}
			room.updateEntity(key, buildContent(typ, action, p), profileID)
		default:
			c.sendError(room, seq, 2003, "")
			return 0
		}
	}
	if typ == "doodle" && (action == "stroke" || action == "undo") {
		value, valid := e.Val.(map[string]interface{})
		if valid && toBool(value["live"]) {
			lines, _ := value["lines"].([]interface{})
			index := len(lines)
			payload := map[string]interface{}{"key": key, "from": profileID, "index": index}
			opcode := "doodle/line/removed"
			if action == "stroke" {
				opcode = "doodle/line"
				index--
				payload["index"], payload["val"] = index, lines[index]
			}
			message := map[string]interface{}{"opcode": opcode, "result": payload}
			if !c.isHost {
				room.sendToHost(message)
			}
			for _, player := range room.players {
				if player.profileID != profileID && aclReadable(e.ACL, player.role, player.profileID) {
					room.sendTo(player.profileID, message, nil, "")
				}
			}
			if aclReadable(e.ACL, "audience", 0) {
				room.sendToAudience(message)
			}
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
