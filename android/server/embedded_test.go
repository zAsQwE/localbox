package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"github.com/gorilla/websocket"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testPort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	l.Close()
	return port
}

func TestEmbeddedTwoPortsLifecycle(t *testing.T) {
	root := t.TempDir()
	game, web := testPort(t), testPort(t)
	if err := startEmbedded(root, "192.168.1.50", game, web); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(stopEmbedded)
	base := "http://127.0.0.1:" + itoa(game)
	response, err := http.Post(base+"/api/v2/rooms", "application/json", strings.NewReader(`{"userId":"host","appTag":"test"}`))
	if err != nil {
		t.Fatal(err)
	}
	var created struct {
		Body struct{ Code, Token, Host string }
	}
	json.NewDecoder(response.Body).Decode(&created)
	response.Body.Close()
	if created.Body.Host != "127.0.0.1:"+itoa(game) {
		t.Fatal(created)
	}
	host := dial(t, "ws://127.0.0.1:"+itoa(game)+"/api/v2/rooms/"+created.Body.Code+"/play?role=host&host-token="+created.Body.Token+"&user-id=host")
	readUntil(t, host, "client/welcome")
	webBase := "http://127.0.0.1:" + itoa(web)
	response, err = http.Get(webBase + "/localbox/status")
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]interface{}
	json.NewDecoder(response.Body).Decode(&state)
	response.Body.Close()
	if state["running"] != true || state["room"].(map[string]interface{})["code"] != created.Body.Code {
		t.Fatal(state)
	}
	send(t, host, map[string]interface{}{"opcode": "game/started", "params": map[string]interface{}{}})
	readUntil(t, host, "ok")
	json.Unmarshal([]byte(embeddedStatus()), &state)
	if state["room"].(map[string]interface{})["qrVisible"] != false {
		t.Fatal(state)
	}
	stopEmbedded()
	host.Close()
	if embeddedRunning.Load() {
		t.Fatal("server still running")
	}
	if err := startEmbedded(root, "192.168.1.50", game, web); err != nil {
		t.Fatal(err)
	}
	json.Unmarshal([]byte(embeddedStatus()), &state)
	if state["room"] != nil {
		t.Fatal("room leaked across restart")
	}
}

func TestEmbeddedStartupRollsBackWhenSecondPortIsBusy(t *testing.T) {
	busy, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer busy.Close()
	port := testPort(t)
	if err := startEmbedded(t.TempDir(), "127.0.0.1", port, busy.Addr().(*net.TCPAddr).Port); err == nil {
		t.Fatal("occupied port accepted")
	}
	l, err := net.Listen("tcp4", "127.0.0.1:"+itoa(port))
	if err != nil {
		t.Fatal("first listener leaked:", err)
	}
	l.Close()
}

