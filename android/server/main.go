package main

//
// LocalBox Go-сервер — точка входа. Совместим с играми Jackbox по Ecast (API v2) и Blobcast
// (socket.io). Порт server/server.js. Порты и TLS настраиваются (для Android — один высокий
// порт по HTTP, чтобы не требовался root и не нужен сертификат).
//
// Конфиг (config.json рядом с бинарём или путь в LOCALBOX_CONFIG):
//   {
//     "serverUrl": "192.168.1.5:9999",
//     "listen": [ { "port": 9999, "tls": false } ],
//     "ssl": { "cert": "cert.pem", "key": "key.pem" }   // только если tls:true
//   }
// Без конфига: слушает HTTP на порту LOCALBOX_PORT (по умолчанию 9999), serverUrl из LOCALBOX_SERVER_URL.
//

import (
	"crypto/tls"
	"encoding/json"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/gorilla/websocket"
)

// engineMu сериализует ВЕСЬ доступ к комнатам/сущностям (модель как в Node — один поток).
var engineMu sync.Mutex

var storageDir = "storage"
var clientDir = ""

type listenSpec struct {
	Port int  `json:"port"`
	TLS  bool `json:"tls"`
}
type serverConfig struct {
	ServerURL string       `json:"serverUrl"`
	Listen    []listenSpec `json:"listen"`
	SSL       struct {
		Cert string `json:"cert"`
		Key  string `json:"key"`
	} `json:"ssl"`
}

var upgrader = websocket.Upgrader{
	Subprotocols:    []string{"ecast-v0"},
	CheckOrigin:     func(r *http.Request) bool { return true },
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
}

func main() {
	baseDir := execDir()
	cfg := loadConfig(baseDir)

	serverURL = cfg.ServerURL
	if serverURL == "" {
		serverURL = envOr("LOCALBOX_SERVER_URL", "localhost")
	}
	if d := os.Getenv("LOCALBOX_STORAGE_DIR"); d != "" {
		storageDir = d
	} else {
		storageDir = filepath.Join(baseDir, "storage")
	}
	clientDir = os.Getenv("LOCALBOX_CLIENT_DIR")

	loadGames(baseDir)

	handler := http.HandlerFunc(rootHandler)

	// TLS-конфиг (общий), если хоть один слушатель просит TLS.
	var tlsCfg *tls.Config
	if anyTLS(cfg.Listen) {
		cert, err := tls.LoadX509KeyPair(rel(baseDir, cfg.SSL.Cert), rel(baseDir, cfg.SSL.Key))
		if err != nil {
			logf("Не удалось прочитать сертификат (%s): %v", cfg.SSL.Cert, err)
			os.Exit(1)
		}
		tlsCfg = &tls.Config{Certificates: []tls.Certificate{cert}}
	}

	var wg sync.WaitGroup
	bound := 0
	for _, spec := range cfg.Listen {
		spec := spec
		srv := &http.Server{Handler: handler}
		ln, err := net.Listen("tcp", ":"+itoa(spec.Port))
		if err != nil {
			// Порт занять не удалось — НЕ падаем, пропускаем. На Android/Termux без root
			// порты <1024 (80/443) недоступны; сервер продолжит на высоких портах.
			logf("порт %d пропущен (%v)", spec.Port, err)
			continue
		}
		bound++
		wg.Add(1)
		go func() {
			defer wg.Done()
			scheme := "http"
			if spec.TLS {
				scheme = "https"
				ln = tls.NewListener(ln, tlsCfg)
			}
			logf("LocalBox Go-сервер: %s на порту %d", scheme, spec.Port)
			if err := srv.Serve(ln); err != nil {
				logf("Порт %d остановлен: %v", spec.Port, err)
			}
		}()
	}
	if bound == 0 {
		logf("Ни один порт не удалось занять. На Android без root задайте высокий порт: LOCALBOX_PORT=9999")
		os.Exit(1)
	}
	logf("serverUrl = %s | клиент = %s", serverURL, orNone(clientDir))
	wg.Wait()
}

