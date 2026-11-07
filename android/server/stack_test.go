package main

import (
	"reflect"
	"testing"
)

// Jackbox 12 Debate stacks, player SEND (lock) and taps without points — same as the desktop server.
func TestStackPushPeekPopAndACL(t *testing.T) {
	_, _, host, player, _ := extendedFixture(t)
	mustOK(t, rpc(t, host, "stack/create", map[string]interface{}{"key": "args", "acl": []interface{}{"r *"}}))
	mustError(t, rpc(t, host, "stack/create", map[string]interface{}{"key": "args"}), 2006)
	mustError(t, rpc(t, player, "stack/create", map[string]interface{}{"key": "mine"}), 2023)
	mustOK(t, rpc(t, host, "stack/push", map[string]interface{}{"key": "args", "val": "a"}))
	mustOK(t, rpc(t, host, "stack/pushbulk", map[string]interface{}{"key": "args", "vals": []interface{}{"b", "c"}}))
	notice := readUntil(t, player, "stack")
	if result(notice)["size"] == nil {
		t.Fatalf("stack notification without size: %+v", notice)
	}
	peek := rpc(t, player, "stack/peek", map[string]interface{}{"key": "args", "size": 2})
	if peek["opcode"] != "stack/elements" || !reflect.DeepEqual(result(peek)["vals"], []interface{}{"c", "b"}) {
		t.Fatalf("peek must return newest first: %+v", peek)
	}
	if vals := result(rpc(t, player, "stack/peek", map[string]interface{}{"key": "args"}))["vals"]; !reflect.DeepEqual(vals, []interface{}{"c"}) {
		t.Fatal(vals)
	}
	mustError(t, rpc(t, player, "stack/push", map[string]interface{}{"key": "args", "val": "x"}), 2028)
	mustError(t, rpc(t, player, "stack/pop", map[string]interface{}{"key": "args"}), 2028)
	mustError(t, rpc(t, host, "stack/peek", map[string]interface{}{"key": "args", "size": -1}), 2004)
	mustError(t, rpc(t, host, "stack/pushbulk", map[string]interface{}{"key": "args", "vals": "x"}), 2004)
	mustError(t, rpc(t, host, "stack/shuffle", map[string]interface{}{"key": "args"}), 2003)
	pop := rpc(t, host, "stack/pop", map[string]interface{}{"key": "args"})
	if pop["opcode"] != "stack/element" || result(pop)["val"] != "c" {
		t.Fatal(pop)
	}
	mustOK(t, rpc(t, host, "stack/create", map[string]interface{}{"key": "shared", "acl": []interface{}{"rw *"}}))
	mustOK(t, rpc(t, player, "stack/push", map[string]interface{}{"key": "shared", "val": "mine"}))
	if result(rpc(t, player, "stack/pop", map[string]interface{}{"key": "shared"}))["val"] != "mine" {
		t.Fatal("player could not pop a writable stack")
	}
	mustError(t, rpc(t, player, "stack/pop", map[string]interface{}{"key": "shared"}), 2004)
}

func TestPlayerLocksOwnDrawingOnSend(t *testing.T) {
	ts, room, host, player, _ := extendedFixture(t)
	engineMu.Lock()
	id := 0
	for _, p := range room.players {
		if p.userID == "player" {
			id = p.profileID
		}
	}
	engineMu.Unlock()
	mustOK(t, rpc(t, host, "doodle/create", map[string]interface{}{"key": "signature", "live": false,
		"acl": []interface{}{"rw id:" + itoa(id)}}))
	mustOK(t, rpc(t, player, "doodle/stroke", map[string]interface{}{"key": "signature", "color": "#a00", "weight": 12, "points": []interface{}{}}))
	mustOK(t, rpc(t, player, "doodle/stroke", map[string]interface{}{"key": "signature", "color": "#a00", "weight": 12}))
	mustError(t, rpc(t, player, "doodle/stroke", map[string]interface{}{"key": "signature", "points": "x"}), 2004)
	other := dial(t, wsURL(ts, "/api/v2/rooms/"+room.code+"/play?role=player&name=Other&user-id=other"))
	t.Cleanup(func() { other.Close() })
	readUntil(t, other, "client/welcome")
	mustError(t, rpc(t, other, "lock", map[string]interface{}{"key": "signature"}), 2023)
	mustOK(t, rpc(t, player, "lock", map[string]interface{}{"key": "signature"}))
	if lock := readUntil(t, host, "lock"); result(lock)["key"] != "signature" || result(lock)["from"] != float64(id) {
		t.Fatalf("host was not told who locked: %+v", lock)
	}
	mustError(t, rpc(t, player, "lock", map[string]interface{}{"key": "signature"}), 2028)
	mustError(t, rpc(t, player, "doodle/stroke", map[string]interface{}{"key": "signature", "points": []interface{}{}}), 2028)
}
