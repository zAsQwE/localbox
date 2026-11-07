package main

// Yjs V1 updates are the actual text-map wire format, not plain-text substitutions.
// Keep a compact snapshot, rebuilding into a temporary document for atomic validation.
import (
	"encoding/base64"
	"fmt"

	"github.com/antst/go-yjs/crdt"
)

const maxTextMapBytes = 1 << 20

type textMap struct {
	Root string
	Text string
}

func newTextMap(initial string) (*textMap, error) {
	if len(initial) > maxTextMapBytes {
		return nil, fmt.Errorf("text-map is too large")
	}
	doc := crdt.NewDoc("")
	defer doc.Destroy()
	if initial != "" {
		doc.GetText("ecast").Insert(0, initial, crdt.Object{})
	}
	return encodeTextMap(doc)
}

func encodeTextMap(doc *crdt.Doc) (*textMap, error) {
	data, err := crdt.EncodeStateAsUpdate(doc, nil)
	if err != nil || len(data) > maxTextMapBytes {
		return nil, fmt.Errorf("invalid or oversized text-map state")
	}
	return &textMap{Root: base64.StdEncoding.EncodeToString(data), Text: doc.GetText("ecast").ToString()}, nil
}

func (m *textMap) sync(message string) (err error) {
	// An invalid remote frame must neither crash the engine nor poison its prior snapshot.
	defer func() {
		if recovered := recover(); recovered != nil {
			err = fmt.Errorf("invalid Yjs update")
		}
	}()
	if len(message) > base64.StdEncoding.EncodedLen(maxTextMapBytes) {
		return fmt.Errorf("Yjs update is too large")
	}
	update, err := base64.StdEncoding.Strict().DecodeString(message)
	if err != nil || len(update) == 0 {
		return fmt.Errorf("invalid base64 Yjs update")
	}
	state, err := base64.StdEncoding.DecodeString(m.Root)
	if err != nil {
		return err
	}
	doc := crdt.NewDoc("")
	defer doc.Destroy()
	if err = crdt.ApplyUpdate(doc, state, nil); err != nil {
		return err
	}
	if err = crdt.ApplyUpdate(doc, update, nil); err != nil {
		return err
	}
	next, err := encodeTextMap(doc)
	if err == nil {
		*m = *next
	}
	return err
}

func dispatchTextMap(c *Client, room *Room, msg map[string]interface{}) {
	p := msg["params"].(map[string]interface{})
	key := str(p["key"])
	fail := func(code int) { c.sendError(room, msg["seq"], code, "") }
	if key == "" || !validACL(p["acl"]) {
		fail(2004)
		return
	}
	e := room.entities[key]
	switch msg["opcode"] {
	case "text-map/create":
		if !c.isHost {
			fail(2023)
			return
		}
		if e != nil {
			fail(2006)
			return
		}
		initial, ok := p["val"].(string)
		if p["val"] != nil && !ok {
			fail(2004)
			return
		}
		doc, err := newTextMap(initial)
		if err != nil {
			fail(2004)
			return
		}
		acl := []string{"rw *"}
		if p["acl"] != nil {
			acl = aclStrings(p["acl"])
		}
		e = &Entity{Type: "text-map", ACL: parseAcl(acl), Version: 1, TextMap: doc, Extra: map[string]interface{}{}}
		room.entities[key] = e
	case "text-map/get", "text-map/sync":
		if e == nil || e.Type != "text-map" {
			fail(2005)
			return
		}
		if msg["opcode"] == "text-map/get" {
			if !c.isHost && !aclReadable(e.ACL, c.role, c.profileID) {
				fail(2023)
				return
			}
			body := room.getBody(key)
			if toBool(p["includeNodes"]) {
				delete(body, "root")
				body["text"], body["attributions"] = e.TextMap.Text, []interface{}{}
			}
			c.sendEcast(room, map[string]interface{}{"opcode": "text-map/state", "result": body}, msg["seq"])
			return
		}
		if !c.isHost && (e.Locked || aclLockedFor(e.ACL, c.role, c.profileID)) {
			fail(2028)
			return
		}
		value, ok := p["msg"].(string)
		if !ok || e.TextMap.sync(value) != nil {
			fail(2004)
			return
		}
		e.Version++
		e.From = c.profileID
	default:
		fail(2003)
		return
	}
	room.notify(key, !c.isHost, c.profileID)
	c.sendOk(room, msg["seq"])
}