func rootHandler(w http.ResponseWriter, req *http.Request) {
	// WebSocket-апгрейд?
	if strings.EqualFold(req.Header.Get("Upgrade"), "websocket") {
		handleUpgrade(w, req)
		return
	}

	// CORS (эхо origin — для локальной игры)
	if o := req.Header.Get("Origin"); o != "" {
		w.Header().Set("Access-Control-Allow-Origin", o)
	}
	w.Header().Set("Access-Control-Allow-Credentials", "true")
	w.Header().Set("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "content-type,x-jbg-secret,x-internal-token")
	if req.Method == "OPTIONS" {
		w.WriteHeader(200)
		return
	}

	path := req.URL.Path

	// POST /api/v2/rooms
	if path == "/api/v2/rooms" && req.Method == "POST" {
		b := readBody(req)
		if b["userId"] == nil {
			writeJSON(w, 400, map[string]interface{}{"ok": false, "error": "missing required field userId"})
			return
		}
		if b["appTag"] == nil {
			writeJSON(w, 400, map[string]interface{}{"ok": false, "error": "missing required field appTag"})
			return
		}
		engineMu.Lock()
		register(b)
		room := newRoom(b, serverURL, games)
		addRoom(room)
		code, token := room.code, room.token
		engineMu.Unlock()
		logf("[room] created %s for %s (%s)", code, str(b["appTag"]), str(b["appId"]))
		writeJSON(w, 200, map[string]interface{}{"ok": true, "body": map[string]interface{}{"host": serverURL, "code": code, "token": token}})
		return
	}

	// GET /api/v2/app-configs/:appTag → 404 (клиент берёт свои дефолты)
	if strings.HasPrefix(path, "/api/v2/app-configs/") && req.Method == "GET" {
		tag := strings.TrimPrefix(path, "/api/v2/app-configs/")
		writeJSON(w, 404, map[string]interface{}{"ok": false, "error": "no app config for " + tag})
		return
	}

	// GET /api/v2/rooms/:code/play (не-WS) → 400
	if strings.HasSuffix(path, "/play") && req.Method == "GET" {
		w.Header().Set("Content-Type", "text/plain")
		w.WriteHeader(400)
		w.Write([]byte("Bad Request\n{\"ok\":false,\"error\":\"the client is not using the websocket protocol\"}"))
		return
	}

	// GET /api/v2/rooms/:code
	if strings.HasPrefix(path, "/api/v2/rooms/") && req.Method == "GET" {
		code := strings.TrimPrefix(path, "/api/v2/rooms/")
		engineMu.Lock()
		room := getRoom(code)
		if room == nil {
			engineMu.Unlock()
			writeJSON(w, 404, map[string]interface{}{"ok": false, "error": "no such room"})
			return
		}
		body := map[string]interface{}{
			"appId": room.appID, "appTag": room.appTag, "audienceEnabled": room.audienceEnabled,
			"code": room.code, "host": serverURL, "audienceHost": serverURL, "locked": room.locked,
			"full": room.isFull(), "maxPlayers": room.maxPlayers, "minPlayers": room.minPlayers,
			"moderationEnabled": room.moderatorPassword != "", "passwordRequired": room.password != "",
			"twitchLocked": false, "locale": "en", "keepalive": false, "controllerBranch": "",
		}
		engineMu.Unlock()
		writeJSON(w, 200, map[string]interface{}{"ok": true, "body": body})
		return
	}

	// POST /api/v2/controller/state → 200
	if path == "/api/v2/controller/state" {
		w.WriteHeader(200)
		return
	}

	// Blobcast HTTP (старые игры)
	if blobcastHTTP(w, req) {
		return
	}

	// Веб-клиент
	if serveClient(w, req) {
		return
	}

	w.Header().Set("Content-Type", "text/plain")
	w.WriteHeader(404)
	w.Write([]byte("404 page not found"))
}

func handleUpgrade(w http.ResponseWriter, req *http.Request) {
	reqPath := req.URL.Path
	dbg("[ws] апгрейд: %s", reqPath)

	// Blobcast: /socket.io/1/websocket/<token>
	if strings.HasPrefix(reqPath, "/socket.io/1/websocket/") {
		conn, err := upgrader.Upgrade(w, req, nil)
		if err != nil {
			return
		}
		go serveBlobcast(conn)
		return
	}
	// Ecast: /api/v2/(rooms|audience)/CODE/play
	if m := matchPlay(reqPath); m != "" {
		query := map[string]string{}
		for k, v := range req.URL.Query() {
			if len(v) > 0 {
				query[k] = v[0]
			}
		}
		conn, err := upgrader.Upgrade(w, req, nil)
		if err != nil {
			return
		}
		go serveEcast(conn, m, query)
		return
	}
	logf("[ws] апгрейд ОТКЛОНЁН (путь не распознан): %s", reqPath)
	http.Error(w, "not found", 404)
}

// matchPlay возвращает код комнаты из /api/v2/(rooms|audience)/CODE/play или "".
func matchPlay(p string) string {
	for _, pre := range []string{"/api/v2/rooms/", "/api/v2/audience/"} {
		if strings.HasPrefix(p, pre) && strings.HasSuffix(p, "/play") {
			code := strings.TrimSuffix(strings.TrimPrefix(p, pre), "/play")
			if len(code) == 4 && isUpperAlpha(code) {
				return code
			}
		}
	}
	return ""
}
func isUpperAlpha(s string) bool {
	for _, ch := range s {
		if ch < 'A' || ch > 'Z' {
			return false
		}
	}
	return true
}

// ---------------- конфиг / игры ----------------

func loadConfig(baseDir string) serverConfig {
	cfg := serverConfig{}
	path := os.Getenv("LOCALBOX_CONFIG")
	if path == "" {
		path = filepath.Join(baseDir, "config.json")
	}
	if data, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(data, &cfg)
	}
	if len(cfg.Listen) == 0 {
		port := 9999
		if v, err := strconv.Atoi(os.Getenv("LOCALBOX_PORT")); err == nil && v > 0 {
			port = v
		}
		cfg.Listen = []listenSpec{{Port: port, TLS: false}}
	}
	return cfg
}

func loadGames(baseDir string) {
	path := filepath.Join(baseDir, "games.json")
	if os.Getenv("LOCALBOX_GAMES") != "" {
		path = os.Getenv("LOCALBOX_GAMES")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	g := newGames()
	if json.Unmarshal(data, g) == nil {
		for k, v := range g.AppTags {
			games.AppTags[k] = v
		}
		for k, v := range g.AppIds {
			games.AppIds[k] = v
		}
		for k, v := range g.MaxPlayers {
			games.MaxPlayers[k] = v
		}
		for k, v := range g.MinPlayers {
			games.MinPlayers[k] = v
		}
	}
}

// ---------------- утилиты ----------------

func execDir() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	return filepath.Dir(exe)
}
func rel(base, p string) string {
	if p == "" || filepath.IsAbs(p) {
		return p
	}
	return filepath.Join(base, p)
}
func anyTLS(l []listenSpec) bool {
	for _, s := range l {
		if s.TLS {
			return true
		}
	}
	return false
}
func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
func orNone(s string) string {
	if s == "" {
		return "(нет)"
	}
	return s
}
