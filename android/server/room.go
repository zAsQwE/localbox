package main

//
// LocalBox Go-сервер — комнаты и entity-store (порт server/lib/room.js).
// ВАЖНО: весь доступ к движку сериализован глобальным engineMu (см. main.go) — это
// повторяет однопоточную модель Node и исключает гонки. Методы Room предполагают,
// что engineMu уже захвачен вызывающим (обработчиком WS/HTTP или сработавшим таймером).
//

import (
	"encoding/json"
	"strconv"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

func itoa(i int) string { return strconv.Itoa(i) }

// ---------------- Клиент ----------------

type Client struct {
	id        int
	conn      *websocket.Conn
	writeMu   sync.Mutex // gorilla не допускает параллельную запись (ecast + пинг blobcast)
	roomCode  string
	profileID int // 0 = нет профиля (зритель); реальные profileId начинаются с 1
	role      string
	userID    string
	server    string // "ecast" | "blobcast"
	isHost    bool
	isPlayer  bool
}

func (c *Client) writeText(s string) {
	if c == nil || c.conn == nil {
		return
	}
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	_ = c.conn.WriteMessage(websocket.TextMessage, []byte(s))
}

func (c *Client) closed() bool { return c == nil || c.conn == nil }

// sendEcast формирует {pc, re, ...msg} и шлёт JSON.
func (c *Client) sendEcast(room *Room, msg map[string]interface{}, re interface{}) {
	full := make(map[string]interface{}, len(msg)+2)
	if room != nil {
		full["pc"] = room.nextPc()
	} else {
		full["pc"] = 0
	}
	if re != nil {
		full["re"] = re
	}
	for k, v := range msg {
		full[k] = v
	}
	b, _ := json.Marshal(full)
	c.writeText(string(b))
}

func (c *Client) sendOk(room *Room, re interface{}) {
	c.sendEcast(room, map[string]interface{}{"opcode": "ok", "result": map[string]interface{}{}}, re)
}

func (c *Client) sendError(room *Room, re interface{}, code int, extra string) {
	msg := extra
	if msg == "" {
		msg = errText[code]
	}
	c.sendEcast(room, map[string]interface{}{"opcode": "error", "result": map[string]interface{}{"code": code, "msg": msg}}, re)
}

// sendBlob упаковывает событие в socket.io-кадр '5:::{name:"msg",args:[obj]}'.
func (c *Client) sendBlob(obj map[string]interface{}) {
	if len(obj) == 0 {
		return
	}
	b, _ := json.Marshal(map[string]interface{}{"name": "msg", "args": []interface{}{obj}})
	c.writeText("5:::" + string(b))
}

var errText = map[int]string{
	1000: "internal error", 1002: "unable to connect to room", 2001: "parse error in ecast protocol",
	2002: "missing opcode", 2003: "invalid opcode", 2004: "invalid arguments", 2005: "entity not found",
	2006: "an entity already exists with that key", 2009: "room is locked", 2010: "room is full",
	2013: "room not found", 2014: "requested role does not exist", 2019: "missing name",
	2023: "permission denied", 2024: "not connected to a room", 2028: "the entity is locked",
}

// ---------------- Сущности ----------------

type Entity struct {
	Type         string
	ACL          []Rule
	Version      int
	From         interface{} // profileId (int) или nil
	Val          interface{}
	Restrictions map[string]interface{} // для number
	Extra        map[string]interface{} // прочие поля (audience-сессии и т.п.)
}

func entityContent(e *Entity) map[string]interface{} {
	switch e.Type {
	case "number":
		return map[string]interface{}{"val": e.Val, "restrictions": e.Restrictions}
	case "object", "text", "doodle":
		return map[string]interface{}{"val": e.Val}
	default:
		if e.Val != nil {
			return map[string]interface{}{"val": e.Val}
		}
		return map[string]interface{}{}
	}
}

// ---------------- Игрок / хост ----------------

type Player struct {
	profileID     int
	userID        string
	name          string
	role          string
	client        *Client
	connected     bool
	banned        bool
	everConnected bool
}

// ---------------- Комната ----------------

type Room struct {
	serverURL         string
	appTag            string
	appID             string
	code              string
	token             string
	locked            bool
	audienceEnabled   bool
	password          string
	moderatorPassword string
	maxPlayers        int
	minPlayers        int
	hostUserID        string
	pc                int
	nextProfileID     int
	entities          map[string]*Entity
	host              *Player
	players           map[int]*Player
	audienceCount     int
	banned            []string
	audienceClients   map[int]*Client
	audiencePush      map[string]*time.Timer
	blobcast          bool
}

func newRoom(p map[string]interface{}, serverURL string, games *Games) *Room {
	appTag, _ := p["appTag"].(string)
	appID, _ := p["appId"].(string)
	if games != nil {
		if id, ok := games.AppTags[appTag]; ok {
			appID = id
		}
	}
	if appID == "" {
		appID = appTag
	}
	code := makeCode()
	if f, ok := p["forceRoomId"].(string); ok && f != "" {
		code = f
	}
	gMax, gMin := 8, 1
	if games != nil {
		if v, ok := games.MaxPlayers[appTag]; ok {
			gMax = v
		}
		if v, ok := games.MinPlayers[appTag]; ok {
			gMin = v
		}
	}
	maxP := gMax
	if v, ok := toInt(p["maxPlayers"]); ok && v > 0 {
		maxP = v
	}
	minP := gMin
	if v, ok := toInt(p["minPlayers"]); ok && v > 0 {
		minP = v
	}
	r := &Room{
		serverURL: serverURL, appTag: appTag, appID: appID, code: code, token: makeToken(24),
		audienceEnabled: toBool(p["audienceEnabled"]), password: str(p["password"]),
		moderatorPassword: str(p["moderatorPassword"]), maxPlayers: maxP, minPlayers: minP,
		hostUserID: str(p["userId"]), nextProfileID: 1,
		entities: map[string]*Entity{}, players: map[int]*Player{},
		audienceClients: map[int]*Client{}, audiencePush: map[string]*time.Timer{},
	}
	return r
}

func (r *Room) nextPc() int          { v := r.pc; r.pc++; return v }
func (r *Room) newProfileID() int    { v := r.nextProfileID; r.nextProfileID++; return v }
func (r *Room) playerCount() int {
	n := 0
	for _, p := range r.players {
		if p.role == "player" {
			n++
		}
	}
	return n
}
func (r *Room) isFull() bool { return r.playerCount() >= r.maxPlayers }

func (r *Room) findByUserID(userID string) *Player {
	if r.host != nil && r.host.userID == userID {
		return r.host
	}
	for _, p := range r.players {
		if p.userID == userID {
			return p
		}
	}
	return nil
}
func (r *Room) nameTaken(name string) bool {
	if r.host != nil && r.host.name == name {
		return true
	}
	for _, p := range r.players {
		if p.name == name {
			return true
		}
	}
	return false
}

// ---- отправка ----

func (r *Room) clientOf(profileID int) *Client {
	if r.host != nil && r.host.profileID == profileID {
		return r.host.client
	}
	if p := r.players[profileID]; p != nil {
		return p.client
	}
	return nil
}
func (r *Room) userIDOf(profileID int) string {
	if r.host != nil && r.host.profileID == profileID {
		return r.host.userID
	}
	if p := r.players[profileID]; p != nil {
		return p.userID
	}
	return ""
}

// sendTo — отправка одному профилю; для blobcast-клиента переводит в blob-событие.
func (r *Room) sendTo(profileID int, msg map[string]interface{}, re interface{}, ctxUserID string) {
	c := r.clientOf(profileID)
	if c == nil || c.closed() {
		return
	}
	if c.server == "blobcast" {
		ctx := ctxUserID
		if ctx == "" {
			ctx = r.userIDOf(profileID)
		}
		ev := translate(msg, r.code, ctx, r.hostUserID)
		if len(ev) > 0 {
			c.sendBlob(ev)
		}
	} else {
		c.sendEcast(r, msg, re)
	}
}

func (r *Room) sendToAudience(msg map[string]interface{}) {
	for _, c := range r.audienceClients {
		if c != nil && !c.closed() {
			c.sendEcast(r, msg, nil)
		}
	}
}
func (r *Room) sendToHost(msg map[string]interface{}) {
	if r.host != nil && r.host.profileID != 0 {
		r.sendTo(r.host.profileID, msg, nil, "")
	}
}
func (r *Room) sendToAll(msg map[string]interface{}) {
	r.sendToHost(msg)
	for pid := range r.players {
		r.sendTo(pid, msg, nil, "")
	}
	r.sendToAudience(msg)
}
func (r *Room) sendByAcl(acl []Rule, msg map[string]interface{}, sendToHost bool) {
	if sendToHost {
		r.sendToHost(msg)
	}
	for _, p := range r.players {
		if aclVisible(acl, p.role, p.profileID) {
			r.sendTo(p.profileID, msg, nil, "")
		}
	}
	if r.audienceCount > 0 && aclVisible(acl, "audience", 0) {
		r.sendToAudience(msg)
	}
}

// send — client/send между профилями (ctxUserId = отправитель, для CustomerMessage).
func (r *Room) send(fromProfileID, toProfileID int, body interface{}) {
	r.sendTo(toProfileID, map[string]interface{}{
		"opcode": "client/send", "result": map[string]interface{}{"from": fromProfileID, "body": body},
	}, nil, r.userIDOf(fromProfileID))
}

// ---- сущности ----

func (r *Room) getBody(key string) map[string]interface{} {
	e := r.entities[key]
	if e == nil {
		return nil
	}
	body := map[string]interface{}{"key": key}
	for k, v := range entityContent(e) {
		body[k] = v
	}
	for k, v := range e.Extra {
		body[k] = v
	}
	body["version"] = e.Version
	body["from"] = e.From
	return body
}

// get — тело сущности (для Blobcast-действий) или nil.
func (r *Room) get(key string) map[string]interface{} {
	if r.entities[key] == nil {
		return nil
	}
	return r.getBody(key)
}

func (r *Room) notify(key string, notifyHost bool, exceptProfileID int) {
	e := r.entities[key]
	if e == nil {
		return
	}
	msg := map[string]interface{}{"opcode": e.Type, "result": r.getBody(key)}
	if notifyHost {
		r.sendToHost(msg)
	}
	for _, p := range r.players {
		if p.profileID == exceptProfileID {
			continue
		}
		if aclVisible(e.ACL, p.role, p.profileID) && aclReadable(e.ACL, p.role, p.profileID) {
			r.sendTo(p.profileID, msg, nil, "")
		}
	}
	if r.audienceCount > 0 && aclVisible(e.ACL, "audience", 0) && aclReadable(e.ACL, "audience", 0) {
		r.notifyAudience(key)
	}
}

// notifyAudience — коалесцирующая рассылка зрителям (не чаще ~7 раз/сек на ключ).
func (r *Room) notifyAudience(key string) {
	if r.audiencePush[key] != nil {
		return
	}
	r.audiencePush[key] = time.AfterFunc(150*time.Millisecond, func() {
		engineMu.Lock()
		defer engineMu.Unlock()
		delete(r.audiencePush, key)
		e := r.entities[key]
		if e == nil || r.audienceCount == 0 {
			return
		}
		if aclVisible(e.ACL, "audience", 0) && aclReadable(e.ACL, "audience", 0) {
			r.sendToAudience(map[string]interface{}{"opcode": e.Type, "result": r.getBody(key)})
		}
	})
}

func aclOrDefault(raw []string, def string) []Rule {
	if len(raw) > 0 {
		return parseAcl(raw)
	}
	return parseAcl([]string{def})
}

func (r *Room) createEntity(typ, key string, aclRaw []string, content map[string]interface{}) {
	e := &Entity{Type: typ, ACL: aclOrDefault(aclRaw, "r *"), Version: 1, Extra: map[string]interface{}{}}
	r.applyContent(e, content)
	r.entities[key] = e
}
func (r *Room) setEntity(typ, key string, aclRaw []string, content map[string]interface{}) {
	version := 1
	prev := r.entities[key]
	if prev != nil {
		version = prev.Version + 1
	}
	// ACL: если явно не задан при set — СОХРАНЯЕМ прежний (иначе сброс на "r *" делает
	// приватные сущности (audiencePlayer) видимыми игрокам → игра считает игрока зрителем).
	var acl []Rule
	if len(aclRaw) > 0 {
		acl = parseAcl(aclRaw)
	} else if prev != nil {
		acl = prev.ACL
	} else {
		acl = parseAcl([]string{"r *"})
	}
	e := &Entity{Type: typ, ACL: acl, Version: version, Extra: map[string]interface{}{}}
	r.applyContent(e, content)
	r.entities[key] = e
}

// applyContent раскладывает поля content по типизированным полям Entity.
func (r *Room) applyContent(e *Entity, content map[string]interface{}) {
	for k, v := range content {
		switch k {
		case "val":
			e.Val = v
		case "restrictions":
			if m, ok := v.(map[string]interface{}); ok {
				e.Restrictions = m
			}
		default:
			e.Extra[k] = v
		}
	}
}

func (r *Room) updateEntity(key string, content map[string]interface{}, fromProfileID int) bool {
	e := r.entities[key]
	if e == nil {
		return false
	}
	r.applyContent(e, content)
	e.Version++
	if fromProfileID != 0 {
		e.From = fromProfileID
	}
	return true
}
func (r *Room) incrementEntity(key string, times interface{}, fromProfileID int) bool {
	e := r.entities[key]
	if e == nil || e.Type != "number" {
		return false
	}
	step := numberStep(e, times)
	e.Val = toFloatOr(e.Val, 0) + step
	if e.Restrictions != nil {
		if mx, ok := toFloat(e.Restrictions["max"]); ok && toFloatOr(e.Val, 0) > mx {
			e.Val = mx
		}
	}
	e.Version++
	if fromProfileID != 0 {
		e.From = fromProfileID
	}
	return true
}
func (r *Room) decrementEntity(key string, times interface{}, fromProfileID int) bool {
	e := r.entities[key]
	if e == nil || e.Type != "number" {
		return false
	}
	step := numberStep(e, times)
	e.Val = toFloatOr(e.Val, 0) - step
	if e.Restrictions != nil {
		if mn, ok := toFloat(e.Restrictions["min"]); ok && toFloatOr(e.Val, 0) < mn {
			e.Val = mn
		}
	}
	e.Version++
	if fromProfileID != 0 {
		e.From = fromProfileID
	}
	return true
}
func numberStep(e *Entity, times interface{}) float64 {
	if v, ok := toFloat(times); ok {
		return v
	}
	if e.Restrictions != nil {
		if v, ok := toFloat(e.Restrictions["increment"]); ok && v != 0 {
			return v
		}
	}
	return 1
}
func (r *Room) drop(key string) { delete(r.entities, key) }

// ---- подключение / отключение ----

func (r *Room) connect(c *Client, userID, name, role, server string) {
	c.server = server
	c.roomCode = r.code
	if role == "host" && server == "blobcast" {
		r.blobcast = true
	}
	reconnect := false
	profileID := 0
	var self *Player

	switch role {
	case "host":
		reconnect = r.host != nil && r.host.everConnected
		if r.host == nil {
			r.host = &Player{}
		}
		if r.host.profileID != 0 {
			profileID = r.host.profileID
		} else {
			profileID = r.newProfileID()
		}
		self = r.host
		self.profileID = profileID
		self.userID = userID
		self.name = ""
		self.role = "host"
		self.client = c
		self.connected = true
		self.everConnected = true
	case "audience":
		r.audienceCount++
		r.audienceClients[c.id] = c
		profileID = 0
		self = nil
	default:
		existing := r.findByUserID(userID)
		reconnect = existing != nil
		if existing != nil {
			profileID = existing.profileID
			self = existing
			self.client = c
			self.connected = true
		} else {
			if r.nameTaken(name) {
				i := 2
				for r.nameTaken(name + itoa(i)) {
					i++
				}
				name = name + itoa(i)
			}
			profileID = r.newProfileID()
			self = &Player{profileID: profileID, userID: userID, name: name, role: role, client: c, connected: true}
			r.players[profileID] = self
			if r.blobcast || server == "blobcast" {
				r.setEntity("object", "bc:customer:"+userID, []string{"r id:" + itoa(profileID)}, map[string]interface{}{"val": map[string]interface{}{}})
			}
		}
	}
	c.profileID = profileID

	// видимые сущности
	entities := map[string]interface{}{}
	for key, e := range r.entities {
		vis := false
		if role == "audience" {
			vis = aclVisible(e.ACL, "audience", 0)
		} else {
			vis = aclVisible(e.ACL, role, profileID)
		}
		if vis {
			entities[key] = []interface{}{e.Type, r.getBody(key), map[string]interface{}{"locked": aclLockedFor(e.ACL, role, profileID)}}
		}
	}

	// here + profile
	var here map[string]interface{}
	var profile interface{}
	if role != "audience" {
		here = map[string]interface{}{}
		roster := []*Player{}
		if r.host != nil && r.host.profileID != 0 {
			roster = append(roster, r.host)
		}
		for _, p := range r.players {
			roster = append(roster, p)
		}
		for _, p := range roster {
			roles := map[string]interface{}{}
			roleObj := map[string]interface{}{}
			if (role == "player" || role == "moderator") && (p.role == "player" || p.role == "moderator") {
				roleObj["name"] = p.name
			}
			roles[p.role] = roleObj
			node := map[string]interface{}{"id": p.profileID, "roles": roles}
			if p.banned {
				node["banned"] = map[string]interface{}{}
			}
			if p.profileID == profileID {
				profile = node
			} else {
				here[itoa(p.profileID)] = node
			}
		}
	}

	secret := userID
	if role == "host" {
		secret = r.token
	}
	welcome := map[string]interface{}{
		"opcode": "client/welcome",
		"result": map[string]interface{}{
			"id": profileID, "name": name, "secret": secret, "reconnect": reconnect,
			"deviceId": "", "entities": entities, "here": here, "profile": profile,
		},
	}
	if role == "audience" {
		c.sendEcast(r, welcome, nil)
	} else {
		r.sendTo(profileID, welcome, nil, "")
	}

	// оповестить остальных
	if role == "host" {
		m := map[string]interface{}{"opcode": "client/connected", "result": map[string]interface{}{"id": profileID, "role": role, "reconnect": reconnect, "profile": profile}}
		for _, p := range r.players {
			r.sendTo(p.profileID, m, nil, "")
		}
	} else if role != "audience" {
		r.sendToHost(map[string]interface{}{"opcode": "client/connected", "result": map[string]interface{}{
			"id": profileID, "userId": userID, "name": name, "role": role, "reconnect": reconnect, "profile": profile}})
	}
}

func (r *Room) disconnect(c *Client) {
	if r.host != nil && r.host.client == c {
		r.host.connected = false
		r.host.client = nil
		for _, p := range r.players {
			r.sendTo(p.profileID, map[string]interface{}{"opcode": "room/exit", "result": map[string]interface{}{"cause": 5}}, nil, "")
		}
		r.sendToAudience(map[string]interface{}{"opcode": "room/exit", "result": map[string]interface{}{"cause": 5}})
		for _, ac := range r.audienceClients {
			if ac != nil && ac.conn != nil {
				ac.conn.Close()
			}
		}
		for _, t := range r.audiencePush {
			t.Stop()
		}
		r.audiencePush = map[string]*time.Timer{}
		delete(rooms, r.code)
		logf("[room] закрыта (хост вышел): %s", r.code)
		return
	}
	for _, p := range r.players {
		if p.client == c {
			p.connected = false
			p.client = nil
			if r.host != nil && r.host.profileID != 0 {
				r.sendTo(r.host.profileID, map[string]interface{}{"opcode": "client/disconnected",
					"result": map[string]interface{}{"id": p.profileID, "role": p.role}}, nil, p.userID)
			}
			return
		}
	}
	if r.audienceClients[c.id] != nil {
		delete(r.audienceClients, c.id)
		if r.audienceCount > 0 {
			r.audienceCount--
		}
	}
}

// ---------------- Менеджер комнат ----------------

var rooms = map[string]*Room{}

func getRoom(code string) *Room { return rooms[code] }
func addRoom(r *Room) *Room     { rooms[r.code] = r; return r }