func TestClientUsesTheBrowserPort(t *testing.T) {
	clientDir = t.TempDir()
	t.Cleanup(func() { clientDir = "" })
	os.WriteFile(filepath.Join(clientDir, "index.html"), []byte(`https://ecast.jackboxgames.com/api wss://ecast.jackboxgames.com/socket`), 0600)
	server := httptest.NewServer(http.HandlerFunc(rootHandler))
	defer server.Close()
	response, err := http.Get(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	data, _ := io.ReadAll(response.Body)
	authority := strings.TrimPrefix(server.URL, "http://")
	if string(data) != "http://"+authority+"/api ws://"+authority+"/socket" {
		t.Fatal(string(data))
	}
}

func TestClientLanguageLayoutFallbackAndHTTPRewrite(t *testing.T) {
	root := t.TempDir()
	clientDir = filepath.Join(root, "client-ru")
	t.Cleanup(func() { clientDir = "" })
	os.MkdirAll(filepath.Join(root, "client/main/pp7-quiplash3/assets"), 0700)
	os.MkdirAll(clientDir, 0700)
	html := `<script integrity="old" src="https://jackbox.ru/app.js"></script>`
	os.WriteFile(filepath.Join(clientDir, "index.html"), []byte(html), 0600)
	os.WriteFile(filepath.Join(root, "client/main/pp7-quiplash3/assets/hash.png"), []byte("image"), 0600)
	request := httptest.NewRequest("GET", "http://192.168.1.20:8080/", nil)
	response := httptest.NewRecorder()
	rootHandler(response, request)
	if response.Code != 200 || strings.Contains(response.Body.String(), "integrity") || !strings.Contains(response.Body.String(), "http://192.168.1.20:8080/app.js") {
		t.Fatal(response.Body.String())
	}
	response = httptest.NewRecorder()
	rootHandler(response, httptest.NewRequest("GET", "http://192.168.1.20:8080/main/pp7/quiplash3/assets/hash.png", nil))
	if response.Code != 200 || response.Body.String() != "image" {
		t.Fatal(response.Code, response.Body.String())
	}
	response = httptest.NewRecorder()
	rootHandler(response, httptest.NewRequest("GET", "http://192.168.1.20:8080/main/pp7/quiplash3/assets/missing.png", nil))
	if response.Code != 404 {
		t.Fatal("a missing hash must never resolve to a different image")
	}
	js := `if(window.location.hostname!=="jackbox.ru")location.href="https://jackbox.ru";this.scheme="https";const c={scheme:'wss'};let x="wss://ecast-prod-use2.jackboxgames.com/api";`
	result := rewriteClientText(js, "192.168.1.20:8080", false)
	if !strings.Contains(result, `hostname!=="192.168.1.20"`) || strings.Contains(result, `scheme="https"`) || !strings.Contains(result, `scheme:'ws'`) || !strings.Contains(result, `ws://192.168.1.20:8080/api`) {
		t.Fatal(result)
	}
}

func TestEmbeddedUsesSelectedRussianClient(t *testing.T) {
	root := t.TempDir()
	os.MkdirAll(filepath.Join(root, "client-ru"), 0700)
	os.WriteFile(filepath.Join(root, "client-ru/index.html"), []byte("Russian fixture"), 0600)
	os.WriteFile(filepath.Join(root, "client-choice.txt"), []byte("client-ru"), 0600)
	game, web := testPort(t), testPort(t)
	if err := startEmbedded(root, "192.168.1.20", game, web); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(stopEmbedded)
	response, err := http.Get("http://127.0.0.1:" + itoa(web) + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	data, _ := io.ReadAll(response.Body)
	if string(data) != "Russian fixture" {
		t.Fatal(string(data))
	}
}

func TestEmbeddedHTTPSUsesOwnPortAndPrivateCertificate(t *testing.T) {
	root := t.TempDir()
	game, web, secure := testPort(t), testPort(t), testPort(t)
	os.WriteFile(filepath.Join(root, "web-tls.json"), []byte(`{"enabled":true,"port":`+itoa(secure)+`}`), 0600)
	os.MkdirAll(filepath.Join(root, "client"), 0700)
	os.WriteFile(filepath.Join(root, "client/index.html"), []byte(`https://ecast.jackboxgames.com/api`), 0600)
	if err := startEmbedded(root, "127.0.0.1", game, web); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(stopEmbedded)
	// Trust only this fixture's own certificate. The operating system's trust store isn't touched.
	certPEM, err := os.ReadFile(filepath.Join(root, "tls/server-cert.pem"))
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(certPEM) {
		t.Fatal("invalid certificate")
	}
	client := &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots}}, Timeout: 3 * time.Second}
	defer client.Transport.(*http.Transport).CloseIdleConnections()
	response, err := client.Get("https://127.0.0.1:" + itoa(secure) + "/")
	if err != nil {
		t.Fatal(err)
	}
	data, _ := io.ReadAll(response.Body)
	response.Body.Close()
	if string(data) != "https://127.0.0.1:"+itoa(secure)+"/api" {
		t.Fatal(string(data))
	}
	response, err = http.Get("http://127.0.0.1:" + itoa(web) + "/")
	if err != nil {
		t.Fatal(err)
	}
	data, _ = io.ReadAll(response.Body)
	response.Body.Close()
	if string(data) != "http://127.0.0.1:"+itoa(web)+"/api" {
		t.Fatal(string(data))
	}
	var state map[string]interface{}
	json.Unmarshal([]byte(embeddedStatus()), &state)
	if state["joinUrl"] != "https://127.0.0.1:"+itoa(secure)+"/" {
		t.Fatal(state)
	}
	response, err = client.Post("https://127.0.0.1:"+itoa(secure)+"/api/v2/rooms", "application/json", strings.NewReader(`{"userId":"tls-host","appTag":"test"}`))
	if err != nil {
		t.Fatal(err)
	}
	var created struct{ Body struct{ Code, Token string } }
	json.NewDecoder(response.Body).Decode(&created)
	response.Body.Close()
	host := dial(t, "ws://127.0.0.1:"+itoa(game)+"/api/v2/rooms/"+created.Body.Code+"/play?role=host&host-token="+created.Body.Token+"&user-id=tls-host")
	defer host.Close()
	readUntil(t, host, "client/welcome")
	secureDialer := websocket.Dialer{TLSClientConfig: &tls.Config{RootCAs: roots}}
	player, _, err := secureDialer.Dial("wss://127.0.0.1:"+itoa(secure)+"/api/v2/rooms/"+created.Body.Code+"/play?role=player&name=TLS&user-id=tls-player", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer player.Close()
	readUntil(t, player, "client/welcome")
	send(t, host, map[string]interface{}{"opcode": "object/create", "params": map[string]interface{}{"key": "tls-prompt", "acl": []interface{}{"r *"}, "val": "WSS works"}})
	readUntil(t, host, "ok")
	if result(readUntil(t, player, "object"))["val"] != "WSS works" {
		t.Fatal("state did not reach the HTTPS player")
	}
	// The native game publishes a loopback HTTP audio URL; the HTTPS controller
	// must receive its own HTTPS web address. Host state retains the original URL.
	audioPath := "/tts/" + strings.Repeat("a", 32) + ".wav"
	audioURL := "http://127.0.0.1:" + itoa(game) + audioPath
	send(t, host, map[string]interface{}{"opcode": "object/create", "params": map[string]interface{}{"key": "speech", "acl": []interface{}{"r *"}, "val": map[string]interface{}{"audio": audioURL, "external": "https://other.example" + audioPath}}})
	readUntil(t, host, "ok")
	send(t, host, map[string]interface{}{"opcode": "object/get", "params": map[string]interface{}{"key": "speech"}})
	if result(readUntil(t, host, "object"))["val"].(map[string]interface{})["audio"] != audioURL {
		t.Fatal("host audio address changed")
	}
	value := result(readUntil(t, player, "object"))["val"].(map[string]interface{})
	if value["audio"] != "https://127.0.0.1:"+itoa(secure)+audioPath || value["external"] != "https://other.example"+audioPath {
		t.Fatal("controller audio address", value)
	}
	if info, err := os.Stat(filepath.Join(root, "tls/server-key.pem")); err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("private key permissions", err)
	}
}
