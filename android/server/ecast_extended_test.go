package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gorilla/websocket"
)

func extendedFixture(t *testing.T) (*httptest.Server, *Room, *websocket.Conn, *websocket.Conn, *websocket.Conn) {
	t.Helper()
	engineMu.Lock()
	rooms, games, clientDir = map[string]*Room{}, newGames(), ""
	room := addRoom(newRoom(map[string]interface{}{"appTag": "ecast-test", "userId": "host", "audienceEnabled": true}, "localhost", games))
	engineMu.Unlock()
	ts := httptest.NewServer(http.HandlerFunc(rootHandler))
	host := dial(t, wsURL(ts, "/api/v2/rooms/"+room.code+"/play?role=host&host-token="+room.token+"&user-id=host"))
	readUntil(t, host, "client/welcome")
	player := dial(t, wsURL(ts, "/api/v2/rooms/"+room.code+"/play?role=player&name=Player&user-id=player"))
	readUntil(t, player, "client/welcome")
	audience := dial(t, wsURL(ts, "/api/v2/audience/"+room.code+"/play?role=audience&user-id=audience"))
	readUntil(t, audience, "client/welcome")
	t.Cleanup(func() { host.Close(); player.Close(); audience.Close(); ts.Close(); connectionWorkers.Wait() })
	return ts, room, host, player, audience
}

func rpc(t *testing.T, c *websocket.Conn, opcode string, p map[string]interface{}) map[string]interface{} {
	t.Helper()
	send(t, c, map[string]interface{}{"opcode": opcode, "params": p, "seq": 987})
	for {
		_, data, err := c.ReadMessage()
		if err != nil {
			t.Fatal(err)
		}
		var msg map[string]interface{}
		if err := json.Unmarshal(data, &msg); err != nil {
			t.Fatal(err)
		}
		if msg["re"] == float64(987) {
			return msg
		}
	}
}

func mustOK(t *testing.T, reply map[string]interface{}) {
	t.Helper()
	if reply["opcode"] != "ok" {
		t.Fatalf("not ok: %+v", reply)
	}
}
func mustError(t *testing.T, reply map[string]interface{}, code int) {
	t.Helper()
	if reply["opcode"] != "error" || result(reply)["code"] != float64(code) {
		t.Fatalf("expected %d: %+v", code, reply)
	}
}

func TestEcastAudienceVotesCountersAndComments(t *testing.T) {
	_, _, host, _, audience := extendedFixture(t)
	mustOK(t, rpc(t, host, "audience/count-group/create", map[string]interface{}{"name": "vote", "options": []interface{}{"yes", "no", "__proto__"}}))
	mustOK(t, rpc(t, audience, "audience/count-group/increment", map[string]interface{}{"name": "vote", "vote": "yes", "times": 2}))
	choices := result(rpc(t, host, "audience/count-group/get", map[string]interface{}{"name": "vote"}))["choices"].(map[string]interface{})
	if choices["yes"] != float64(2) {
		t.Fatal(choices)
	}
	mustError(t, rpc(t, audience, "audience/count-group/increment", map[string]interface{}{"name": "vote", "vote": "missing"}), 2004)
	for _, typ := range []string{"g-counter", "pn-counter"} {
		key := "audience/" + typ
		mustOK(t, rpc(t, host, key+"/create", map[string]interface{}{"key": typ, "count": 3}))
		if typ == "g-counter" {
			mustError(t, rpc(t, audience, key+"/decrement", map[string]interface{}{"key": typ}), 2003)
		} else {
			mustOK(t, rpc(t, audience, key+"/decrement", map[string]interface{}{"key": typ, "times": 5}))
			if result(rpc(t, host, key+"/get", map[string]interface{}{"key": typ}))["count"] != float64(-2) {
				t.Fatal("counter did not decrement")
			}
		}
	}
	mustOK(t, rpc(t, host, "audience/text-ring/create", map[string]interface{}{"key": "comments", "limit": 2}))
	for _, text := range []string{"one", "two", "three"} {
		mustOK(t, rpc(t, audience, "audience/text-ring/push", map[string]interface{}{"name": "comments", "text": text}))
	}
	elements := result(rpc(t, host, "audience/text-ring/get", map[string]interface{}{"name": "comments"}))["elements"].([]interface{})
	if len(elements) != 2 || elements[0] != "two" || elements[1] != "three" {
		t.Fatal(elements)
	}
	mustOK(t, rpc(t, host, "lock", map[string]interface{}{"key": "vote"}))
	mustError(t, rpc(t, audience, "audience/count-group/increment", map[string]interface{}{"name": "vote", "vote": "yes"}), 2028)
}

