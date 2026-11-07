package main

import (
	"math"
	"strconv"
	"strings"
)

func safeInteger(value interface{}) (float64, bool) {
	n, ok := toFloat(value)
	return n, ok && !math.IsNaN(n) && !math.IsInf(n, 0) && math.Trunc(n) == n && math.Abs(n) <= 9007199254740991
}

func validACL(value interface{}) bool {
	if value == nil {
		return true
	}
	items, ok := value.([]interface{})
	if !ok {
		return false
	}
	for _, item := range items {
		if _, ok := item.(string); !ok {
			return false
		}
	}
	return true
}

func audienceChoice(value interface{}) (string, bool) {
	if text, ok := value.(string); ok {
		return text, true
	}
	if number, ok := toFloat(value); ok && !math.IsNaN(number) && !math.IsInf(number, 0) {
		return strconv.FormatFloat(number, 'f', -1, 64), true
	}
	return "", false
}

func dispatchAudience(c *Client, room *Room, msg map[string]interface{}) {
	p := msg["params"].(map[string]interface{})
	parts := strings.Split(str(msg["opcode"]), "/")
	fail := func(code int) { c.sendError(room, msg["seq"], code, "") }
	if len(parts) != 3 {
		fail(2003)
		return
	}
	typ, action := strings.Join(parts[:2], "/"), parts[2]
	if typ != "audience/count-group" && typ != "audience/text-ring" && typ != "audience/g-counter" && typ != "audience/pn-counter" {
		fail(2003)
		return
	}
	key := str(p["name"])
	if key == "" {
		key = str(p["key"])
	}
	if key == "" {
		fail(2004)
		return
	}
	e := room.entities[key]
	if action == "create" {
		if !c.isHost {
			fail(2023)
			return
		}
		if e != nil {
			fail(2006)
			return
		}
		if !validACL(p["acl"]) {
			fail(2004)
			return
		}
		content := map[string]interface{}{}
		switch typ {
		case "audience/count-group":
			choices := map[string]interface{}{}
			switch options := p["options"].(type) {
			case []interface{}:
				for _, option := range options {
					name, ok := audienceChoice(option)
					if !ok {
						fail(2004)
						return
					}
					choices[name] = float64(0)
				}
			case map[string]interface{}:
				for name, value := range options {
					count, ok := safeInteger(value)
					if !ok || count < 0 {
						fail(2004)
						return
					}
					choices[name] = count
				}
			default:
				fail(2004)
				return
			}
			content["choices"] = choices
		case "audience/text-ring":
			limit, ok := safeInteger(orDefault(p["limit"], 1000))
			if !ok || limit < 1 || limit > 100000 {
				fail(2004)
				return
			}
			content["elements"], content["limit"] = []interface{}{}, limit
		default:
			count, ok := safeInteger(orDefault(p["count"], 0))
			if !ok || (typ == "audience/g-counter" && count < 0) {
				fail(2004)
				return
			}
			content["count"] = count
		}
		acl := []string{"rw role:audience"}
		if p["acl"] != nil {
			acl = aclStrings(p["acl"])
		}
		e = &Entity{Type: typ, ACL: parseAcl(acl), Version: 1, Extra: content}
		room.entities[key] = e
	} else {
		if e == nil {
			fail(2005)
			return
		}
		if e.Type != typ {
			fail(2004)
			return
		}
		if action == "get" {
			if !c.isHost && !aclReadable(e.ACL, c.role, c.profileID) {
				fail(2023)
				return
			}
			c.sendEcast(room, map[string]interface{}{"opcode": typ, "result": room.getBody(key)}, msg["seq"])
			return
		}
		if !c.isHost && (e.Locked || aclLockedFor(e.ACL, c.role, c.profileID)) {
			fail(2028)
			return
		}
		if typ == "audience/text-ring" {
			if action != "push" {
				fail(2003)
				return
			}
			text, ok := p["text"].(string)
			if !ok {
				fail(2004)
				return
			}
			elements := append(e.Extra["elements"].([]interface{}), text)
			limit := int(e.Extra["limit"].(float64))
			if len(elements) > limit {
				elements = elements[len(elements)-limit:]
			}
			e.Extra["elements"] = elements
		} else {
			times, ok := safeInteger(orDefault(p["times"], 1))
			if !ok || times < 0 {
				fail(2004)
				return
			}
			if typ == "audience/count-group" {
				if action != "increment" {
					fail(2003)
					return
				}
				choices := e.Extra["choices"].(map[string]interface{})
				vote, valid := audienceChoice(p["vote"])
				if !valid {
					fail(2004)
					return
				}
				old, exists := choices[vote]
				count, ok := safeInteger(toFloatOr(old, 0) + times)
				if !exists || !ok {
					fail(2004)
					return
				}
				choices[vote] = count
			} else {
				if action != "increment" && !(action == "decrement" && typ == "audience/pn-counter") {
					fail(2003)
					return
				}
				if action == "decrement" {
					times = -times
				}
				count, ok := safeInteger(toFloatOr(e.Extra["count"], 0) + times)
				if !ok {
					fail(2004)
					return
				}
				e.Extra["count"] = count
			}
		}
		e.Version++
		e.From = c.profileID
	}
	room.notify(key, !c.isHost, c.profileID)
	c.sendOk(room, msg["seq"])
}
