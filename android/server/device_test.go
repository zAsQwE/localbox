package main

// Explicit opt-in: checks our APK on an adb emulator/device, never a real game APK.
import (
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"
)

func TestDeviceGameAndWebPorts(t *testing.T) {
	game, web := os.Getenv("LOCALBOX_DEVICE_GAME_URL"), os.Getenv("LOCALBOX_DEVICE_WEB_URL")
	if game == "" || web == "" {
		t.Skip("set device port-forward URLs to test the APK")
	}
	response, err := http.Post(game+"/api/v2/rooms", "application/json", strings.NewReader(`{"userId":"fixture-host","appTag":"test"}`))
	if err != nil {
		t.Fatal(err)
	}
	var created struct{ Body struct{ Code, Token string } }
	json.NewDecoder(response.Body).Decode(&created)
	response.Body.Close()
	host := dial(t, strings.Replace(game, "http://", "ws://", 1)+"/api/v2/rooms/"+created.Body.Code+"/play?role=host&host-token="+created.Body.Token+"&user-id=fixture-host")
	defer host.Close()
	readUntil(t, host, "client/welcome")
	player := dial(t, strings.Replace(web, "http://", "ws://", 1)+"/api/v2/rooms/"+created.Body.Code+"/play?role=player&name=Fixture&user-id=fixture-player")
	defer player.Close()
	readUntil(t, player, "client/welcome")
	send(t, host, map[string]interface{}{"opcode": "object/create", "params": map[string]interface{}{"key": "prompt", "acl": []interface{}{"r *"}, "val": "device test"}})
	readUntil(t, host, "ok")
	if result(readUntil(t, player, "object"))["val"] != "device test" {
		t.Fatal("cross-port room sync failed")
	}
	response, err = http.Get(web + "/localbox/status")
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]interface{}
	json.NewDecoder(response.Body).Decode(&state)
	response.Body.Close()
	room := state["room"].(map[string]interface{})
	if state["running"] != true || room["code"] != created.Body.Code || room["playerCount"] != float64(1) {
		t.Fatal(state)
	}
	if os.Getenv("LOCALBOX_DEVICE_CAPTURE") == "1" {
		t.Log("lobby ready")
		time.Sleep(5 * time.Second)
	}
	send(t, host, map[string]interface{}{"opcode": "game/started", "params": map[string]interface{}{}})
	readUntil(t, host, "ok")
	response, err = http.Get(web + "/localbox/status")
	if err != nil {
		t.Fatal(err)
	}
	json.NewDecoder(response.Body).Decode(&state)
	response.Body.Close()
	if state["room"].(map[string]interface{})["qrVisible"] != false {
		t.Fatal("QR did not hide")
	}
	if os.Getenv("LOCALBOX_DEVICE_CAPTURE") == "1" {
		t.Log("game started, QR hidden")
		time.Sleep(5 * time.Second)
	}
}
