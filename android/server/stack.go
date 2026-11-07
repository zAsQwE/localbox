package main

// Ecast StackEntity (Jackbox 12: Debate). A LIFO list: the host pushes values,
// controllers learn only its size from notifications and fetch new values with
// stack/peek. peek returns the newest values first, as the web client expects.
import "strings"

const maxStackElements = 10000

func stackElements(e *Entity) []interface{} {
	elements, _ := e.Extra["elements"].([]interface{})
	return elements
}

func dispatchStack(c *Client, room *Room, msg map[string]interface{}) {
	p, _ := msg["params"].(map[string]interface{})
	seq := msg["seq"]
	action := strings.TrimPrefix(str(msg["opcode"]), "stack/")
	fail := func(code int, text string) { c.sendError(room, seq, code, text) }
	if action != "create" && action != "push" && action != "pushbulk" && action != "peek" && action != "pop" {
		fail(2003, "")
		return
	}
	key, _ := p["key"].(string)
	if key == "" || len(key) > 512 {
		fail(2004, "")
		return
	}
	e := room.entities[key]

	if action == "create" {
		if !c.isHost {
			fail(2023, "")
			return
		}
		if e != nil {
			fail(2006, "")
			return
		}
		if !validACL(p["acl"]) {
			fail(2004, "")
			return
		}
		room.createEntity("stack", key, aclStrings(p["acl"]), map[string]interface{}{"elements": []interface{}{}})
		room.notify(key, false, c.profileID)
		c.sendOk(room, seq)
		return
	}

	if e == nil {
		fail(2005, "no known entity with key "+key)
		return
	}
	if e.Type != "stack" {
		fail(2004, "")
		return
	}
	role, profileID := c.role, c.profileID
	elements := stackElements(e)

	if action == "peek" {
		if !c.isHost && !(aclVisible(e.ACL, role, profileID) && aclReadable(e.ACL, role, profileID)) {
			fail(2023, "")
			return
		}
		size := 1
		if p["size"] != nil {
			n, ok := safeInteger(p["size"])
			if !ok || n < 0 {
				fail(2004, "")
				return
			}
			size = int(n)
		}
		if size > len(elements) {
			size = len(elements)
		}
		vals := make([]interface{}, 0, size)
		for i := len(elements) - 1; i >= len(elements)-size; i-- {
			vals = append(vals, elements[i])
		}
		c.sendEcast(room, map[string]interface{}{"opcode": "stack/elements", "result": map[string]interface{}{"key": key, "vals": vals}}, seq)
		return
	}

	if !c.isHost && (e.Locked || aclLockedFor(e.ACL, role, profileID)) {
		fail(2028, "")
		return
	}
	if action == "pop" {
		if len(elements) == 0 {
			fail(2004, "stack "+key+" is empty")
			return
		}
		val := elements[len(elements)-1]
		e.Extra["elements"] = elements[:len(elements)-1]
		e.Version++
		e.From = profileID
		c.sendEcast(room, map[string]interface{}{"opcode": "stack/element", "result": map[string]interface{}{"key": key, "val": val}}, seq)
		room.notify(key, !c.isHost, profileID)
		return
	}

	var vals []interface{}
	if action == "push" {
		value, exists := p["val"]
		if !exists || value == nil {
			fail(2004, "")
			return
		}
		vals = []interface{}{value}
	} else {
		list, ok := p["vals"].([]interface{})
		if !ok {
			fail(2004, "")
			return
		}
		vals = list
	}
	if len(elements)+len(vals) > maxStackElements {
		fail(2004, "stack "+key+" is full")
		return
	}
	e.Extra["elements"] = append(elements, vals...)
	e.Version++
	e.From = profileID
	room.notify(key, !c.isHost, profileID)
	c.sendOk(room, seq)
}