func TestEcastTextMapJavaScriptInteropAndAtomicRejection(t *testing.T) {
	var fixture struct {
		Updates []string
		Text    string
	}
	data, err := os.ReadFile("testdata/yjs-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	_, _, host, player, _ := extendedFixture(t)
	mustOK(t, rpc(t, host, "text-map/create", map[string]interface{}{"key": "text"}))
	for _, update := range fixture.Updates {
		mustOK(t, rpc(t, player, "text-map/sync", map[string]interface{}{"key": "text", "msg": update}))
	}
	state := result(rpc(t, host, "text-map/get", map[string]interface{}{"key": "text", "includeNodes": true}))
	if state["text"] != fixture.Text {
		t.Fatalf("Yjs mismatch: %+v", state)
	}
	root := result(rpc(t, host, "text-map/get", map[string]interface{}{"key": "text"}))["root"].(string)
	for _, bad := range []string{"not-base64", "AQ==", "/////w=="} {
		mustError(t, rpc(t, player, "text-map/sync", map[string]interface{}{"key": "text", "msg": bad}), 2004)
		if result(rpc(t, host, "text-map/get", map[string]interface{}{"key": "text"}))["root"] != root {
			t.Fatal("bad update changed document")
		}
	}
	// Consume the Go-produced wire state with the real JavaScript Yjs used by desktop controllers.
	if node, err := exec.LookPath("node"); err == nil {
		module, _ := filepath.Abs("../../server/node_modules/yjs")
		if _, err := os.Stat(module); err == nil {
			output, err := exec.Command(node, "-e", `const Y=require(process.argv[1]);const d=new Y.Doc();Y.applyUpdate(d,Buffer.from(process.argv[2],'base64'));process.stdout.write(d.getText('ecast').toString());`, module, root).CombinedOutput()
			if err != nil || string(output) != fixture.Text {
				t.Fatalf("JS rejected Go state: %s %v", output, err)
			}
		}
	}
	mustOK(t, rpc(t, host, "lock", map[string]interface{}{"key": "text"}))
	mustError(t, rpc(t, player, "text-map/sync", map[string]interface{}{"key": "text", "msg": fixture.Updates[0]}), 2028)
}

func TestEcastLiveDoodlesAndEmptyACL(t *testing.T) {
	_, _, host, player, _ := extendedFixture(t)
	mustOK(t, rpc(t, host, "doodle/create", map[string]interface{}{"key": "drawing", "live": true, "acl": []interface{}{"rw *"}}))
	mustOK(t, rpc(t, player, "doodle/stroke", map[string]interface{}{"key": "drawing", "points": []interface{}{map[string]interface{}{"x": 1, "y": 2}}}))
	line := result(readUntil(t, host, "doodle/line"))
	if line["index"] != float64(0) {
		t.Fatal(line)
	}
	mustOK(t, rpc(t, player, "doodle/undo", map[string]interface{}{"key": "drawing"}))
	if result(readUntil(t, host, "doodle/line/removed"))["index"] != float64(0) {
		t.Fatal("undo index")
	}
	mustOK(t, rpc(t, host, "object/create", map[string]interface{}{"key": "private", "acl": []interface{}{}, "val": map[string]interface{}{"secret": true}}))
	mustError(t, rpc(t, player, "object/get", map[string]interface{}{"key": "private"}), 2023)
	mustError(t, rpc(t, player, "object/update", map[string]interface{}{"key": "private", "val": map[string]interface{}{}}), 2028)
}

func TestEcastPasswordRolesAndTypedEcho(t *testing.T) {
	ts, room, host, player, _ := extendedFixture(t)
	mustOK(t, rpc(t, host, "room/set-password", map[string]interface{}{"password": "secret"}))
	denied := dial(t, wsURL(ts, "/api/v2/rooms/"+room.code+"/play?role=player&name=Other&user-id=other"))
	defer denied.Close()
	mustError(t, readUntil(t, denied, "error"), 2023)
	other := dial(t, wsURL(ts, "/api/v2/rooms/"+room.code+"/play?role=player&name=Other&user-id=other&password=secret"))
	defer other.Close()
	readUntil(t, other, "client/welcome")
	stolen := dial(t, wsURL(ts, "/api/v2/rooms/"+room.code+"/play?role=player&name=Other&user-id=host&password=secret"))
	defer stolen.Close()
	mustError(t, readUntil(t, stolen, "error"), 2023)
	mustError(t, rpc(t, player, "room/unlock", map[string]interface{}{}), 2023)
	if response := rpc(t, host, "text/echo", map[string]interface{}{"message": "ready"}); response["opcode"] != "text/echo" {
		t.Fatal(response)
	}
	if result(readUntil(t, player, "text/echo"))["message"] != "ready" {
		t.Fatal("echo lost")
	}
	// A native game may supply only its application ID.
	response, err := http.Post(ts.URL+"/api/v2/rooms", "application/json", strings.NewReader(`{"appId":"id-only","userId":"native"}`))
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 200 {
		t.Fatal(response.StatusCode)
	}
}
