package main

//
// LocalBox Go-сервер — вспомогательные функции протокола Ecast (ACL, коды, токены).
// Порт server/lib/util.js. Описывает лишь формат «провода» Jackbox (не объект авторского права).
//

import (
	"math/rand"
	"strings"
)

const codeAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
const hexAlphabet = "0123456789abcdef"

func randInt(min, max int) int { return min + rand.Intn(max-min) }

func makeCode() string {
	b := make([]byte, 4)
	for i := range b {
		b[i] = codeAlphabet[rand.Intn(len(codeAlphabet))]
	}
	return string(b)
}

func makeToken(length int) string {
	if length <= 0 {
		length = 24
	}
	b := make([]byte, length)
	for i := range b {
		b[i] = hexAlphabet[rand.Intn(len(hexAlphabet))]
	}
	return string(b)
}

// Rule — распарсенное ACL-правило: read/write + цель (all | <role> | id:<profileId>).
type Rule struct {
	Read  bool
	Write bool
	To    string // "all" | имя роли | "id"
	ID    string // profileId, если To == "id"
}

// parseAcl разбирает список строк вида "rw *", "r role:audience", "rw id:5".
func parseAcl(list []string) []Rule {
	rules := []Rule{}
	for _, item := range list {
		parts := strings.SplitN(item, " ", 2)
		if len(parts) != 2 {
			continue
		}
		flags, target := parts[0], parts[1]
		r := Rule{Read: strings.Contains(flags, "r"), Write: strings.Contains(flags, "w")}
		switch {
		case target == "*":
			r.To = "all"
		case strings.HasPrefix(target, "role:"):
			r.To = target[len("role:"):]
		case strings.HasPrefix(target, "id:"):
			r.To = "id"
			r.ID = target[len("id:"):]
		default:
			continue
		}
		rules = append(rules, r)
	}
	return rules
}

func ruleHits(r Rule, role string, profileID int) bool {
	return r.To == "all" || r.To == role || (r.To == "id" && r.ID == itoa(profileID))
}

func aclVisible(acl []Rule, role string, profileID int) bool {
	for _, r := range acl {
		if ruleHits(r, role, profileID) {
			return true
		}
	}
	return false
}

func aclReadable(acl []Rule, role string, profileID int) bool {
	for _, r := range acl {
		if ruleHits(r, role, profileID) && r.Read {
			return true
		}
	}
	return false
}

// aclLockedFor — заблокирован ли объект для записи этому клиенту (нет ни одного write-правила).
func aclLockedFor(acl []Rule, role string, profileID int) bool {
	for _, r := range acl {
		if ruleHits(r, role, profileID) && r.Write {
			return false
		}
	}
	return true
}
