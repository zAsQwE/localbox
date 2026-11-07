package main

// The APK loads this engine as a native library. No Termux, root or child process.
import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

var embeddedMu sync.Mutex
var embeddedServers []*http.Server
var embeddedRunning atomic.Bool
var embeddedScheme = "http"
var connectionMu sync.Mutex
var connections = map[*websocket.Conn]struct{}{}
var connectionWorkers sync.WaitGroup
var stoppingConnections bool

func startEmbedded(directory, advertisedHost string, gamePort, webPort int) error {
	embeddedMu.Lock()
	defer embeddedMu.Unlock()
	if embeddedRunning.Load() {
		return fmt.Errorf("сервер уже запущен")
	}
	if gamePort < 1024 || gamePort > 65535 || webPort < 1024 || webPort > 65535 || gamePort == webPort {
		return fmt.Errorf("нужны два разных порта от 1024 до 65535")
	}
	directory, err := filepath.Abs(directory)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Join(directory, "storage"), 0700); err != nil {
		return err
	}
	game, err := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", gamePort))
	if err != nil {
		return fmt.Errorf("порт игры %d: %w", gamePort, err)
	}
	web, err := net.Listen("tcp4", fmt.Sprintf("0.0.0.0:%d", webPort))
	if err != nil {
		game.Close()
		return fmt.Errorf("веб-порт %d: %w", webPort, err)
	}
	listeners := []net.Listener{game, web}
	options, err := readWebTLS(directory)
	if err != nil {
		game.Close()
		web.Close()
		return err
	}
	publicPort := webPort
	var publicCA []byte
	scheme := "http"
	if options.Enabled {
		if options.Port == gamePort || options.Port == webPort {
			game.Close()
			web.Close()
			return fmt.Errorf("для HTTPS нужен отдельный порт")
		}
		certificate, caPEM, certError := localCertificate(directory, advertisedHost)
		if certError != nil {
			game.Close()
			web.Close()
			return fmt.Errorf("сертификат HTTPS: %w", certError)
		}
		secure, listenError := net.Listen("tcp4", fmt.Sprintf("0.0.0.0:%d", options.Port))
		if listenError != nil {
			game.Close()
			web.Close()
			return fmt.Errorf("порт HTTPS %d: %w", options.Port, listenError)
		}
		listeners = append(listeners, tls.NewListener(secure, &tls.Config{Certificates: []tls.Certificate{certificate}, MinVersion: tls.VersionTLS12}))
		publicPort = options.Port
		scheme = "https"
		publicCA = caPEM
	}
	engineMu.Lock()
	rooms = map[string]*Room{}
	games = newGames()
	storageDir = filepath.Join(directory, "storage")
	selected := "client"
	if data, err := os.ReadFile(filepath.Join(directory, "client-choice.txt")); err == nil && string(data) == "client-ru" {
		selected = "client-ru"
	}
	clientDir = filepath.Join(directory, selected)
	serverURL = net.JoinHostPort(advertisedHost, itoa(publicPort))
	embeddedScheme = scheme
	webCAPEM = publicCA
	initSpeechOrigins(advertisedHost, gamePort, webPort, publicPort)
	loadGames(directory)
	engineMu.Unlock()
	connectionMu.Lock()
	stoppingConnections = false
	connectionMu.Unlock()
	embeddedServers = nil
	for _, listener := range listeners {
		server := &http.Server{Handler: http.HandlerFunc(rootHandler), ReadHeaderTimeout: 10 * time.Second, MaxHeaderBytes: 64 << 10}
		embeddedServers = append(embeddedServers, server)
		go func(server *http.Server, listener net.Listener) {
			if err := server.Serve(listener); err != nil && err != http.ErrServerClosed {
				logf("[android] server: %v", err)
			}
		}(server, listener)
	}
	embeddedRunning.Store(true)
	setSpeechState(false, "Подготовка системной озвучки Android…")
	logf("[android] LocalBox: game=127.0.0.1:%d, players=%s", gamePort, serverURL)
	return nil
}

func stopEmbedded() {
	embeddedMu.Lock()
	defer embeddedMu.Unlock()
	setSpeechState(false, "Сервер остановлен")
	connectionMu.Lock()
	stoppingConnections = true
	for conn := range connections {
		conn.Close()
	}
	connectionMu.Unlock()
	for _, server := range embeddedServers {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		if server.Shutdown(ctx) != nil {
			server.Close()
		}
		cancel()
	}
	connectionWorkers.Wait()
	engineMu.Lock()
	for _, room := range rooms {
		room.endSpeechSession()
		for _, timer := range room.audiencePush {
			timer.Stop()
		}
	}
	rooms = map[string]*Room{}
	engineMu.Unlock()
	embeddedServers = nil
	embeddedRunning.Store(false)
	connectionMu.Lock()
	stoppingConnections = false
	connectionMu.Unlock()
}

func trackConnection(conn *websocket.Conn, serve func()) {
	connectionMu.Lock()
	if stoppingConnections {
		connectionMu.Unlock()
		conn.Close()
		return
	}
	connections[conn] = struct{}{}
	connectionWorkers.Add(1)
	connectionMu.Unlock()
	go func() {
		defer func() {
			conn.Close()
			connectionMu.Lock()
			delete(connections, conn)
			connectionMu.Unlock()
			connectionWorkers.Done()
		}()
		serve()
	}()
}

func embeddedStatus() string {
	engineMu.Lock()
	defer engineMu.Unlock()
	var current *Room
	for _, room := range rooms {
		if room.host != nil && room.host.connected && (current == nil || room.createdAt.After(current.createdAt)) {
			current = room
		}
	}
	var roomStatus interface{}
	if current != nil {
		players := 0
		for _, player := range current.players {
			if player.role == "player" && player.connected {
				players++
			}
		}
		roomStatus = map[string]interface{}{"id": current.code + ":" + fmt.Sprint(current.createdAt.UnixNano()), "code": current.code, "appTag": current.appTag,
			"playerCount": players, "maxPlayers": current.maxPlayers,
			"qrVisible": !current.locked && !current.gameStarted,
			"joinUrl":   embeddedScheme + "://" + serverURL + "/?code=" + current.code}
	}
	_, clientError := os.Stat(filepath.Join(clientDir, "index.html"))
	data, _ := json.Marshal(map[string]interface{}{"running": embeddedRunning.Load(), "room": roomStatus,
		"tts":     speechState(),
		"joinUrl": embeddedScheme + "://" + serverURL + "/", "clientInstalled": clientDir != "" && clientError == nil})
	return string(data)
}
